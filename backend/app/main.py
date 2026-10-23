from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.config.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestLoggingMiddleware, SecurityHeadersMiddleware
from app.core.production_security import IdempotencyMiddleware, RateLimitingMiddleware
from app.core.redis import redis_manager
from app.database.session import engine
from app.jobs.scheduler.cron_manager import cron_scheduler, initialize_default_cron_jobs

setup_logging()

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup Tasks ---
    logger.info(
        "Starting up FastAPI application",
        app_name=settings.APP_NAME,
        env=settings.APP_ENV,
        debug_mode=settings.DEBUG,
    )

    # 1. Verification of DB connectivity (skip during tests)
    try:
        if settings.APP_ENV != "testing":
            async with engine.begin() as conn:
                await conn.exec_driver_sql("SELECT 1")
                if settings.get_database_url.startswith("sqlite"):
                    import app.enterprise.models  # noqa: F401
                    import app.models.advanced_ai  # noqa: F401
                    import app.models.analytics  # noqa: F401
                    import app.models.dataset  # noqa: F401
                    import app.models.evaluation  # noqa: F401
                    import app.models.project  # noqa: F401
                    import app.platform.models  # noqa: F401
                    from app.database.session import Base

                    await conn.run_sync(Base.metadata.create_all)
            logger.info("Database connectivity verified successfully.")
    except Exception as e:
        logger.error("Database connection check failed during startup.", error=str(e))

    # 2. Initialization of Redis connection manager
    try:
        redis_manager.init(settings.get_redis_url)
        redis_alive = await redis_manager.ping()
        if redis_alive:
            logger.info("Redis connectivity verified successfully.")
        else:
            logger.warning(
                "Redis is unreachable or degraded. Disabling Redis client for fast in-memory fallback."
            )
            redis_manager.client = None
    except Exception as e:
        logger.error(
            "Redis connection initialization failed during startup.", error=str(e)
        )
        redis_manager.client = None

    # 3. Initialize and start Cron Scheduler
    try:
        initialize_default_cron_jobs()
        if settings.APP_ENV != "testing":
            cron_scheduler.start()
            logger.info("Periodic cron job scheduler started successfully.")
    except Exception as e:
        logger.error("Failed to start cron job scheduler.", error=str(e))

    yield

    # --- Shutdown Tasks ---
    logger.info("Shutting down FastAPI application")

    # 1. Gracefully stop Cron Scheduler
    cron_scheduler.stop()

    # 2. Gracefully close Redis connections
    await redis_manager.close()

    # 3. Dispose of database connections
    await engine.dispose()
    logger.info("All connection resources released.")


app = FastAPI(
    title="Evalium API",
    description=(
        "🚀 **Evalium** — Production-grade AI Evaluation Infrastructure.\n\n"
        "This API establishes the scalable core backend foundation supporting "
        "high-throughput project and evaluation lifecycle management.\n\n"
        "**Key Features:**\n"
        "* **Clean Architecture**: Layered API routes, service business logic, and database repositories.\n"
        "* **High Performance**: Asynchronous database connection pooling with SQLAlchemy 2.0 & PostgreSQL.\n"
        "* **Resiliency**: Built-in health check, liveness, and readiness probes.\n"
        "* **Security Headers**: Standard production-grade security and request validation middleware.\n"
        "* **Structured Logging**: Contextvars-based correlation (Request ID) tracking across operations."
    ),
    version="1.0.0",
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url="/redoc" if settings.APP_ENV != "production" else None,
    openapi_url="/openapi.json" if settings.APP_ENV != "production" else None,
    lifespan=lifespan,
)

# Warn about insecure CORS configuration in production
if settings.CORS_ORIGINS == ["*"] and settings.APP_ENV == "production":
    logger.warning(
        "CORS is configured to allow all origins (CORS_ORIGINS='*'). "
        "This is insecure and should be restricted in production."
    )

# Register Middlewares (Outermost first for request execution, innermost first for response headers)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitingMiddleware, requests_per_minute=300)
app.add_middleware(IdempotencyMiddleware)

# GZip Compression Middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Trusted Host Middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS,
)

# Request logging and Request ID Middleware (Outermost wrapper)
app.add_middleware(RequestLoggingMiddleware)

# Register API routes under /api/v1 prefix
app.include_router(api_router, prefix=settings.API_V1_STR)


# Root level health endpoint for cloud load balancers and Railway probes
@app.get("/health", include_in_schema=False)
async def root_health_check():
    """Root health check endpoint for reverse proxies and container orchestrators."""
    return {"status": "healthy", "service": settings.APP_NAME}


# Register custom global exception handlers
register_exception_handlers(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # nosec B104
        port=settings.PORT,
        reload=settings.APP_ENV == "development",
    )

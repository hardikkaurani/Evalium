import os
import re
import sys
import time
import uuid
from typing import Optional

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.config import settings
from app.core.metrics import normalize_route_path, record_http_metrics

logger = structlog.get_logger()

CORRELATION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def validate_correlation_id(raw_id: Optional[str]) -> Optional[str]:
    """Validates raw correlation header to ensure length and character safety."""
    if not raw_id:
        return None
    stripped = raw_id.strip()
    if CORRELATION_ID_PATTERN.match(stripped):
        return stripped
    return None


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for tracking request correlation IDs, trace IDs, and logging execution time.

    Generates or validates request and trace IDs for every incoming request,
    binds them to structlog contextvars, measures request execution time, and
    ensures context cleanup after request completion.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        structlog.contextvars.clear_contextvars()

        raw_req_id = request.headers.get("X-Request-ID")
        request_id = validate_correlation_id(raw_req_id) or str(uuid.uuid4())

        raw_trace_id = request.headers.get("X-Trace-ID") or request.headers.get(
            "traceparent"
        )
        trace_id = validate_correlation_id(raw_trace_id) or str(uuid.uuid4())

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
        )

        start_time = time.perf_counter()
        status_code = 500

        logger.info(
            "Request started",
            client_host=request.client.host if request.client else None,
        )

        try:
            response = await call_next(request)
            status_code = response.status_code
            duration = time.perf_counter() - start_time
            duration_ms = round(duration * 1000, 2)

            logger.info(
                "Request finished",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )

            response.headers["X-Request-ID"] = request_id
            response.headers["X-Trace-ID"] = trace_id
            response.headers["X-Process-Time"] = f"{duration:.6f}s"

            return response
        except Exception as exc:
            status_code = 500
            duration = time.perf_counter() - start_time
            logger.error(
                "Request failed with unhandled exception",
                duration_ms=round(duration * 1000, 2),
                error=str(exc),
            )
            raise exc from None
        finally:
            duration = time.perf_counter() - start_time
            route_template = normalize_route_path(request)
            record_http_metrics(
                method=request.method,
                route=route_template,
                status_code=status_code,
                duration_seconds=duration,
            )
            structlog.contextvars.clear_contextvars()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to inject standard production-grade security headers."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Set standard security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "no-referrer-when-downgrade"

        # Content-Security-Policy setup
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )

        # HSTS header (Strict-Transport-Security) for HTTPS in production
        if settings.APP_ENV == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware for enforcing distributed sliding-window rate limiting across endpoints."""

    EXEMPT_PATHS = {
        "/health",
        "/ready",
        "/live",
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/live",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/favicon.ico",
    }

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in self.EXEMPT_PATHS:
            return await call_next(request)

        is_test_env = (
            "pytest" in sys.modules
            or settings.APP_ENV == "testing"
            or os.getenv("TESTING") == "1"
        )
        if is_test_env and not request.headers.get("X-Test-Enforce-Rate-Limit"):
            return await call_next(request)

        api_key_token = request.headers.get("X-API-Key")
        if not api_key_token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                api_key_token = auth_header.split(" ", 1)[1].strip()

        api_key_record = None
        db_session = None

        if api_key_token:
            try:
                from app.database.session import SessionLocal
                from app.enterprise.services.apikey_service import (
                    EnterpriseAPIKeyService,
                )

                async with SessionLocal() as db:
                    key_service = EnterpriseAPIKeyService()
                    api_key_record = await key_service.validate_key(db, api_key_token)
                    db_session = db
            except Exception as exc:
                logger.debug("Rate limit auth token resolution skipped", error=str(exc))

        from app.core.rate_limiter import RateLimiter

        result = await RateLimiter.check(
            request, api_key_record=api_key_record, db=db_session
        )

        if not result.allowed:
            from fastapi.responses import JSONResponse

            headers = {
                "Retry-After": str(result.reset_seconds),
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(result.reset_seconds),
            }
            content = {
                "success": False,
                "message": "Too Many Requests. Rate limit exceeded.",
                "data": {
                    "error": f"Rate limit exceeded. Please retry after {result.reset_seconds} seconds.",
                    "retry_after": result.reset_seconds,
                    "scope": result.scope,
                },
            }
            return JSONResponse(status_code=429, content=content, headers=headers)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(result.reset_seconds)
        return response

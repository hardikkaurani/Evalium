import hashlib
import json
import os
import sys
import time

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.config import settings
from app.core.rate_limiter import RateLimiter as NewRateLimiter
from app.core.rate_limiter import RateLimitFallback
from app.core.redis import redis_manager

logger = structlog.get_logger()


class RateLimiter:
    """Legacy compatibility RateLimiter wrapper."""

    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self._fallback = RateLimitFallback(max_keys=1000)

    async def is_allowed(self, client_key: str) -> bool:
        res = self._fallback.check(client_key, self.requests_per_minute, time.time())
        return res.allowed


class RateLimitingMiddleware(BaseHTTPMiddleware):
    """Middleware enforcing sliding-window rate limit checks per IP or API key with tier resolution."""

    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        exempt = {
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
        if request.url.path in exempt:
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

        if api_key_token:
            try:
                from app.enterprise.services.apikey_service import (
                    EnterpriseAPIKeyService,
                )

                key_service = EnterpriseAPIKeyService()
                api_key_record = await key_service.validate_key_cached(
                    None, api_key_token
                )
            except Exception as exc:
                logger.debug("Rate limit auth token resolution skipped", error=str(exc))

        result = await NewRateLimiter.check(request, api_key_record=api_key_record)

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


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Middleware validating X-Idempotency-Key headers to prevent duplicate execution of mutating actions."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)

        idempotency_key = request.headers.get("X-Idempotency-Key")
        if not idempotency_key:
            return await call_next(request)

        # Never retain newly generated credentials or buffer file uploads.
        if (
            "/api-keys" in request.url.path
            or "application/json" not in request.headers.get("content-type", "")
        ):
            return await call_next(request)

        # Scope cached responses to the credential, endpoint, and exact payload.
        # A caller-provided idempotency key must never retrieve another tenant's response.
        credential = request.headers.get("X-API-Key") or request.headers.get(
            "Authorization", ""
        )
        if not credential:
            return await call_next(request)
        body = await request.body()
        fingerprint = hashlib.sha256(
            credential.encode()
            + b"\0"
            + request.method.encode()
            + b"\0"
            + str(request.url).encode()
            + b"\0"
            + body
        ).hexdigest()
        redis_key = f"idempotency:{fingerprint}:{idempotency_key}"

        try:
            if redis_manager.client:
                cached_res = await redis_manager.client.get(redis_key)
                if cached_res:
                    # Revoked, expired, or reduced-scope keys cannot replay a cached success.
                    from fastapi import HTTPException

                    from app.core.dependencies import get_current_api_key
                    from app.database.session import SessionLocal

                    async with SessionLocal() as db:
                        try:
                            await get_current_api_key(
                                request.headers.get("X-API-Key"), db, request
                            )
                        except HTTPException:
                            return await call_next(request)
                    data = json.loads(cached_res)
                    logger.info(
                        "Duplicate request prevented by Idempotency Key",
                        key=idempotency_key,
                    )
                    return Response(
                        content=data.get("body", ""),
                        status_code=data.get("status_code", 200),
                        headers=data.get("headers", {}),
                    )
        except Exception as e:
            logger.warning("Redis idempotency validation error.", error=str(e))

        response: Response = await call_next(request)

        # Store response details if status is success/created
        if response.status_code in (200, 201, 202, 204):
            try:
                if redis_manager.client:
                    # Capture body if possible (only for simple text/json responses)
                    body_bytes = b""
                    # Read response body chunks safely
                    async for chunk in response.body_iterator:
                        body_bytes += chunk
                    # Reconstruct body_iterator so subsequent handlers/clients can read it
                    response.body_iterator = self._recreate_iterator(body_bytes)

                    payload = {
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "body": body_bytes.decode("utf-8", errors="ignore"),
                    }
                    await redis_manager.client.setex(
                        redis_key, 86400, json.dumps(payload)
                    )  # 24h retention
            except Exception as e:
                logger.warning(
                    "Failed to cache response payload for idempotency key.",
                    error=str(e),
                )

        return response

    async def _recreate_iterator(self, body_bytes: bytes):
        yield body_bytes

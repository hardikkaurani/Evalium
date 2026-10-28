from typing import Any, Optional
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_api_key
from app.database.session import get_db
from app.enterprise.exceptions import (
    OAuthConfigurationException,
    OAuthConflictException,
    OAuthException,
    OAuthStateInvalidException,
    OAuthVerificationException,
)
from app.enterprise.schemas import OAuthSessionResponse
from app.enterprise.services.credentials_auth_service import CredentialsAuthService
from app.enterprise.services.google_oauth_service import (
    GoogleOAuthService,
    is_safe_redirect_url,
)
from app.utils.responses import create_response

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["Authentication & Single Sign-On"])


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


class EmailPasswordLoginRequest(BaseModel):
    email: str
    password: str


class EmailPasswordRegisterRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


@router.get("/status", summary="Inspect available authentication methods")
async def get_auth_status():
    """Returns availability status of configured authentication methods without exposing secrets."""
    service = GoogleOAuthService()
    return create_response(
        success=True,
        message="Authentication status retrieved.",
        data={
            "google_oauth_enabled": service.is_configured(),
            "credentials_enabled": True,
        },
    )


@router.post(
    "/register",
    summary="Register user with email and password",
    status_code=status.HTTP_201_CREATED,
)
async def register_user_endpoint(
    payload: EmailPasswordRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Registers a new user account, provisions an enterprise workspace, and returns an active session API key."""
    service = CredentialsAuthService()
    try:
        session_res = await service.register_user(
            db,
            email=payload.email,
            password=payload.password,
            display_name=payload.name,
        )
    except OAuthConflictException as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except OAuthVerificationException as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return create_response(
        success=True,
        message="Registration successful.",
        data=session_res.model_dump(),
    )


@router.post("/login", summary="Sign in with email and password")
async def login_user_endpoint(
    payload: EmailPasswordLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticates email and password credentials and issues an active workspace session API key."""
    service = CredentialsAuthService()
    try:
        session_res = await service.login_user(
            db,
            email=payload.email,
            password=payload.password,
        )
    except OAuthVerificationException as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    return create_response(
        success=True,
        message="Login successful.",
        data=session_res.model_dump(),
    )


@router.get("/google/start", summary="Initiate Google OAuth 2.0 / OpenID Connect login")
async def google_oauth_start(
    request: Request,
    return_to: Optional[str] = Query(
        None, description="Safe relative redirect destination"
    ),
    format: Optional[str] = Query(
        None, description="Set to 'json' to receive auth_url payload"
    ),
):
    """Generates a cryptographically secure CSRF state token and redirects to Google's consent screen."""
    service = GoogleOAuthService()
    if not service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server.",
        )

    if return_to and not is_safe_redirect_url(return_to, service.allowed_origins):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid return_to destination. External redirects are prohibited.",
        )

    try:
        flow_data = await service.generate_auth_flow(return_to=return_to)
    except OAuthConfigurationException as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    accept_header = request.headers.get("accept", "")
    if format == "json" or "application/json" in accept_header:
        return create_response(
            success=True,
            message="Google OAuth authorization URL generated.",
            data=flow_data,
        )

    return RedirectResponse(
        url=flow_data["auth_url"], status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )


@router.get("/google/callback", summary="Google OAuth 2.0 browser redirect callback")
async def google_oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Processes Google OAuth callback, verifies identity, provisions account, and issues active session key."""
    service = GoogleOAuthService()
    accept_header = request.headers.get("accept", "")
    is_browser = "text/html" in accept_header

    # Handle provider cancellation or denial
    if error:
        safe_error = "oauth_cancelled" if error == "access_denied" else "oauth_failed"
        logger.warning(
            "Google OAuth provider error",
            error=error,
            provider="google",
        )
        if is_browser:
            return RedirectResponse(
                url=f"{service.frontend_url}/login?error={quote(safe_error)}",
                status_code=status.HTTP_302_FOUND,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google OAuth authentication was cancelled or rejected by user.",
        )

    if not code or not state:
        logger.warning("Google OAuth callback missing required code or state parameter")
        if is_browser:
            return RedirectResponse(
                url=f"{service.frontend_url}/login?error=missing_parameters",
                status_code=status.HTTP_302_FOUND,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required code or state parameter.",
        )

    # 1. Validate state CSRF token (single-use, signed, unexpired)
    try:
        state_data = await service.validate_state(state)
    except OAuthStateInvalidException as exc:
        logger.warning("Google OAuth state validation failed", reason=str(exc))
        if is_browser:
            return RedirectResponse(
                url=f"{service.frontend_url}/login?error=invalid_state",
                status_code=status.HTTP_302_FOUND,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    # 2. Exchange code with Google
    try:
        tokens = await service.exchange_code_for_tokens(code)
    except OAuthException as exc:
        logger.warning("Google OAuth token exchange failed", reason=str(exc))
        if is_browser:
            return RedirectResponse(
                url=f"{service.frontend_url}/login?error=exchange_failed",
                status_code=status.HTTP_302_FOUND,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange authorization code with Google.",
        ) from exc

    # 3. Verify OpenID Connect ID token
    try:
        claims = await service.verify_id_token(
            tokens["id_token"], expected_nonce=state_data.get("nonce")
        )
    except OAuthVerificationException as exc:
        logger.warning("Google OAuth ID token verification failed", reason=str(exc))
        if is_browser:
            return RedirectResponse(
                url=f"{service.frontend_url}/login?error=verification_failed",
                status_code=status.HTTP_302_FOUND,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    # 4. Authenticate or provision user and issue session API key
    try:
        session_res: OAuthSessionResponse = await service.authenticate_google_user(
            db, claims, return_to=state_data.get("return_to", "/overview")
        )
    except OAuthConflictException as exc:
        logger.warning("Google identity linking conflict", reason=str(exc))
        if is_browser:
            return RedirectResponse(
                url=f"{service.frontend_url}/login?error=account_conflict",
                status_code=status.HTTP_302_FOUND,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error("Google user authentication failed", error=str(exc))
        if is_browser:
            return RedirectResponse(
                url=f"{service.frontend_url}/login?error=auth_error",
                status_code=status.HTTP_302_FOUND,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to authenticate user session.",
        ) from exc

    # Redirect to frontend callback route with API key in URL fragment for security
    dest = (
        f"{service.frontend_url}/auth/callback"
        f"#api_key={quote(session_res.api_key)}"
        f"&return_to={quote(session_res.return_to)}"
    )
    return RedirectResponse(url=dest, status_code=status.HTTP_302_FOUND)


@router.post(
    "/google/callback",
    response_model=dict,
    summary="Google OAuth 2.0 programmatic / SPA callback",
)
async def google_oauth_callback_post(
    payload: OAuthCallbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """Programmatic callback endpoint for SPAs or testing harnesses."""
    service = GoogleOAuthService()
    if not service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server.",
        )

    state_data = await service.validate_state(payload.state)
    tokens = await service.exchange_code_for_tokens(payload.code)
    claims = await service.verify_id_token(
        tokens["id_token"], expected_nonce=state_data.get("nonce")
    )
    session_res = await service.authenticate_google_user(
        db, claims, return_to=state_data.get("return_to", "/overview")
    )
    return create_response(
        success=True,
        message="Authentication successful.",
        data=session_res.model_dump(),
    )


@router.get("/me", summary="Get authenticated identity information")
async def get_current_user_profile(
    current_key: Any = Depends(get_current_api_key),
):
    """Returns caller's active session metadata and organization context."""
    return create_response(
        success=True,
        message="Current user profile retrieved.",
        data={
            "name": getattr(current_key, "name", "Active Session"),
            "organization_id": (
                str(current_key.organization_id)
                if current_key.organization_id
                else None
            ),
            "workspace_id": (
                str(current_key.workspace_id) if current_key.workspace_id else None
            ),
            "scopes": current_key.scopes,
        },
    )

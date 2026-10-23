import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse

import httpx
import jwt
import structlog
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.config import settings
from app.core.redis import redis_manager
from app.enterprise.exceptions import (
    OAuthConfigurationException,
    OAuthConflictException,
    OAuthException,
    OAuthStateInvalidException,
    OAuthVerificationException,
)
from app.enterprise.models import Membership, OAuthIdentity
from app.enterprise.schemas import OAuthSessionResponse
from app.enterprise.services.apikey_service import EnterpriseAPIKeyService
from app.enterprise.services.organization_service import OrganizationService
from app.enterprise.services.workspace_service import WorkspaceService

logger = structlog.get_logger()


def is_safe_redirect_url(
    url: Optional[str], allowed_origins: Optional[List[str]] = None
) -> bool:
    """Validates that a URL is a safe internal relative path or belongs to explicitly trusted origins."""
    if not url or not isinstance(url, str):
        return False
    # Check for CRLF / control characters to prevent header injection
    if any(c in url for c in ("\r", "\n", "\t", "\x00")):
        return False
    clean = url.strip()
    # Reject protocol-relative URLs (//evil.com, /\evil.com, or \\evil.com)
    if clean.startswith("//") or clean.startswith("/\\") or clean.startswith("\\\\"):
        return False
    # If relative path starting with /
    if clean.startswith("/"):
        parsed = urlparse(clean)
        # Scheme or netloc must NOT be present in relative path
        if not parsed.scheme and not parsed.netloc:
            return True
        return False
    # If absolute URL, verify scheme and netloc against allowed origins
    parsed = urlparse(clean)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        if allowed_origins:
            origin = f"{parsed.scheme}://{parsed.netloc}"
            return origin in allowed_origins
    return False


_UNSET: Any = object()


class GoogleOAuthService:
    """Production-grade service handling Google OAuth 2.0 / OpenID Connect authentication."""

    GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # nosec B105
    GOOGLE_JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
    STATE_EXPIRATION_SECONDS = 600  # 10 minutes

    # In-memory JWKS cache: {"keys": {...}, "expires_at": float}
    _jwks_cache: Dict[str, Any] = {}
    # In-memory single-use state fallback for test environments without live Redis
    _memory_state_cache: Dict[str, float] = {}

    def __init__(
        self,
        client_id: Any = _UNSET,
        client_secret: Any = _UNSET,
        redirect_uri: Any = _UNSET,
        frontend_url: Any = _UNSET,
    ):
        if client_id is _UNSET:
            self.client_id = settings.GOOGLE_CLIENT_ID
        else:
            self.client_id = client_id

        if client_secret is _UNSET:
            secret_val = (
                settings.GOOGLE_CLIENT_SECRET.get_secret_value()
                if settings.GOOGLE_CLIENT_SECRET
                else None
            )
        else:
            secret_val = client_secret
        self.client_secret = secret_val

        if redirect_uri is _UNSET:
            self.redirect_uri = settings.GOOGLE_REDIRECT_URI
        else:
            self.redirect_uri = redirect_uri

        if frontend_url is _UNSET:
            self.frontend_url = (
                settings.FRONTEND_URL or "http://localhost:5173"
            ).rstrip("/")
        else:
            self.frontend_url = (frontend_url or "http://localhost:5173").rstrip("/")

        secret_key_val = (
            settings.SECRET_KEY.get_secret_value()
            if settings.SECRET_KEY
            else "evalforge-secret"
        )
        self.secret_key = secret_key_val

        self.allowed_origins = [
            self.frontend_url,
            "http://localhost:5173",
            "http://localhost:4173",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:4173",
        ]
        for origin in settings.CORS_ORIGINS:
            if origin and origin != "*":
                self.allowed_origins.append(origin.rstrip("/"))

    def is_configured(self) -> bool:
        """Returns True only when required Google OAuth client credentials are configured."""
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise OAuthConfigurationException(
                "Google OAuth is not configured on this server."
            )

    async def _store_state(self, state_token: str, exp: int) -> None:
        """Stores state token in Redis with TTL or in-memory fallback."""
        key = f"oauth_state:{hashlib.sha256(state_token.encode()).hexdigest()}"
        client = None
        try:
            client = redis_manager.get_client()
        except Exception:
            client = None

        stored = False
        if client:
            try:
                await client.setex(key, self.STATE_EXPIRATION_SECONDS, "1")
                stored = True
            except Exception as e:
                logger.debug(
                    "Redis state store failed, using memory cache fallback",
                    error=str(e),
                )
        if not stored:
            self._memory_state_cache[key] = float(exp)

    async def _consume_state(self, state_token: str) -> bool:
        """Atomically checks and removes state token ensuring strict single-use."""
        key = f"oauth_state:{hashlib.sha256(state_token.encode()).hexdigest()}"
        client = None
        try:
            client = redis_manager.get_client()
        except Exception:
            client = None

        if client:
            try:
                deleted = await client.delete(key)
                if deleted and deleted > 0:
                    return True
            except Exception as e:
                logger.debug(
                    "Redis state delete failed, checking memory fallback", error=str(e)
                )

        now = time.time()
        if key in self._memory_state_cache:
            exp = self._memory_state_cache.pop(key)
            return exp >= now
        return False

    async def generate_auth_flow(
        self, return_to: Optional[str] = None
    ) -> Dict[str, str]:
        """Generates Google authorization URL, secure CSRF state token, and OIDC nonce."""
        self._require_configured()

        safe_return = (
            return_to
            if is_safe_redirect_url(return_to, self.allowed_origins)
            else "/overview"
        )
        nonce = secrets.token_hex(16)
        exp = int(time.time()) + self.STATE_EXPIRATION_SECONDS
        payload = {
            "nonce": nonce,
            "exp": exp,
            "return_to": safe_return,
            "rand": secrets.token_hex(16),
        }
        raw_payload = json.dumps(payload, sort_keys=True)
        payload_b64 = base64.urlsafe_b64encode(raw_payload.encode()).decode()
        sig = hmac.new(
            self.secret_key.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        state_token = f"{payload_b64}.{sig}"

        await self._store_state(state_token, exp)

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state_token,
            "nonce": nonce,
            "access_type": "online",
            "prompt": "select_account",
        }
        auth_url = f"{self.GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"
        return {"auth_url": auth_url, "state": state_token, "nonce": nonce}

    async def validate_state(self, state_token: Optional[str]) -> Dict[str, Any]:
        """Validates OAuth state token HMAC signature, expiration, and ensures single-use consumption."""
        if not state_token or not isinstance(state_token, str):
            raise OAuthStateInvalidException(
                "Missing or invalid OAuth state parameter."
            )

        parts = state_token.split(".")
        if len(parts) != 2:
            raise OAuthStateInvalidException("Malformed OAuth state parameter.")

        payload_b64, sig = parts
        expected_sig = hmac.new(
            self.secret_key.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise OAuthStateInvalidException(
                "OAuth state signature verification failed."
            )

        try:
            raw_payload = base64.urlsafe_b64decode(payload_b64.encode()).decode()
            payload = json.loads(raw_payload)
        except Exception as exc:
            raise OAuthStateInvalidException(
                "Failed to decode OAuth state payload."
            ) from exc

        if payload.get("exp", 0) < time.time():
            raise OAuthStateInvalidException(
                "OAuth state has expired. Please try logging in again."
            )

        consumed = await self._consume_state(state_token)
        if not consumed:
            raise OAuthStateInvalidException(
                "OAuth state has already been used or was revoked."
            )

        return payload

    async def exchange_code_for_tokens(
        self, code: str, client: Optional[httpx.AsyncClient] = None
    ) -> Dict[str, Any]:
        """Exchanges authorization code for Google tokens without logging secrets."""
        self._require_configured()
        if not code or not isinstance(code, str) or not code.strip():
            raise OAuthException("Authorization code is required.")

        data = {
            "code": code.strip(),
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }

        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=10.0)
            should_close = True

        try:
            resp = await client.post(self.GOOGLE_TOKEN_ENDPOINT, data=data)
            if resp.status_code != 200:
                logger.warning(
                    "Google token exchange failed",
                    status_code=resp.status_code,
                )
                raise OAuthException(
                    f"Failed to exchange authorization code with Google (HTTP {resp.status_code})."
                )
            tokens = resp.json()
            if "id_token" not in tokens:
                raise OAuthVerificationException(
                    "Google token response missing id_token."
                )
            return tokens
        except httpx.RequestError as exc:
            logger.warning(
                "Google token endpoint network request failed", error=str(exc)
            )
            raise OAuthException("Unable to reach Google OAuth token service.") from exc
        finally:
            if should_close:
                await client.aclose()

    async def _fetch_jwks(
        self, client: Optional[httpx.AsyncClient] = None
    ) -> List[Dict[str, Any]]:
        """Fetches Google's public JWKS certificates with in-memory caching."""
        now = time.time()
        if "keys" in self._jwks_cache and self._jwks_cache.get("expires_at", 0) > now:
            return self._jwks_cache["keys"]

        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=10.0)
            should_close = True

        try:
            resp = await client.get(self.GOOGLE_JWKS_ENDPOINT)
            if resp.status_code != 200:
                raise OAuthVerificationException(
                    "Failed to fetch Google JWKS public keys."
                )
            data = resp.json()
            keys = data.get("keys", [])
            self._jwks_cache = {"keys": keys, "expires_at": now + 3600}
            return keys
        except httpx.RequestError as exc:
            raise OAuthVerificationException(
                "Unable to reach Google JWKS certs endpoint."
            ) from exc
        finally:
            if should_close:
                await client.aclose()

    async def verify_id_token(
        self,
        id_token: str,
        expected_nonce: Optional[str] = None,
        custom_jwks: Optional[List[Dict[str, Any]]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """Validates Google OpenID Connect ID token signature, issuer, audience, and claims."""
        self._require_configured()
        if not id_token or not isinstance(id_token, str):
            raise OAuthVerificationException("Missing ID token.")

        try:
            unverified_header = jwt.get_unverified_header(id_token)
        except Exception as exc:
            raise OAuthVerificationException(f"Invalid ID token header: {exc}") from exc

        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg")
        if alg != "RS256":
            raise OAuthVerificationException(
                f"Unsupported ID token algorithm: {alg}. Expected RS256."
            )

        jwks_keys = (
            custom_jwks
            if custom_jwks is not None
            else await self._fetch_jwks(client=client)
        )
        matched_key = next((k for k in jwks_keys if k.get("kid") == kid), None)
        if not matched_key:
            raise OAuthVerificationException(
                "Public key for ID token kid was not found in JWKS."
            )

        try:
            public_key = RSAAlgorithm.from_jwk(matched_key)
        except Exception as exc:
            raise OAuthVerificationException(
                f"Failed to load RSA public key from JWK: {exc}"
            ) from exc

        try:
            claims = jwt.decode(
                id_token,
                key=public_key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=["https://accounts.google.com", "accounts.google.com"],
                options={"require": ["sub", "iss", "aud", "exp"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise OAuthVerificationException("Google ID token has expired.") from exc
        except jwt.InvalidAudienceError as exc:
            raise OAuthVerificationException(
                "Google ID token audience does not match configured client ID."
            ) from exc
        except jwt.InvalidIssuerError as exc:
            raise OAuthVerificationException(
                "Google ID token issuer is invalid."
            ) from exc
        except Exception as exc:
            raise OAuthVerificationException(
                f"Google ID token validation failed: {exc}"
            ) from exc

        # Nonce verification
        if expected_nonce is not None:
            token_nonce = claims.get("nonce")
            if token_nonce != expected_nonce:
                raise OAuthVerificationException(
                    "Google ID token nonce does not match expected session nonce."
                )

        # Email verification check
        email_verified = claims.get("email_verified")
        if email_verified is not True and str(email_verified).lower() != "true":
            raise OAuthVerificationException("Google account email is not verified.")

        sub = claims.get("sub")
        if not sub or not isinstance(sub, str):
            raise OAuthVerificationException(
                "Google ID token missing valid subject identifier (sub)."
            )

        return claims

    async def authenticate_google_user(
        self,
        db: AsyncSession,
        claims: Dict[str, Any],
        return_to: str = "/overview",
    ) -> OAuthSessionResponse:
        """Provisions or logs in the user based on verified Google subject ID and issues session API key."""
        sub = str(claims["sub"]).strip()
        email = str(claims.get("email", "")).strip().lower()
        if not email:
            raise OAuthVerificationException(
                "Google identity claims did not provide an email address."
            )

        display_name = claims.get("name")
        avatar_url = claims.get("picture")

        # 1. Check for existing OAuth identity by canonical sub
        stmt = select(OAuthIdentity).where(
            OAuthIdentity.provider == "google",
            OAuthIdentity.provider_user_id == sub,
        )
        res = await db.execute(stmt)
        existing_identity = res.scalar_one_or_none()

        org_service = OrganizationService()
        ws_service = WorkspaceService()
        key_service = EnterpriseAPIKeyService()

        target_user_id: uuid.UUID
        target_org_id: uuid.UUID
        target_ws_id: Optional[uuid.UUID] = None

        if existing_identity:
            # CASE A: Existing linked identity
            target_user_id = existing_identity.user_id
            if display_name:
                existing_identity.display_name = display_name
            if avatar_url:
                existing_identity.avatar_url = avatar_url
            existing_identity.email_verified = True

            # Retrieve active organization & workspace from user membership
            m_stmt = (
                select(Membership)
                .where(
                    Membership.user_id == target_user_id,
                    Membership.is_active.is_(True),
                )
                .order_by(Membership.created_at.asc())
            )
            m_res = await db.execute(m_stmt)
            membership = m_res.scalars().first()

            if membership:
                target_org_id = membership.organization_id
                target_ws_id = membership.workspace_id
                if not target_ws_id:
                    workspaces = await ws_service.list_workspaces(db, target_org_id)
                    if workspaces:
                        target_ws_id = workspaces[0].id
            else:
                # Provision fallback personal org if missing
                org_name = f"{display_name or email.split('@')[0]}'s Org"
                new_org = await org_service.create_organization(
                    db, name=org_name, user_id=target_user_id
                )
                new_ws = await ws_service.create_workspace(
                    db, org_id=new_org.id, name="Default Workspace"
                )
                target_org_id = new_org.id
                target_ws_id = new_ws.id
        else:
            # CASE B: Identity does not exist
            # Prevent malicious cross-identity account takeover if email already linked to another sub
            conflict_stmt = select(OAuthIdentity).where(
                OAuthIdentity.provider == "google",
                OAuthIdentity.email == email,
            )
            conflict_res = await db.execute(conflict_stmt)
            conflict = conflict_res.scalar_one_or_none()
            if conflict and conflict.provider_user_id != sub:
                logger.warning(
                    "Google identity linking conflict rejected",
                    provider="google",
                    sub_provided=sub,
                    sub_existing=conflict.provider_user_id,
                )
                raise OAuthConflictException(
                    "Identity conflict: this email is already registered to a different Google account."
                )

            # Provision new user
            target_user_id = uuid.uuid4()
            new_identity = OAuthIdentity(
                id=uuid.uuid4(),
                user_id=target_user_id,
                provider="google",
                provider_user_id=sub,
                email=email,
                email_verified=True,
                display_name=display_name,
                avatar_url=avatar_url,
            )
            db.add(new_identity)
            await db.flush()

            # Provision user personal organization and default workspace
            org_name = f"{display_name or email.split('@')[0]}'s Org"
            org = await org_service.create_organization(
                db, name=org_name, user_id=target_user_id
            )
            ws = await ws_service.create_workspace(
                db,
                org_id=org.id,
                name="Default Workspace",
                description="Default workspace provisioned via Google SSO",
            )
            target_org_id = org.id
            target_ws_id = ws.id

        # Issue active session EnterpriseAPIKey
        raw_key, key_record = await key_service.generate_key(
            db,
            name=f"Google SSO - {email}",
            org_id=target_org_id,
            workspace_id=target_ws_id,
            scopes=["*"],
            expires_in_days=30,
        )
        await db.commit()

        logger.info(
            "Google OAuth login successful",
            provider="google",
            user_id=str(target_user_id),
            organization_id=str(target_org_id),
            workspace_id=str(target_ws_id) if target_ws_id else None,
        )

        safe_return = (
            return_to
            if is_safe_redirect_url(return_to, self.allowed_origins)
            else "/overview"
        )

        return OAuthSessionResponse(
            api_key=raw_key,
            user_id=str(target_user_id),
            email=email,
            display_name=display_name,
            avatar_url=avatar_url,
            organization_id=str(target_org_id),
            workspace_id=str(target_ws_id) if target_ws_id else None,
            expires_at=key_record.expires_at,
            return_to=safe_return,
        )

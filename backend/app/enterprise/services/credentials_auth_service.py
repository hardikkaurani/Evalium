import hashlib
import hmac
import re
import secrets
import uuid
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enterprise.exceptions import (
    OAuthConflictException,
    OAuthVerificationException,
)
from app.enterprise.models import Membership, UserCredential
from app.enterprise.schemas import OAuthSessionResponse
from app.enterprise.services.apikey_service import EnterpriseAPIKeyService
from app.enterprise.services.organization_service import OrganizationService
from app.enterprise.services.workspace_service import WorkspaceService

logger = structlog.get_logger()

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
DUMMY_SALT = "0" * 64
DUMMY_HASH = hashlib.pbkdf2_hmac(
    "sha256", b"dummy_password", DUMMY_SALT.encode("utf-8"), 100_000
).hex()


class CredentialsAuthService:
    """Production-grade service handling email and password registration and login."""

    ITERATIONS = 100_000

    @classmethod
    def hash_password(
        cls, password: str, salt: Optional[str] = None
    ) -> tuple[str, str]:
        """Hashes a password with PBKDF2-HMAC-SHA256 and a random 32-byte cryptographic salt."""
        if not salt:
            salt = secrets.token_hex(32)
        pwd_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            cls.ITERATIONS,
        ).hex()
        return pwd_hash, salt

    @classmethod
    def verify_password(cls, password: str, stored_hash: str, salt: str) -> bool:
        """Verifies a password against a stored hash using constant-time comparison."""
        computed_hash, _ = cls.hash_password(password, salt)
        return hmac.compare_digest(computed_hash, stored_hash)

    @classmethod
    def validate_credentials_input(cls, email: str, password: str) -> tuple[str, str]:
        """Validates and normalizes email and password inputs."""
        if not email or not isinstance(email, str):
            raise OAuthVerificationException("Email address is required.")
        normalized_email = email.strip().lower()
        if not EMAIL_REGEX.match(normalized_email):
            raise OAuthVerificationException("Invalid email address format.")

        if not password or not isinstance(password, str):
            raise OAuthVerificationException("Password is required.")
        if len(password) < 8:
            raise OAuthVerificationException(
                "Password must be at least 8 characters long."
            )

        return normalized_email, password

    async def register_user(
        self,
        db: AsyncSession,
        email: str,
        password: str,
        display_name: Optional[str] = None,
    ) -> OAuthSessionResponse:
        """Registers a new user account with credentials, provisions tenant workspace, and issues session key."""
        clean_email, clean_password = self.validate_credentials_input(email, password)

        # Check for duplicate email
        stmt = select(UserCredential).where(UserCredential.email == clean_email)
        res = await db.execute(stmt)
        if res.scalar_one_or_none():
            logger.warning(
                "Duplicate email registration rejected",
                email=clean_email,
            )
            raise OAuthConflictException("An account with this email already exists.")

        # Hash password and create record
        pwd_hash, salt = self.hash_password(clean_password)
        user_id = uuid.uuid4()
        clean_name = display_name.strip() if display_name else clean_email.split("@")[0]

        credential = UserCredential(
            id=uuid.uuid4(),
            user_id=user_id,
            email=clean_email,
            password_hash=pwd_hash,
            salt=salt,
            display_name=clean_name,
            is_active=True,
        )
        db.add(credential)
        await db.flush()

        # Provision personal Organization and default Workspace
        org_service = OrganizationService()
        ws_service = WorkspaceService()
        key_service = EnterpriseAPIKeyService()

        org_name = f"{clean_name}'s Org"
        org = await org_service.create_organization(db, name=org_name, user_id=user_id)
        ws = await ws_service.create_workspace(
            db,
            org_id=org.id,
            name="Default Workspace",
            description="Default workspace provisioned upon registration",
        )

        # Issue active session EnterpriseAPIKey
        raw_key, key_record = await key_service.generate_key(
            db,
            name=f"User Session - {clean_email}",
            org_id=org.id,
            workspace_id=ws.id,
            scopes=["*"],
            expires_in_days=30,
        )
        await db.commit()

        logger.info(
            "User registered successfully with email/password",
            user_id=str(user_id),
            organization_id=str(org.id),
            workspace_id=str(ws.id),
        )

        return OAuthSessionResponse(
            api_key=raw_key,
            user_id=str(user_id),
            email=clean_email,
            display_name=clean_name,
            avatar_url=None,
            organization_id=str(org.id),
            workspace_id=str(ws.id),
            expires_at=key_record.expires_at,
            return_to="/overview",
        )

    async def login_user(
        self,
        db: AsyncSession,
        email: str,
        password: str,
    ) -> OAuthSessionResponse:
        """Authenticates user with email and password and issues active workspace session key."""
        if not email or not password:
            raise OAuthVerificationException("Email and password are required.")

        clean_email = email.strip().lower()

        # Retrieve credential
        stmt = select(UserCredential).where(
            UserCredential.email == clean_email,
            UserCredential.is_active.is_(True),
        )
        res = await db.execute(stmt)
        credential = res.scalar_one_or_none()

        if not credential:
            # Constant-time dummy verification to mitigate user-enumeration timing attacks
            self.verify_password(password, DUMMY_HASH, DUMMY_SALT)
            logger.warning(
                "Authentication failed: account not found",
                email=clean_email,
            )
            raise OAuthVerificationException("Invalid email or password.")

        if not self.verify_password(
            password, credential.password_hash, credential.salt
        ):
            logger.warning(
                "Authentication failed: incorrect password",
                email=clean_email,
            )
            raise OAuthVerificationException("Invalid email or password.")

        # Lookup organization and workspace from active membership
        target_user_id = credential.user_id
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

        org_service = OrganizationService()
        ws_service = WorkspaceService()
        key_service = EnterpriseAPIKeyService()

        target_org_id: uuid.UUID
        target_ws_id: Optional[uuid.UUID] = None

        if membership:
            target_org_id = membership.organization_id
            target_ws_id = membership.workspace_id
            if not target_ws_id:
                workspaces = await ws_service.list_workspaces(db, target_org_id)
                if workspaces:
                    target_ws_id = workspaces[0].id
        else:
            # Provision fallback personal org if missing
            org_name = f"{credential.display_name or clean_email.split('@')[0]}'s Org"
            new_org = await org_service.create_organization(
                db, name=org_name, user_id=target_user_id
            )
            new_ws = await ws_service.create_workspace(
                db, org_id=new_org.id, name="Default Workspace"
            )
            target_org_id = new_org.id
            target_ws_id = new_ws.id

        raw_key, key_record = await key_service.generate_key(
            db,
            name=f"User Session - {clean_email}",
            org_id=target_org_id,
            workspace_id=target_ws_id,
            scopes=["*"],
            expires_in_days=30,
        )
        await db.commit()

        logger.info(
            "User authenticated successfully with email/password",
            user_id=str(target_user_id),
            organization_id=str(target_org_id),
            workspace_id=str(target_ws_id) if target_ws_id else None,
        )

        return OAuthSessionResponse(
            api_key=raw_key,
            user_id=str(target_user_id),
            email=clean_email,
            display_name=credential.display_name,
            avatar_url=None,
            organization_id=str(target_org_id),
            workspace_id=str(target_ws_id) if target_ws_id else None,
            expires_at=key_record.expires_at,
            return_to="/overview",
        )

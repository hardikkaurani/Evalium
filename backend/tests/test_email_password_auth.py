import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enterprise.exceptions import (
    OAuthConflictException,
    OAuthVerificationException,
)
from app.enterprise.models import UserCredential
from app.enterprise.services.credentials_auth_service import CredentialsAuthService
from app.main import app


@pytest.mark.asyncio
async def test_01_credentials_service_hash_and_verify():
    """Verify password hashing produces distinct salts and validates correctly."""
    pwd = "CorrectHorseBatteryStaple99!"
    pwd_hash1, salt1 = CredentialsAuthService.hash_password(pwd)
    pwd_hash2, salt2 = CredentialsAuthService.hash_password(pwd)

    # Distinct salts must generate distinct hashes
    assert salt1 != salt2
    assert pwd_hash1 != pwd_hash2
    assert pwd_hash1 != pwd

    # Verification must pass for correct password and fail for incorrect
    assert CredentialsAuthService.verify_password(pwd, pwd_hash1, salt1) is True
    assert (
        CredentialsAuthService.verify_password("WrongPassword123!", pwd_hash1, salt1)
        is False
    )


@pytest.mark.asyncio
async def test_02_credentials_input_validation():
    """Verify email and password input constraints."""
    # Empty inputs
    with pytest.raises(OAuthVerificationException, match="Email address is required"):
        CredentialsAuthService.validate_credentials_input("", "ValidPassword123!")

    # Malformed email
    with pytest.raises(
        OAuthVerificationException, match="Invalid email address format"
    ):
        CredentialsAuthService.validate_credentials_input(
            "not-an-email", "ValidPassword123!"
        )

    # Short password (< 8 chars)
    with pytest.raises(OAuthVerificationException, match="at least 8 characters long"):
        CredentialsAuthService.validate_credentials_input("user@example.com", "short")

    # Valid inputs normalize email to lowercase
    email, pwd = CredentialsAuthService.validate_credentials_input(
        " USER.Name+test@Example.COM ", "ValidPassword123!"
    )
    assert email == "user.name+test@example.com"
    assert pwd == "ValidPassword123!"


@pytest.mark.asyncio
async def test_03_registration_and_login_service_flow(db_session: AsyncSession):
    """Verify service-level user registration, workspace provisioning, and login."""
    service = CredentialsAuthService()
    unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    password = "SecurePassword2026!"

    # 1. Register
    reg_session = await service.register_user(
        db_session,
        email=unique_email,
        password=password,
        display_name="Test Engineer",
    )
    assert reg_session.api_key.startswith("ef_ent_")
    assert reg_session.email == unique_email
    assert reg_session.display_name == "Test Engineer"
    assert reg_session.organization_id is not None
    assert reg_session.workspace_id is not None

    # Verify database persistence
    stmt = select(UserCredential).where(UserCredential.email == unique_email)
    res = await db_session.execute(stmt)
    cred = res.scalar_one_or_none()
    assert cred is not None
    assert cred.password_hash != password
    assert cred.is_active is True

    # 2. Duplicate registration must raise conflict (409)
    with pytest.raises(OAuthConflictException, match="already exists"):
        await service.register_user(
            db_session, email=unique_email, password="AnotherPassword999!"
        )

    # 3. Successful login
    login_session = await service.login_user(
        db_session, email=unique_email.upper(), password=password
    )
    assert login_session.api_key.startswith("ef_ent_")
    assert login_session.user_id == reg_session.user_id
    assert login_session.organization_id == reg_session.organization_id
    assert login_session.workspace_id == reg_session.workspace_id

    # 4. Incorrect password rejection
    with pytest.raises(OAuthVerificationException, match="Invalid email or password"):
        await service.login_user(
            db_session, email=unique_email, password="WrongPassword999!"
        )

    # 5. Non-existent account rejection
    with pytest.raises(OAuthVerificationException, match="Invalid email or password"):
        await service.login_user(
            db_session,
            email=f"missing_{uuid.uuid4().hex[:8]}@example.com",
            password=password,
        )


@pytest.mark.asyncio
async def test_04_api_endpoints_registration_and_login(db_session: AsyncSession):
    """Verify HTTP API endpoints for /auth/register and /auth/login."""
    from app.core.dependencies import get_db as core_get_db
    from app.database.session import get_db as session_get_db

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[session_get_db] = _override_get_db
    app.dependency_overrides[core_get_db] = _override_get_db

    try:
        unique_email = f"api_user_{uuid.uuid4().hex[:8]}@evalium.dev"
        password = "ProductionPassword9988!"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Auth status includes credentials_enabled
            status_resp = await client.get("/api/v1/auth/status")
            assert status_resp.status_code == 200
            status_data = status_resp.json()
            assert status_data["data"]["credentials_enabled"] is True

            # 2. Register via API
            reg_resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": unique_email,
                    "password": password,
                    "name": "API Tester",
                },
            )
            assert reg_resp.status_code == 201
            reg_payload = reg_resp.json()
            assert reg_payload["success"] is True
            api_key = reg_payload["data"]["api_key"]
            assert api_key.startswith("ef_ent_")

            # 3. Duplicate registration rejected with 409 Conflict
            dup_resp = await client.post(
                "/api/v1/auth/register",
                json={"email": unique_email, "password": password},
            )
            assert dup_resp.status_code == 409

            # 4. Invalid email format rejected with 400 Bad Request
            bad_resp = await client.post(
                "/api/v1/auth/register",
                json={"email": "invalid-email", "password": password},
            )
            assert bad_resp.status_code == 400

            # 5. Login via API
            login_resp = await client.post(
                "/api/v1/auth/login",
                json={"email": unique_email, "password": password},
            )
            assert login_resp.status_code == 200
            login_payload = login_resp.json()
            assert login_payload["success"] is True
            session_key = login_payload["data"]["api_key"]

            # 6. Invalid password rejected with 401 Unauthorized
            bad_pwd_resp = await client.post(
                "/api/v1/auth/login",
                json={"email": unique_email, "password": "WrongPassword!"},
            )
            assert bad_pwd_resp.status_code == 401

            # 7. Access protected endpoint using issued session key
            projects_resp = await client.get(
                "/api/v1/projects",
                headers={"X-API-Key": session_key},
            )
            assert projects_resp.status_code == 200
            assert projects_resp.json()["success"] is True

            # 8. Unauthenticated request to protected endpoint rejected with 401
            unauth_resp = await client.get("/api/v1/projects")
            assert unauth_resp.status_code == 401
    finally:
        app.dependency_overrides.pop(session_get_db, None)
        app.dependency_overrides.pop(core_get_db, None)

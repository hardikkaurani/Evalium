import sys
from unittest.mock import patch

from scripts.check_environment import EnvironmentDoctor, mask_connection_url


def test_mask_connection_url_hides_passwords():
    raw_postgres = (
        "postgresql://postgres:super_secret_pw123@db.prod.internal:5432/evalforge"
    )
    masked = mask_connection_url(raw_postgres)
    assert "super_secret_pw123" not in masked
    assert ":***@" in masked
    assert "db.prod.internal:5432/evalforge" in masked

    raw_redis = "rediss://default:redis_super_secret_token@redis.prod.internal:6379"
    masked_redis = mask_connection_url(raw_redis)
    assert "redis_super_secret_token" not in masked_redis
    assert ":***@" in masked_redis


def test_mask_connection_url_handles_empty_or_no_password():
    assert mask_connection_url(None) == "[NOT CONFIGURED]"
    assert mask_connection_url("") == "[NOT CONFIGURED]"
    assert (
        mask_connection_url("sqlite+aiosqlite:///local.db")
        == "sqlite+aiosqlite:///local.db"
    )


def test_doctor_development_success():
    doctor = EnvironmentDoctor(target_env="development")
    with (
        patch("shutil.which", return_value="/mock/bin"),
        patch("subprocess.run") as mock_sub,
    ):
        mock_sub.return_value.stdout = "v22.0.0\n"
        passed = doctor.run_all()
        assert passed is True
        assert len(doctor.errors) == 0
        report = doctor.format_report()
        assert "ALL AUDIT GATES PASSED" in report


def test_doctor_detects_invalid_python_version():
    doctor = EnvironmentDoctor(target_env="development")
    with patch.object(sys, "version_info", (3, 10, 0)):
        assert doctor.check_python_version() is False
        assert any("Python Runtime" in err for err in doctor.errors)


def test_doctor_detects_missing_module():
    doctor = EnvironmentDoctor(target_env="development")
    with patch(
        "importlib.import_module",
        side_effect=ImportError("No module named non_existent"),
    ):
        assert doctor.check_core_dependencies() is False
        assert any("Core Dependencies" in err for err in doctor.errors)


def test_doctor_production_fail_fast_localhost_db():
    from app.config.config import Settings

    doctor = EnvironmentDoctor(target_env="production")
    # Simulate a production settings instance pointing database to localhost
    mock_settings = Settings(
        APP_ENV="development",  # instantiate in dev to allow setting values
        DATABASE_URL="postgresql+asyncpg://postgres:secure_pw_1234567890@localhost:5432/evalforge",
        REDIS_URL="rediss://default:secure_pw_1234567890@managed-redis:6379",
        SECRET_KEY="a" * 64,
        CORS_ORIGINS=["https://eval-forge-sandy.vercel.app"],
        DEBUG=False,
    )
    doctor.check_configuration_and_security(custom_settings=mock_settings)
    assert any(
        "Localhost/SQLite database disallowed in production" in err
        for err in doctor.errors
    )


def test_doctor_production_fail_fast_localhost_redis():
    from app.config.config import Settings

    doctor = EnvironmentDoctor(target_env="production")
    mock_settings = Settings(
        APP_ENV="development",
        DATABASE_URL="postgresql+asyncpg://postgres:secure_pw_1234567890@managed-db:5432/evalforge",
        REDIS_URL="redis://localhost:6379/0",
        SECRET_KEY="a" * 64,
        CORS_ORIGINS=["https://eval-forge-sandy.vercel.app"],
        DEBUG=False,
    )
    doctor.check_configuration_and_security(custom_settings=mock_settings)
    assert any(
        "Localhost Redis disallowed in production" in err for err in doctor.errors
    )


def test_doctor_production_fail_fast_insecure_secret():
    from app.config.config import Settings

    doctor = EnvironmentDoctor(target_env="production")
    mock_settings = Settings(
        APP_ENV="development",
        DATABASE_URL="postgresql+asyncpg://postgres:secure_pw_1234567890@managed-db:5432/evalforge",
        REDIS_URL="rediss://default:secure_pw_1234567890@managed-redis:6379",
        SECRET_KEY="dev-secret-key-evalforge-placeholder",
        CORS_ORIGINS=["https://eval-forge-sandy.vercel.app"],
        DEBUG=False,
    )
    doctor.check_configuration_and_security(custom_settings=mock_settings)
    assert any("SECRET_KEY in production" in err for err in doctor.errors)


def test_doctor_production_fail_fast_wildcard_cors():
    from app.config.config import Settings

    doctor = EnvironmentDoctor(target_env="production")
    mock_settings = Settings(
        APP_ENV="development",
        DATABASE_URL="postgresql+asyncpg://postgres:secure_pw_1234567890@managed-db:5432/evalforge",
        REDIS_URL="rediss://default:secure_pw_1234567890@managed-redis:6379",
        SECRET_KEY="a" * 64,
        CORS_ORIGINS=["*"],
        DEBUG=False,
    )
    doctor.check_configuration_and_security(custom_settings=mock_settings)
    assert any("Wildcard '*' disallowed" in err for err in doctor.errors)


def test_doctor_alembic_head_detection():
    doctor = EnvironmentDoctor(target_env="development")
    assert doctor.check_alembic_migrations() is True
    assert not any("Alembic Migrations" in err for err in doctor.errors)


def test_doctor_sdk_and_cli_detection():
    doctor = EnvironmentDoctor(target_env="development")
    assert doctor.check_sdk_and_cli_packages() is True
    assert not any("SDK & CLI Modules" in err for err in doctor.errors)

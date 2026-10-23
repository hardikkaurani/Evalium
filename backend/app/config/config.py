import os
from typing import Literal
from urllib.parse import unquote, urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Determine environment to load corresponding .env file
# Order of precedence: environment variables > .env.{APP_ENV} > .env
APP_ENV = os.getenv("APP_ENV", "development").lower()

env_files: list[str] = []
if APP_ENV != "testing":
    if os.path.exists(".env"):
        env_files.append(".env")
    if os.path.exists(f".env.{APP_ENV}"):
        env_files.append(f".env.{APP_ENV}")

INSECURE_CREDENTIALS: frozenset[str] = frozenset(
    {
        "postgres_password",
        "password",
        "p@ssword",
        "p@ssw0rd",
        "p4ssw0rd",
        "changeme",
        "secret",
        "admin",
        "admin123",
        "admin_password",
        "123456",
        "12345678",
        "123456789",
        "evalforge",
        "dev",
        "placeholder",
        "root",
        "test",
        "dev-secret-key-evalforge-placeholder",
    }
)


def _is_insecure_credential(val: str | None) -> bool:
    """Checks whether a credential matches known insecure defaults or common leet-speak patterns."""
    if not val:
        return True
    lowered = val.lower().strip()
    if lowered in INSECURE_CREDENTIALS:
        return True
    normalized = (
        lowered.replace("@", "a")
        .replace("0", "o")
        .replace("$", "s")
        .replace("3", "e")
        .replace("1", "i")
        .replace("!", "i")
    )
    if normalized in INSECURE_CREDENTIALS:
        return True
    return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=tuple(env_files) if env_files else None,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Core Application Settings
    APP_NAME: str = "Evalium API"
    APP_ENV: Literal["development", "testing", "production"] = "development"
    DEBUG: bool = True
    PORT: int = Field(8000, ge=1, le=65535)
    API_V1_STR: str = "/api/v1"

    # Database Configuration
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = Field(5432, ge=1, le=65535)
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: SecretStr = SecretStr("postgres_password")
    POSTGRES_DB: str = "evalforge"
    DATABASE_URL: str | None = None

    # Redis Configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = Field(6379, ge=1, le=65535)
    REDIS_DB: int = Field(0, ge=0)
    REDIS_URL: str | None = None

    # Logging Configuration
    LOG_LEVEL: Literal["debug", "info", "warning", "error", "critical"] = "info"
    JSON_LOGS: bool = False

    # Security Configuration
    SECRET_KEY: SecretStr = SecretStr("dev-secret-key-evalforge-placeholder")
    CORS_ORIGINS: list[str] = ["*"]
    ALLOWED_HOSTS: list[str] = ["*"]
    TRUST_PROXY_HEADERS: bool = True
    TRUSTED_PROXIES: list[str] = Field(
        default_factory=lambda: [
            "127.0.0.1",
            "::1",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
        ]
    )

    # LLM Provider API Keys
    OPENAI_API_KEY: SecretStr | None = None
    GEMINI_API_KEY: SecretStr | None = None
    ANTHROPIC_API_KEY: SecretStr | None = None
    OPENROUTER_API_KEY: SecretStr | None = None
    DEEPSEEK_API_KEY: SecretStr | None = None
    COHERE_API_KEY: SecretStr | None = None
    NVIDIA_API_KEY: SecretStr | None = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Stripe SaaS Billing Configuration
    STRIPE_SECRET_KEY: SecretStr | None = None
    STRIPE_PUBLISHABLE_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: SecretStr | None = None

    # Google OAuth 2.0 Configuration
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: SecretStr | None = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"
    FRONTEND_URL: str = "http://localhost:5173"

    # Evaluation Engine Defaults
    DEFAULT_EVALUATION_PROVIDER: str = "openai"
    DEFAULT_EVALUATION_JUDGE: str = "rubric"
    DEFAULT_EVALUATION_PROMPT_VERSION: str = "v1"
    EVALUATION_RETRY_COUNT: int = Field(2, ge=0, le=10)
    EVALUATION_TIMEOUT_SECONDS: float = Field(30.0, gt=0.0, le=300.0)
    EVALUATION_MAX_BATCH_SIZE: int = Field(500, ge=1, le=5000)
    EVALUATION_SCORE_THRESHOLD: float = Field(0.7, ge=0.0, le=1.0)
    EVALUATION_MODEL_NAME: str = "gpt-4o-mini"

    @field_validator("APP_ENV", mode="before")
    @classmethod
    def validate_app_env(cls, v: str) -> str:
        if isinstance(v, str):
            return v.lower()
        return v

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        env = (self.APP_ENV or "development").lower()
        if env == "production":
            # 1. DEBUG must be False in production
            if self.DEBUG:
                raise ValueError("DEBUG must be False in production environment")

            # 2. SECRET_KEY must be set to a secure value
            secret_val = self.SECRET_KEY.get_secret_value()
            if (
                not secret_val
                or _is_insecure_credential(secret_val)
                or secret_val
                == "dev-secret-key-evalforge-placeholder"  # nosec B105
                or len(secret_val) < 16
            ):
                raise ValueError(
                    "SECRET_KEY must be set to a secure value in production environment. "
                    "The default value is insecure."
                )

            # 3. CORS_ORIGINS must not be wildcard in production
            if "*" in self.CORS_ORIGINS:
                raise ValueError(
                    "CORS_ORIGINS must be set to a specific list of origins in production. "
                    "Allowing all origins is insecure."
                )

            # 4. Database configuration validation
            if self.DATABASE_URL and not self.DATABASE_URL.startswith("sqlite"):
                # If DATABASE_URL contains template variables, validate discrete credentials
                if "${" in self.DATABASE_URL:
                    pg_pass = self.POSTGRES_PASSWORD.get_secret_value()
                    if _is_insecure_credential(pg_pass):
                        raise ValueError(
                            "POSTGRES_PASSWORD must be set to a secure value in production environment. "
                            "The default value is insecure."
                        )
                else:
                    parsed = urlparse(self.DATABASE_URL)
                    if parsed.password:
                        raw_pass = unquote(parsed.password)
                        if _is_insecure_credential(raw_pass):
                            raise ValueError(
                                "DATABASE_URL must be set to a secure value in production environment. "
                                "The database password provided is insecure."
                            )
                    elif parsed.scheme in (
                        "postgresql",
                        "postgres",
                        "postgresql+asyncpg",
                        "postgresql+psycopg2",
                    ):
                        raise ValueError(
                            "DATABASE_URL must include a secure password in production environment."
                        )
            else:
                # DATABASE_URL is not provided or is sqlite test DB, validate discrete host and password
                pg_pass = self.POSTGRES_PASSWORD.get_secret_value()
                if _is_insecure_credential(pg_pass):
                    raise ValueError(
                        "POSTGRES_PASSWORD must be set to a secure value in production environment. "
                        "The default value is insecure."
                    )

            # 6. Google OAuth configuration validation
            if self.GOOGLE_CLIENT_ID:
                if not self.GOOGLE_CLIENT_SECRET or _is_insecure_credential(
                    self.GOOGLE_CLIENT_SECRET.get_secret_value()
                ):
                    raise ValueError(
                        "GOOGLE_CLIENT_SECRET must be configured securely when GOOGLE_CLIENT_ID is enabled in production."
                    )
                if (
                    not self.GOOGLE_REDIRECT_URI.startswith("https://")
                    and "localhost" not in self.GOOGLE_REDIRECT_URI
                    and "127.0.0.1" not in self.GOOGLE_REDIRECT_URI
                ):
                    raise ValueError(
                        "GOOGLE_REDIRECT_URI must use HTTPS in production environment."
                    )

            # 7. Stripe Billing configuration validation
            if self.STRIPE_SECRET_KEY:
                stripe_val = self.STRIPE_SECRET_KEY.get_secret_value()
                if _is_insecure_credential(stripe_val) or not stripe_val.startswith(
                    "sk_"
                ):
                    raise ValueError(
                        "STRIPE_SECRET_KEY must be a valid secret key (sk_...) when Stripe billing is enabled."
                    )

        return self

    @property
    def get_database_url(self) -> str:
        """Constructs or retrieves the database connection string.

        Supports dynamic replacement of environment variables in DATABASE_URL if
        they are in the format ${VAR}. Converts postgres:// and postgresql:// to
        postgresql+asyncpg:// for SQLAlchemy async engine compatibility.
        """
        if self.DATABASE_URL:
            db_url = self.DATABASE_URL
            if "${" in db_url:
                db_url = db_url.replace("${POSTGRES_USER}", self.POSTGRES_USER)
                db_url = db_url.replace(
                    "${POSTGRES_PASSWORD}", self.POSTGRES_PASSWORD.get_secret_value()
                )
                db_url = db_url.replace("${POSTGRES_SERVER}", self.POSTGRES_SERVER)
                db_url = db_url.replace("${POSTGRES_PORT}", str(self.POSTGRES_PORT))
                db_url = db_url.replace("${POSTGRES_DB}", self.POSTGRES_DB)

            if db_url.startswith("postgres://"):
                db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif db_url.startswith("postgresql://") and not db_url.startswith(
                "postgresql+asyncpg://"
            ):
                db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

            return db_url

        password = self.POSTGRES_PASSWORD.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{password}@"
            f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def get_redis_url(self) -> str:
        """Constructs or retrieves the Redis connection string."""
        if self.REDIS_URL:
            redis_url = self.REDIS_URL
            if "${" in redis_url:
                redis_url = redis_url.replace("${REDIS_HOST}", self.REDIS_HOST)
                redis_url = redis_url.replace("${REDIS_PORT}", str(self.REDIS_PORT))
                redis_url = redis_url.replace("${REDIS_DB}", str(self.REDIS_DB))
            return redis_url
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


# Initialize the settings instance
settings = Settings()

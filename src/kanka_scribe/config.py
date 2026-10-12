from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "kanka-scribe"
    secret_key: str = "change-me-in-production"
    database_url: str = "sqlite+pysqlite:////tmp/kanka-scribe.db"
    # JWT
    jwt_expire_minutes: int = 60 * 24 * 7
    # Optional OIDC (disabled when issuer empty)
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "http://localhost:8000/api/v1/auth/oidc/callback"
    # Fernet key for encrypting workspace secrets (urlsafe 32-byte base64)
    secrets_fernet_key: str = ""
    # Craig handoff watch directory (optional)
    handoff_dir: str = ""
    # Bootstrap first admin on empty DB
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "changeme"


@lru_cache
def get_settings() -> Settings:
    return Settings()

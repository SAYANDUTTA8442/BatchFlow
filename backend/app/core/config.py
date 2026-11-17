from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_LOCAL_JWT_SECRET = "local-development-secret-change-before-deployment-2026"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="BatchFlow API", alias="APP_NAME")
    app_environment: Literal["local", "test", "staging", "production"] = Field(
        default="local", alias="APP_ENVIRONMENT"
    )
    database_url: str = Field(
        default="postgresql+psycopg://batchflow:change-me-local-only@localhost:5432/batchflow",
        alias="DATABASE_URL",
    )
    sqlalchemy_echo: bool = Field(default=False, alias="SQLALCHEMY_ECHO")
    jwt_secret_key: str = Field(default=_LOCAL_JWT_SECRET, alias="JWT_SECRET_KEY")
    jwt_key_id: str = Field(default="local-v1", alias="JWT_KEY_ID")
    jwt_previous_keys: str = Field(default="", alias="JWT_PREVIOUS_KEYS")
    jwt_issuer: str = Field(default="batchflow-api", alias="JWT_ISSUER")
    jwt_audience: str = Field(default="batchflow-client", alias="JWT_AUDIENCE")
    allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="ALLOWED_ORIGINS",
    )
    refresh_cookie_secure: bool = Field(default=False, alias="REFRESH_COOKIE_SECURE")

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if len(self.jwt_secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 characters")
        if not self.jwt_key_id.strip():
            raise ValueError("JWT_KEY_ID must not be empty")
        if self.app_environment == "production":
            if self.jwt_secret_key == _LOCAL_JWT_SECRET:
                raise ValueError("Production requires a unique JWT_SECRET_KEY")
            if not self.refresh_cookie_secure:
                raise ValueError("Production requires REFRESH_COOKIE_SECURE=true")
        return self

    @property
    def origin_allowlist(self) -> set[str]:
        return {
            origin.strip().rstrip("/")
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()

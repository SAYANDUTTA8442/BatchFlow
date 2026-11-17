from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Email Cleaner & Prioritizer"
    environment: str = "local"
    database_url: str = "sqlite:///./email_cleaner.db"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/v1/gmail/oauth/callback"
    gmail_sync_max_results: int = Field(default=25, ge=1, le=100)
    allow_insecure_oauth_transport: bool = True
    app_secret_key: str = "change-me-before-deploy"
    cors_origins: list[str] = ["*"]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

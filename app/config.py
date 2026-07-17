from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / .env file."""

    ai_provider: str = "openai"  # "openai" or "gemini"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "nexus_chat"

    clerk_jwks_url: str = ""
    clerk_issuer: str = ""

    credit_limit: int = 100
    credit_reset_hours: int = 1

    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

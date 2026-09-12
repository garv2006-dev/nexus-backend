from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings for Production-Ready Multi-User RAG Workspace System."""

    # Supabase PostgreSQL
    supabase_url: str = ""
    supabase_secret_key: str = ""
    database_url: str = ""

    # Gemini LLM & Embedding Settings
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    
    embedding_provider: str = "gemini"
    embedding_model: str = "models/text-embedding-004"
    embedding_dimension: int = 768

    # Workspace & Rate Limiting Defaults
    daily_token_limit: int = 50000
    default_max_pages: int = 50
    max_workspace_members: int = 5
    max_file_size_mb: int = 15

    # Clerk Authentication
    clerk_jwks_url: str = ""
    clerk_issuer: str = ""

    # CORS
    cors_origins: str = "*"

    # Resend & Email Settings
    resend_api_key: str = ""
    email_from: str = "Nexus AI <onboarding@resend.dev>"
    app_frontend_url: str = "http://localhost:5173"

    # Direct SMTP Settings (Gmail / Brevo - No Domain Needed)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    brevo_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

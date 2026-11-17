"""Application settings, loaded from environment variables or backend/.env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AGRISENSE_")

    app_name: str = "AgriSense"
    environment: str = "development"
    # SQLite for development; switch to PostgreSQL later by changing only this URL.
    database_url: str = "sqlite:///./agrisense.db"
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()

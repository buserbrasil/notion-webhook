from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = Field(default="Notion Webhook")
    DEBUG: bool = Field(default=False)

    NOTION_API_KEY: Optional[str] = None
    NOTION_VERIFICATION_TOKEN: Optional[str] = None
    NOTION_API_VERSION: str = Field(default="2025-09-03")

    WEBHOOK_URL: Optional[str] = None

    DB_HOST: str = Field(default="localhost")
    DB_PORT: int = Field(default=5432)
    DB_USER: str = Field(default="postgres")
    DB_PASSWORD: Optional[str] = None
    DB_NAME: str = Field(default="notion_webhook")
    DB_POOL_SIZE: int = Field(default=5)

    @property
    def has_database_credentials(self) -> bool:
        """Return True when enough database settings are provided."""
        return all(
            [
                self.DB_HOST,
                self.DB_USER,
                self.DB_NAME,
            ]
        )


settings = Settings()

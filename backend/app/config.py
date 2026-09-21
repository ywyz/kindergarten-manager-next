import os
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            None
            if os.environ.get("APP_DISABLE_DOTENV") == "1"
            else Path(__file__).resolve().parents[1] / ".env"
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Kindergarten Manager API"
    database_url: SecretStr = SecretStr("")
    cookie_secure: bool = Field(default=True)
    allowed_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173")
    session_ttl_seconds: int = Field(default=43200)  # 12 hours
    rate_limit_window_seconds: int = Field(default=60)
    rate_limit_max_requests: int = Field(default=10)
    rate_limit_max_failures: int = Field(default=20)
    rate_limit_max_keys: int = Field(default=10000)
    environment: str = Field(default="production")

    @field_validator(
        "rate_limit_window_seconds",
        "rate_limit_max_requests",
        "rate_limit_max_failures",
        "rate_limit_max_keys",
    )
    @classmethod
    def _positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be positive")
        return v

    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()

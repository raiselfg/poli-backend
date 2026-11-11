from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "production"]
    pg_user: str
    pg_password: SecretStr
    pg_db: str
    pg_port: int
    pg_host: str
    allowed_origins: list[str]
    allow_insecure_cookies: bool
    session_ttl_seconds: int

    @model_validator(mode="after")
    def validate_security(self):
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
            ):
                raise ValueError("ALLOWED_ORIGINS must contain exact HTTP(S) origins")
            # Accessing port also validates its syntax.
            _ = parsed.port
            if self.app_env == "production" and parsed.scheme != "https":
                raise ValueError("Production origins must use HTTPS")
        if self.app_env == "production":
            if self.allow_insecure_cookies:
                raise ValueError("Insecure cookies are forbidden in production")
            if not self.allowed_origins:
                raise ValueError("Production requires explicit ALLOWED_ORIGINS")
        if self.session_ttl_seconds <= 0:
            raise ValueError("Session TTL must be positive")
        return self

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.pg_user,
            password=self.pg_password.get_secret_value(),
            host=self.pg_host,
            port=self.pg_port,
            database=self.pg_db,
        )

    @property
    def cookie_name(self) -> str:
        return "session" if self.allow_insecure_cookies else "__Host-session"


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Application configuration, loaded from the environment only."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

DEV_SECRET = "dev-only-insecure-secret-change-me"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    app_name: str = "Nabz"
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", DEV_SECRET))
    access_token_minutes: int = field(default_factory=lambda: _env_int("ACCESS_TOKEN_MINUTES", 720))
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./nabz.db")
    )
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:8000").split(",")
            if origin.strip()
        )
    )
    rate_limit_per_minute: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 120)
    )
    login_rate_limit_per_minute: int = field(
        default_factory=lambda: _env_int("LOGIN_RATE_LIMIT_PER_MINUTE", 10)
    )
    seed_on_startup: bool = field(default_factory=lambda: _env_bool("SEED_ON_STARTUP", True))
    bcrypt_rounds: int = field(default_factory=lambda: _env_int("BCRYPT_ROUNDS", 12))

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    def validate(self) -> None:
        if self.is_production and (self.secret_key == DEV_SECRET or len(self.secret_key) < 32):
            raise RuntimeError(
                "SECRET_KEY must be a random value of at least 32 characters "
                "when ENVIRONMENT=production."
            )
        if self.access_token_minutes <= 0:
            raise RuntimeError("ACCESS_TOKEN_MINUTES must be positive.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.validate()
    return settings

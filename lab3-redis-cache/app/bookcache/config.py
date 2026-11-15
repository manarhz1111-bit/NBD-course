from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    pg_dsn: str = _env("PG_DSN", "postgresql://lab3_app:app@127.0.0.1:5432/library")
    pg_pool_min: int = int(_env("PG_POOL_MIN", "2"))
    pg_pool_max: int = int(_env("PG_POOL_MAX", "10"))

    pg_pool_timeout_s: float = float(_env("PG_POOL_TIMEOUT_S", "3"))
    pg_pool_max_waiting: int = int(_env("PG_POOL_MAX_WAITING", "200"))

    redis_host: str = _env("REDIS_HOST", "127.0.0.1")
    redis_port: int = int(_env("REDIS_PORT", "6379"))
    redis_user: str = _env("REDIS_USER", "app")
    redis_password: str = _env("REDIS_PASSWORD", "")

    redis_timeout_s: float = float(_env("REDIS_TIMEOUT_S", "0.5"))
    redis_max_connections: int = int(_env("REDIS_MAX_CONNECTIONS", "128"))

    redis_pool_timeout_s: float = float(_env("REDIS_POOL_TIMEOUT_S", "1.0"))

    cache_enabled: bool = _env("CACHE_ENABLED", "true").lower() == "true"

    book_ttl_s: int = int(_env("BOOK_TTL_S", "3600"))
    top_ttl_s: int = int(_env("TOP_TTL_S", "60"))
    genres_ttl_s: int = int(_env("GENRES_TTL_S", "3600"))
    negative_ttl_s: int = int(_env("NEGATIVE_TTL_S", "30"))
    ttl_jitter: float = float(_env("TTL_JITTER", "0.1"))

    lock_ttl_ms: int = int(_env("LOCK_TTL_MS", "3000"))
    lock_wait_step_s: float = float(_env("LOCK_WAIT_STEP_S", "0.02"))

    refresh_ahead_ratio: float = float(_env("REFRESH_AHEAD_RATIO", "0.2"))

    breaker_threshold: int = int(_env("BREAKER_THRESHOLD", "5"))
    breaker_cooldown_s: float = float(_env("BREAKER_COOLDOWN_S", "5"))

    key_version: str = _env("CACHE_KEY_VERSION", "v1")


settings = Settings()

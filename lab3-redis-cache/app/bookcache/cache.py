from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
import random
import time
import uuid
from typing import Any, Awaitable, Callable

from redis.asyncio import Redis
from redis.exceptions import RedisError

from .config import Settings
from .metrics import CACHE_BREAKER_OPEN, CACHE_ERRORS, CACHE_INVALIDATIONS, CACHE_REFRESH_AHEAD, CACHE_REQUESTS

log = logging.getLogger("bookcache.cache")

NEGATIVE = "__none__"


RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


RENEW_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2])
    return 1
end
return 0
"""

STORE_IF_OWNER_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
    return 1
end
return 0
"""

INVALIDATE_LUA = """
local deleted = 0
for i = 1, #KEYS, 2 do
    deleted = deleted + redis.call('DEL', KEYS[i])
    redis.call('DEL', KEYS[i + 1])
end
return deleted
"""


class Cache:
    def __init__(self, redis: Redis, settings: Settings):
        self.r = redis
        self.s = settings
        # Old namespaces expire by TTL; each API process starts fresh.
        self.namespace = f"{settings.key_version}:{uuid.uuid4().hex}"
        self._renew_script = redis.register_script(RENEW_LOCK_LUA)
        self._release_lock = redis.register_script(RELEASE_LOCK_LUA)
        self._store_if_owner = redis.register_script(STORE_IF_OWNER_LUA)
        self._invalidate_keys = redis.register_script(INVALIDATE_LUA)
        self._breaker_until = 0.0
        self._consecutive_failures = 0
        self._background: set[asyncio.Task] = set()

    def book_key(self, book_id: int) -> str:
        return f"book:{self.namespace}:{book_id}"

    def top_key(self, genre: str) -> str:
        return f"top:{self.namespace}:{genre.lower()}"

    def genres_key(self) -> str:
        return f"genres:{self.namespace}"

    def _breaker_open(self) -> bool:
        is_open = time.monotonic() < self._breaker_until
        CACHE_BREAKER_OPEN.set(1 if is_open else 0)
        return is_open

    def _redis_failed(self, op: str, exc: Exception) -> None:
        CACHE_ERRORS.labels(op).inc()
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.s.breaker_threshold:
            self._breaker_until = time.monotonic() + self.s.breaker_cooldown_s
            self._consecutive_failures = 0
            CACHE_BREAKER_OPEN.set(1)
            log.warning(
                "redis %s failed (%s), %d errors in a row: breaker open, serving from PostgreSQL for %.0fs",
                op,
                exc.__class__.__name__,
                self.s.breaker_threshold,
                self.s.breaker_cooldown_s,
            )

    def _redis_ok(self) -> None:
        self._consecutive_failures = 0

    def _ttl(self, base: int) -> int:
        j = self.s.ttl_jitter
        return max(1, int(base * random.uniform(1 - j, 1 + j)))

    async def get_or_load(
        self,
        entity: str,
        key: str,
        ttl: int,
        loader: Callable[[], Awaitable[Any]],
        use_cache: bool = True,
        refresh_ahead: bool = False,
    ) -> tuple[Any, str]:
        if not (use_cache and self.s.cache_enabled):
            return await self._done(entity, "bypass", await loader())
        if self._breaker_open():
            return await self._done(entity, "breaker_open", await loader())

        try:
            if refresh_ahead:
                raw, pttl = await self.r.pipeline(transaction=False).get(key).pttl(key).execute()
            else:
                raw, pttl = await self.r.get(key), None
            self._redis_ok()
        except RedisError as exc:
            self._redis_failed("get", exc)
            return await self._done(entity, "error", await loader())

        if raw is not None:
            if pttl is not None and 0 < pttl < ttl * 1000 * self.s.refresh_ahead_ratio:
                await self._maybe_refresh(entity, key, ttl, loader)
            return await self._done(entity, "negative_hit" if raw == NEGATIVE else "hit", self._decode(raw))

        token = uuid.uuid4().hex
        lock_key = f"lock:{key}"
        try:
            got_lock = await self.r.set(lock_key, token, nx=True, px=self.s.lock_ttl_ms)
        except RedisError as exc:
            self._redis_failed("lock", exc)
            return await self._done(entity, "error", await loader())

        if got_lock:
            renewal = asyncio.create_task(self._renew_lock(lock_key, token))
            try:
                try:
                    raw = await self.r.get(key)
                except RedisError as exc:
                    self._redis_failed("get", exc)
                    raw = None
                if raw is not None:
                    return await self._done(entity, "wait_hit", self._decode(raw))
                value = await loader()
                await self._store(key, value, ttl, token)
                return await self._done(entity, "miss", value)
            finally:
                renewal.cancel()
                with suppress(asyncio.CancelledError):
                    await renewal
                try:
                    await self._release_lock(keys=[lock_key], args=[token])
                except RedisError as exc:
                    self._redis_failed("unlock", exc)

        deadline = time.monotonic() + self.s.lock_ttl_ms / 1000
        while time.monotonic() < deadline:
            await asyncio.sleep(self.s.lock_wait_step_s)
            try:
                raw, lock_held = await self.r.pipeline(transaction=False).get(key).exists(lock_key).execute()
            except RedisError as exc:
                self._redis_failed("get", exc)
                break
            if raw is not None:
                return await self._done(entity, "wait_hit", self._decode(raw))
            if not lock_held:
                break
        return await self._done(entity, "wait_timeout", await loader())

    async def _maybe_refresh(self, entity: str, key: str, ttl: int, loader) -> None:
        token = uuid.uuid4().hex
        lock_key = f"lock:{key}"
        try:
            if not await self.r.set(lock_key, token, nx=True, px=self.s.lock_ttl_ms):
                return
        except RedisError as exc:
            self._redis_failed("lock", exc)
            return
        CACHE_REFRESH_AHEAD.labels(entity).inc()

        async def refresh() -> None:
            renewal = asyncio.create_task(self._renew_lock(lock_key, token))
            try:
                await self._store(key, await loader(), ttl, token)
            except Exception:
                log.exception("refresh-ahead of %s failed", key)
            finally:
                renewal.cancel()
                with suppress(asyncio.CancelledError):
                    await renewal
                try:
                    await self._release_lock(keys=[lock_key], args=[token])
                except RedisError as exc:
                    self._redis_failed("unlock", exc)

        task = asyncio.create_task(refresh())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _renew_lock(self, lock_key: str, token: str) -> None:
        while True:
            await asyncio.sleep(self.s.lock_ttl_ms / 3000)
            try:
                renewed = await self._renew_script(keys=[lock_key], args=[token, self.s.lock_ttl_ms])
            except RedisError as exc:
                self._redis_failed("renew", exc)
                return
            if not renewed:
                return

    async def _store(self, key: str, value: Any, ttl: int, token: str) -> None:
        payload = NEGATIVE if value is None else json.dumps(value, default=str, separators=(",", ":"))
        expiry = self.s.negative_ttl_s if value is None else self._ttl(ttl)
        try:
            await self._store_if_owner(
                keys=[f"lock:{key}", key],
                args=[token, payload, expiry],
            )
        except RedisError as exc:
            self._redis_failed("set", exc)

    @staticmethod
    def _decode(raw: str) -> Any:
        return None if raw == NEGATIVE else json.loads(raw)

    @staticmethod
    async def _done(entity: str, result: str, value: Any) -> tuple[Any, str]:
        CACHE_REQUESTS.labels(entity, result).inc()
        return value, result

    async def invalidate(self, entity: str, *keys: str) -> None:
        if not self.s.cache_enabled:
            return
        try:
            pairs = [item for key in keys for item in (key, f"lock:{key}")]
            deleted = await self._invalidate_keys(keys=pairs, args=[])
            CACHE_INVALIDATIONS.labels(entity).inc(deleted)
        except RedisError as exc:
            # Stop using possibly stale keys after failed invalidation.
            self.namespace = f"{self.s.key_version}:{uuid.uuid4().hex}"
            log.warning("cache namespace rotated after failed invalidation")
            self._redis_failed("del", exc)

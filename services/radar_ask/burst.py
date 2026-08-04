"""Atomic Redis burst limits with a stricter process-local fallback."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable

from redis import Redis
from redis.exceptions import RedisError

from .config import TIER_BURST_LIMITS, VALID_TIERS


BURST_TTL_SECONDS = 120
BURST_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
if current > tonumber(ARGV[1]) then
  return {0, current}
end
return {1, current}
"""


class BurstExceeded(RuntimeError):
    def __init__(
        self,
        *,
        tier: str,
        limit: int,
        used: int,
        retry_after_seconds: int,
        fallback_active: bool,
    ):
        self.tier = tier
        self.limit = limit
        self.used = used
        self.retry_after_seconds = retry_after_seconds
        self.fallback_active = fallback_active
        super().__init__("Radar Ask per-minute limit reached")


@dataclass(frozen=True)
class BurstAllowance:
    tier: str
    limit: int
    used: int
    retry_after_seconds: int
    fallback_active: bool


class BurstLimiter:
    def __init__(
        self,
        *,
        redis_client,
        clock: Callable[[], float] = time.time,
        local_max_keys: int = 10_000,
    ):
        if not 1 <= int(local_max_keys) <= 100_000:
            raise ValueError("local_max_keys must be between 1 and 100000")
        self.redis = redis_client
        self.clock = clock
        self.local_max_keys = int(local_max_keys)
        self._local_counts: dict[tuple[int, int], int] = {}
        self._local_lock = threading.Lock()

    @staticmethod
    def _validate(user_id: int, tier: str) -> int:
        if user_id <= 0 or tier not in VALID_TIERS:
            raise ValueError("an authenticated Radar Ask tier is required")
        return TIER_BURST_LIMITS[tier]  # type: ignore[index]

    @staticmethod
    def _retry_after(now: float) -> int:
        return max(1, 60 - (int(now) % 60))

    def _local_check(
        self,
        *,
        user_id: int,
        tier: str,
        minute_epoch: int,
        now: float,
        normal_limit: int,
    ) -> BurstAllowance:
        fallback_limit = max(1, normal_limit // 2)
        key = (user_id, minute_epoch)
        with self._local_lock:
            stale_before = minute_epoch - 1
            for existing in list(self._local_counts):
                if existing[1] < stale_before:
                    self._local_counts.pop(existing, None)
            if key not in self._local_counts and len(self._local_counts) >= self.local_max_keys:
                raise BurstExceeded(
                    tier=tier,
                    limit=fallback_limit,
                    used=fallback_limit + 1,
                    retry_after_seconds=self._retry_after(now),
                    fallback_active=True,
                )
            used = self._local_counts.get(key, 0) + 1
            self._local_counts[key] = used
        retry_after = self._retry_after(now)
        if used > fallback_limit:
            raise BurstExceeded(
                tier=tier,
                limit=fallback_limit,
                used=used,
                retry_after_seconds=retry_after,
                fallback_active=True,
            )
        return BurstAllowance(
            tier=tier,
            limit=fallback_limit,
            used=used,
            retry_after_seconds=retry_after,
            fallback_active=True,
        )

    def check(self, *, user_id: int, tier: str) -> BurstAllowance:
        normal_limit = self._validate(user_id, tier)
        now = float(self.clock())
        minute_epoch = int(now // 60)
        key = f"radar-ask:burst:{user_id}:{minute_epoch}"
        try:
            result = self.redis.eval(
                BURST_LUA,
                1,
                key,
                normal_limit,
                BURST_TTL_SECONDS,
            )
            if not isinstance(result, (list, tuple)) or len(result) != 2:
                raise RedisError("invalid Redis burst response")
            allowed, used = int(result[0]), int(result[1])
        except (RedisError, OSError, TimeoutError, TypeError, ValueError):
            return self._local_check(
                user_id=user_id,
                tier=tier,
                minute_epoch=minute_epoch,
                now=now,
                normal_limit=normal_limit,
            )

        retry_after = self._retry_after(now)
        if allowed != 1:
            raise BurstExceeded(
                tier=tier,
                limit=normal_limit,
                used=used,
                retry_after_seconds=retry_after,
                fallback_active=False,
            )
        return BurstAllowance(
            tier=tier,
            limit=normal_limit,
            used=used,
            retry_after_seconds=retry_after,
            fallback_active=False,
        )


_default_limiter: BurstLimiter | None = None
_default_lock = threading.Lock()


def get_burst_limiter() -> BurstLimiter:
    global _default_limiter
    if _default_limiter is not None:
        return _default_limiter
    with _default_lock:
        if _default_limiter is None:
            redis_client = Redis.from_url(
                os.getenv("RADAR_REDIS_URL", "redis://127.0.0.1:6379/0"),
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
                decode_responses=False,
            )
            _default_limiter = BurstLimiter(redis_client=redis_client)
    return _default_limiter


def check_burst(*, user_id: int, tier: str) -> BurstAllowance:
    return get_burst_limiter().check(user_id=user_id, tier=tier)

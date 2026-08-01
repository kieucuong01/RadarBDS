"""Shared fresh/stale response caching with bounded database fallback work."""
from __future__ import annotations

import json
import logging
import os
import random
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from redis import Redis
from redis.exceptions import RedisError

from db.connection import get_conn
from db.public_dataset_versions import ALLOWED_DATASETS, get_dataset_versions
from services.public_cache_keys import build_public_cache_key


logger = logging.getLogger(__name__)

_RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _env_float(
    name: str, default: float, minimum: float, maximum: float
) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


@dataclass(frozen=True)
class CacheResult:
    payload: dict
    status: str
    load_ms: float


class PublicCacheBusy(RuntimeError):
    """Raised when cache coordination cannot safely admit more DB work."""

    def __init__(self, retry_after: int = 1):
        self.retry_after = int(retry_after)
        super().__init__("Public response cache is temporarily busy")


_LOCAL_CACHE_MAX_ITEMS = 256
_LOCAL_CACHE: OrderedDict[str, dict] = OrderedDict()
_LOCAL_CACHE_LOCK = threading.RLock()
_DB_LOAD_SLOTS = threading.BoundedSemaphore(
    _env_int("RADAR_PUBLIC_DB_SLOTS", 2, 1, 8)
)

_REDIS_CLIENT: Redis | None = None
_REDIS_CLIENT_LOCK = threading.Lock()
_VERSION_CACHE: dict[str, tuple[int, float]] = {}
_VERSION_CACHE_LOCK = threading.RLock()
_VERSION_CACHE_SECONDS = 5.0


def _local_get(key: str, *, clock: Callable[[], float], max_age: float):
    with _LOCAL_CACHE_LOCK:
        record = _LOCAL_CACHE.get(key)
        if record is None:
            return None
        try:
            age = max(0.0, float(clock()) - float(record["stored_at"]))
        except (KeyError, TypeError, ValueError):
            _LOCAL_CACHE.pop(key, None)
            return None
        if age > max_age:
            _LOCAL_CACHE.pop(key, None)
            return None
        _LOCAL_CACHE.move_to_end(key)
        return record


def _local_put(key: str, record: dict) -> None:
    with _LOCAL_CACHE_LOCK:
        _LOCAL_CACHE[key] = record
        _LOCAL_CACHE.move_to_end(key)
        while len(_LOCAL_CACHE) > _LOCAL_CACHE_MAX_ITEMS:
            _LOCAL_CACHE.popitem(last=False)


def _clear_local_cache_for_test() -> None:
    """Reset process mirrors without touching Redis; intended for isolated tests."""
    with _LOCAL_CACHE_LOCK:
        _LOCAL_CACHE.clear()
    with _VERSION_CACHE_LOCK:
        _VERSION_CACHE.clear()


def clear_local_public_cache() -> None:
    """Drop only disposable process-local response/version mirrors."""
    _clear_local_cache_for_test()


class PublicResponseCache:
    def __init__(
        self,
        *,
        redis_client,
        clock: Callable[[], float] = time.time,
    ):
        self.redis = redis_client
        self.clock = clock
        self.fresh_seconds = _env_float(
            "RADAR_PUBLIC_CACHE_FRESH_SECONDS", 60.0, 1.0, 3600.0
        )
        self.stale_seconds = _env_float(
            "RADAR_PUBLIC_CACHE_STALE_SECONDS", 180.0, 0.0, 86400.0
        )
        self.lock_seconds = _env_float(
            "RADAR_PUBLIC_CACHE_LOCK_SECONDS", 5.0, 0.1, 60.0
        )
        self.wait_seconds = _env_float(
            "RADAR_PUBLIC_CACHE_WAIT_SECONDS", 0.25, 0.01, 5.0
        )

    def _read_json(self, key: str, *, max_age: float):
        try:
            raw = self.redis.get(key)
        except RedisError:
            logger.warning("Redis cache read failed", exc_info=True)
            return _local_get(key, clock=self.clock, max_age=max_age)

        if raw is None:
            return _local_get(key, clock=self.clock, max_age=max_age)
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            record = json.loads(raw)
            if not isinstance(record, dict) or not isinstance(
                record.get("payload"), dict
            ):
                raise ValueError("invalid cache record")
            stored_at = float(record["stored_at"])
            age = max(0.0, float(self.clock()) - stored_at)
            if age > max_age:
                return None
            record = {"stored_at": stored_at, "payload": record["payload"]}
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Discarding malformed public cache record key=%s", key)
            return None
        _local_put(key, record)
        return record

    def _store(self, key: str, payload: dict, *, stored_at: float | None = None):
        if not isinstance(payload, dict):
            raise TypeError("public cache loader must return a dictionary")
        record = {
            "stored_at": float(self.clock() if stored_at is None else stored_at),
            "payload": payload,
        }
        encoded = json.dumps(
            record, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        fresh_key = f"{key}:fresh"
        stale_key = f"{key}:stale"
        _local_put(fresh_key, record)
        _local_put(stale_key, record)
        try:
            self.redis.set(
                stale_key,
                encoded,
                ex=max(1, int(round(self.fresh_seconds + self.stale_seconds))),
            )
            self.redis.set(
                fresh_key,
                encoded,
                ex=max(1, int(round(self.fresh_seconds))),
            )
        except RedisError:
            logger.warning("Redis cache write failed", exc_info=True)

    def store_for_test(self, key: str, payload: dict, *, stored_at: float):
        self._store(key, payload, stored_at=stored_at)

    def _acquire_lock(self, lock_key: str, token: str) -> bool | None:
        try:
            return bool(
                self.redis.set(
                    lock_key,
                    token,
                    nx=True,
                    px=max(1, int(round(self.lock_seconds * 1000))),
                )
            )
        except RedisError:
            logger.warning("Redis cache lock failed", exc_info=True)
            return None

    def release_lock(self, lock_key: str, token: str) -> None:
        try:
            self.redis.eval(_RELEASE_LOCK_LUA, 1, lock_key, token)
        except RedisError:
            logger.warning("Redis lock release failed", exc_info=True)

    @staticmethod
    def _bounded_load(loader: Callable[[], dict]) -> dict:
        if not _DB_LOAD_SLOTS.acquire(blocking=False):
            raise PublicCacheBusy(retry_after=1)
        try:
            return loader()
        finally:
            _DB_LOAD_SLOTS.release()

    def _stale_age_is_allowed(self, record: dict) -> bool:
        age = max(0.0, float(self.clock()) - float(record["stored_at"]))
        return age <= self.fresh_seconds + self.stale_seconds

    def _load_and_store(
        self,
        key: str,
        loader: Callable[[], dict],
        stale: dict | None,
    ) -> CacheResult:
        started = time.perf_counter()
        try:
            payload = self._bounded_load(loader)
            self._store(key, payload)
            return CacheResult(
                payload,
                "miss",
                (time.perf_counter() - started) * 1000.0,
            )
        except Exception:
            if stale is not None and self._stale_age_is_allowed(stale):
                return CacheResult(stale["payload"], "stale", 0.0)
            raise

    def get_or_load(self, key: str, loader: Callable[[], dict]) -> CacheResult:
        fresh = self._read_json(
            f"{key}:fresh", max_age=self.fresh_seconds
        )
        if fresh is not None:
            return CacheResult(fresh["payload"], "hit", 0.0)

        stale = self._read_json(
            f"{key}:stale",
            max_age=self.fresh_seconds + self.stale_seconds,
        )
        token = secrets.token_hex(16)
        lock_key = f"{key}:lock"
        acquired = self._acquire_lock(lock_key, token)

        if acquired is None:
            if stale is not None and self._stale_age_is_allowed(stale):
                return CacheResult(stale["payload"], "stale", 0.0)
            return self._load_and_store(key, loader, stale)

        if acquired:
            try:
                return self._load_and_store(key, loader, stale)
            finally:
                self.release_lock(lock_key, token)

        if stale is not None and self._stale_age_is_allowed(stale):
            return CacheResult(stale["payload"], "stale", 0.0)

        deadline = time.monotonic() + self.wait_seconds
        while time.monotonic() < deadline:
            time.sleep(random.uniform(0.015, 0.035))
            fresh = self._read_json(
                f"{key}:fresh", max_age=self.fresh_seconds
            )
            if fresh is not None:
                return CacheResult(fresh["payload"], "hit", 0.0)
        raise PublicCacheBusy(retry_after=1)


def get_redis_client() -> Redis:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT
    with _REDIS_CLIENT_LOCK:
        if _REDIS_CLIENT is None:
            _REDIS_CLIENT = Redis.from_url(
                os.getenv("RADAR_REDIS_URL", "redis://127.0.0.1:6379/0"),
                decode_responses=False,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
                health_check_interval=30,
            )
    return _REDIS_CLIENT


def _cache_enabled() -> bool:
    return os.getenv("RADAR_PUBLIC_CACHE_ENABLED", "0").strip() == "1"


def get_or_load_public_payload(
    *,
    endpoint: str,
    tier: str,
    versions: dict[str, int],
    query: dict,
    loader: Callable[[], dict],
    force_refresh: bool = False,
) -> CacheResult:
    if force_refresh or tier == "admin" or not _cache_enabled():
        started = time.perf_counter()
        payload = loader()
        return CacheResult(
            payload,
            "bypass",
            (time.perf_counter() - started) * 1000.0,
        )
    key = build_public_cache_key(
        endpoint=endpoint,
        tier=tier,
        versions=versions,
        query=query,
        schema_version=_env_int("RADAR_CACHE_SCHEMA_VERSION", 1, 1, 9999),
    )
    return PublicResponseCache(redis_client=get_redis_client()).get_or_load(
        key, loader
    )


def _validated_dataset_names(names: Iterable[str]) -> tuple[str, ...]:
    validated = tuple(dict.fromkeys(str(name) for name in names))
    if not validated or any(name not in ALLOWED_DATASETS for name in validated):
        raise ValueError("invalid public dataset name")
    return validated


def _cache_version_locally(name: str, version: int, now: float) -> None:
    with _VERSION_CACHE_LOCK:
        _VERSION_CACHE[name] = (int(version), now)


def get_current_dataset_versions(names: Iterable[str]) -> dict[str, int]:
    validated = _validated_dataset_names(names)
    client = get_redis_client()
    now = time.monotonic()
    versions: dict[str, int] = {}
    missing: list[str] = []
    last_known: dict[str, int] = {}

    for name in validated:
        try:
            raw = client.get(f"radar:dataset-version:{name}")
            if raw is not None:
                version = int(raw)
                versions[name] = version
                _cache_version_locally(name, version, now)
                continue
        except (RedisError, TypeError, ValueError):
            logger.warning(
                "Redis dataset version read failed name=%s", name, exc_info=True
            )

        with _VERSION_CACHE_LOCK:
            local = _VERSION_CACHE.get(name)
        if local is not None:
            last_known[name] = local[0]
        if local is not None and now - local[1] <= _VERSION_CACHE_SECONDS:
            versions[name] = local[0]
        else:
            missing.append(name)

    if missing:
        try:
            with get_conn() as conn:
                durable = get_dataset_versions(conn, tuple(missing))
        except Exception:
            if all(name in last_known for name in missing):
                logger.warning(
                    "Using last-known dataset versions while Redis and PostgreSQL are unavailable",
                    exc_info=True,
                )
                versions.update(
                    {name: last_known[name] for name in missing}
                )
                return {name: versions[name] for name in validated}
            raise
        for name in missing:
            version = int(durable[name])
            versions[name] = version
            _cache_version_locally(name, version, now)
            try:
                client.set(f"radar:dataset-version:{name}", str(version))
            except RedisError:
                logger.warning(
                    "Redis dataset version mirror failed name=%s",
                    name,
                    exc_info=True,
                )

    return {name: versions[name] for name in validated}


def publish_dataset_versions(versions: Mapping[str, int]) -> None:
    validated = _validated_dataset_names(versions.keys())
    client = get_redis_client()
    now = time.monotonic()
    for name in validated:
        version = int(versions[name])
        if version < 0:
            raise ValueError("dataset version must be non-negative")
        _cache_version_locally(name, version, now)
        try:
            client.set(f"radar:dataset-version:{name}", str(version))
        except RedisError:
            logger.warning(
                "Redis dataset version publish failed name=%s",
                name,
                exc_info=True,
            )

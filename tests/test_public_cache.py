import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from services import public_cache
from services.public_cache import PublicCacheBusy, PublicResponseCache


class FakeClock:
    def __init__(self, value):
        self.value = float(value)

    def __call__(self):
        return self.value


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.fail = False
        self._lock = threading.Lock()

    def _check(self):
        if self.fail:
            raise public_cache.RedisError("redis unavailable")

    @staticmethod
    def _bytes(value):
        return value if isinstance(value, bytes) else str(value).encode("utf-8")

    def set(self, key, value, *, ex=None, px=None, nx=False):
        del ex, px
        self._check()
        with self._lock:
            if nx and key in self.values:
                return False
            self.values[key] = self._bytes(value)
            return True

    def get(self, key):
        self._check()
        with self._lock:
            return self.values.get(key)

    def eval(self, script, numkeys, key, token):
        del script, numkeys
        self._check()
        with self._lock:
            if self.values.get(key) == self._bytes(token):
                del self.values[key]
                return 1
            return 0

    def delete(self, *keys):
        with self._lock:
            for key in keys:
                self.values.pop(key, None)


@pytest.fixture(autouse=True)
def _reset_process_cache():
    public_cache._clear_local_cache_for_test()
    yield
    public_cache._clear_local_cache_for_test()


@pytest.fixture
def fake_redis():
    return FakeRedis()


def test_fresh_hit_does_not_call_loader(fake_redis):
    cache = PublicResponseCache(redis_client=fake_redis, clock=FakeClock(100.0))
    cache.store_for_test("key", {"signals": [1]}, stored_at=99.0)
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return {"signals": [2]}

    result = cache.get_or_load("key", loader)

    assert result.status == "hit"
    assert result.payload == {"signals": [1]}
    assert calls == 0


def test_one_hundred_waiters_execute_one_loader(fake_redis):
    cache_a = PublicResponseCache(redis_client=fake_redis)
    cache_b = PublicResponseCache(redis_client=fake_redis)
    barrier = threading.Barrier(100)
    calls = 0
    lock = threading.Lock()

    def load():
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.05)
        return {"signals": [1]}

    def request(index):
        barrier.wait()
        cache = cache_a if index % 2 else cache_b
        return cache.get_or_load("same-key", load).payload

    with ThreadPoolExecutor(max_workers=100) as pool:
        payloads = list(pool.map(request, range(100)))

    assert calls == 1
    assert payloads == [{"signals": [1]}] * 100


def test_loader_error_serves_only_bounded_stale(fake_redis):
    clock = FakeClock(200.0)
    cache = PublicResponseCache(redis_client=fake_redis, clock=clock)
    cache.store_for_test("key", {"signals": [1]}, stored_at=100.0)

    def fail():
        raise RuntimeError("db down")

    result = cache.get_or_load("key", fail)
    assert result.status == "stale"
    assert result.payload == {"signals": [1]}

    clock.value = 400.0
    with pytest.raises(RuntimeError, match="db down"):
        cache.get_or_load("key", fail)


def test_lock_release_requires_ownership_token(fake_redis):
    cache = PublicResponseCache(redis_client=fake_redis)
    fake_redis.set("key:lock", "new-owner", px=5000)

    cache.release_lock("key:lock", "old-owner")

    assert fake_redis.get("key:lock") == b"new-owner"


def test_redis_down_allows_only_two_concurrent_loaders(monkeypatch, fake_redis):
    fake_redis.fail = True
    monkeypatch.setattr(
        public_cache, "_DB_LOAD_SLOTS", threading.BoundedSemaphore(2)
    )
    cache = PublicResponseCache(redis_client=fake_redis)
    entered = 0
    entered_lock = threading.Lock()
    both_entered = threading.Event()
    release = threading.Event()

    def load():
        nonlocal entered
        with entered_lock:
            entered += 1
            if entered == 2:
                both_entered.set()
        release.wait(timeout=1)
        return {"signals": [1]}

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(cache.get_or_load, "a", load)
        second = pool.submit(cache.get_or_load, "b", load)
        assert both_entered.wait(timeout=1)
        third = pool.submit(cache.get_or_load, "c", load)
        with pytest.raises(PublicCacheBusy) as exc_info:
            third.result(timeout=1)
        assert exc_info.value.retry_after == 1
        release.set()
        assert first.result(timeout=1).status == "miss"
        assert second.result(timeout=1).status == "miss"


def test_version_lookup_falls_back_to_postgres_and_mirrors_redis(
    monkeypatch, fake_redis
):
    events = []

    @contextmanager
    def fake_get_conn():
        events.append("db")
        yield object()

    monkeypatch.setattr(public_cache, "get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(public_cache, "get_conn", fake_get_conn)
    monkeypatch.setattr(
        public_cache,
        "get_dataset_versions",
        lambda conn, names: {name: 7 for name in names},
    )

    assert public_cache.get_current_dataset_versions(("signals",)) == {
        "signals": 7
    }
    assert events == ["db"]
    assert fake_redis.get("radar:dataset-version:signals") == b"7"

    assert public_cache.get_current_dataset_versions(("signals",)) == {
        "signals": 7
    }
    assert events == ["db"]


def test_version_lookup_keeps_last_known_version_when_redis_and_db_are_down(
    monkeypatch, fake_redis
):
    fake_redis.fail = True
    monkeypatch.setattr(public_cache, "get_redis_client", lambda: fake_redis)
    with public_cache._VERSION_CACHE_LOCK:
        public_cache._VERSION_CACHE["signals"] = (
            9,
            time.monotonic() - public_cache._VERSION_CACHE_SECONDS - 1,
        )

    @contextmanager
    def unavailable_db():
        raise RuntimeError("db down")
        yield

    monkeypatch.setattr(public_cache, "get_conn", unavailable_db)

    assert public_cache.get_current_dataset_versions(("signals",)) == {
        "signals": 9
    }


def test_stored_record_contains_only_timestamp_and_payload(fake_redis):
    cache = PublicResponseCache(redis_client=fake_redis, clock=FakeClock(123.0))
    cache.store_for_test("key", {"signals": []}, stored_at=123.0)

    record = json.loads(fake_redis.get("key:fresh"))

    assert record == {"stored_at": 123.0, "payload": {"signals": []}}

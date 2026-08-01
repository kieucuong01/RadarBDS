import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.public_cache import PublicResponseCache


REDIS_URL = os.getenv("RADAR_TEST_REDIS_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not REDIS_URL, reason="RADAR_TEST_REDIS_URL is not configured"
)


def test_real_redis_collapses_load_across_cache_instances():
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url(REDIS_URL, decode_responses=False)
    key = f"radar:test:{uuid.uuid4().hex}"
    cache_a = PublicResponseCache(redis_client=client)
    cache_b = PublicResponseCache(redis_client=client)
    barrier = threading.Barrier(2)
    calls = 0
    calls_lock = threading.Lock()

    def loader():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return {"signals": [1]}

    def request(cache):
        barrier.wait()
        return cache.get_or_load(key, loader)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request, (cache_a, cache_b)))

        assert calls == 1
        assert [result.payload for result in results] == [
            {"signals": [1]},
            {"signals": [1]},
        ]
        assert sorted(result.status for result in results) == ["hit", "miss"]
    finally:
        keys = list(client.scan_iter(match=f"{key}*"))
        if keys:
            client.delete(*keys)

from crawler import apify_token_pool as pool
from crawler.facebook_apify import FacebookApifyCrawler


def test_token_pool_masks_secret_and_rotates_by_remaining_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    tokens = pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 950,
        "active": True,
    })
    key_a = tokens[0]["id"]
    tokens = pool.upsert_token({
        "label": "Key B",
        "token": "apify_api_BBBBBBBBBBBBB",
        "monthly_quota": 950,
        "active": True,
    })

    assert "token" not in tokens[0]
    assert tokens[0]["token_mask"].startswith("apify_ap")

    pool.record_usage(key_a, 900)
    chosen = pool.acquire_token(required_posts=330)

    assert chosen["label"] == "Key B"
    assert chosen["token"] == "apify_api_BBBBBBBBBBBBB"


def test_token_pool_disables_key_when_recorded_usage_reaches_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    tokens = pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 10,
        "active": True,
    })
    key_a = tokens[0]["id"]

    pool.record_usage(key_a, 10)
    tokens = pool.list_tokens_public()

    assert tokens[0]["used_this_month"] == 10
    assert tokens[0]["remaining"] == 0
    assert tokens[0]["active"] is False
    assert tokens[0]["last_error"] == "monthly_quota_reached"


def test_token_pool_marks_limit_error_as_exhausted_and_rotates(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    tokens = pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 950,
        "active": True,
    })
    key_a = tokens[0]["id"]
    pool.upsert_token({
        "label": "Key B",
        "token": "apify_api_BBBBBBBBBBBBB",
        "monthly_quota": 950,
        "active": True,
    })

    pool.mark_limit_exhausted(key_a, "Monthly usage limit exceeded")
    tokens = pool.list_tokens_public()
    chosen = pool.acquire_token(required_posts=330)

    key_a_public = next(t for t in tokens if t["id"] == key_a)
    assert key_a_public["used_this_month"] == 950
    assert key_a_public["remaining"] == 0
    assert key_a_public["active"] is False
    assert key_a_public["last_error"] == "Monthly usage limit exceeded"
    assert chosen["label"] == "Key B"


def test_facebook_apify_pool_disables_limited_key_and_retries_next(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    tokens = pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 950,
        "active": True,
    })
    key_a = tokens[0]["id"]
    pool.upsert_token({
        "label": "Key B",
        "token": "apify_api_BBBBBBBBBBBBB",
        "monthly_quota": 950,
        "active": True,
    })
    calls = []

    class FakeActor:
        def __init__(self, token):
            self.token = token

        def call(self, run_input):
            if self.token.endswith("AAAAAAAAAAAAA"):
                raise RuntimeError("Monthly usage limit exceeded")
            return {"defaultDatasetId": "dataset-1"}

    class FakeDataset:
        def iterate_items(self):
            return [{"id": "1"}, {"id": "2"}, {"id": "3"}]

    class FakeClient:
        def __init__(self, token):
            self.token = token
            calls.append(token)

        def actor(self, actor_id):
            return FakeActor(self.token)

        def dataset(self, dataset_id):
            return FakeDataset()

    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = True
    crawler._client_cls = FakeClient
    crawler.actor = "apify/facebook-posts-scraper"

    items = crawler._run_actor({"startUrls": []}, required_posts=3)
    tokens = pool.list_tokens_public()
    key_a_public = next(t for t in tokens if t["id"] == key_a)

    assert calls == ["apify_api_AAAAAAAAAAAAA", "apify_api_BBBBBBBBBBBBB"]
    assert len(items) == 3
    assert key_a_public["used_this_month"] == 950
    assert key_a_public["active"] is False


def test_facebook_apify_batch_uses_per_profile_results_limit(monkeypatch):
    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = False
    crawler.actor = "apify/facebook-posts-scraper"
    calls = []

    def fake_run_actor(run_input, required_posts):
        calls.append((run_input, required_posts))
        return [
            {
                "text": "Ban dat Tan An",
                "url": "https://facebook.test/posts/1",
                "postId": "1",
                "timestamp": 1893456000,
                "inputUrl": "https://facebook.com/a",
            }
        ]

    monkeypatch.setattr(crawler, "_run_actor", fake_run_actor)

    posts = crawler.crawl_all(
        [
            {"url": "https://facebook.com/a", "tier": 10, "broker_name": "A", "default_area": "TDM"},
            {"url": "https://facebook.com/b", "tier": 10, "broker_name": "B", "default_area": "TDM"},
            {"url": "https://facebook.com/c", "tier": 10, "broker_name": "C", "default_area": "TDM"},
        ],
        mode="incremental",
    )

    assert len(posts) == 1
    assert calls[0][0]["resultsLimit"] == 10
    assert len(calls[0][0]["startUrls"]) == 3
    assert calls[0][1] == 30


def test_facebook_apify_clamps_actor_overfetch_per_profile(monkeypatch):
    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = False
    crawler.actor = "apify/facebook-posts-scraper"

    def fake_run_actor(run_input, required_posts):
        assert required_posts == 4
        return [
            {
                "text": f"Ban dat Tan An {i}",
                "url": f"https://facebook.test/a/{i}",
                "postId": f"a-{i}",
                "timestamp": 1893456000,
                "inputUrl": "https://facebook.com/a",
            }
            for i in range(5)
        ] + [
            {
                "text": f"Ban dat Hiep An {i}",
                "url": f"https://facebook.test/b/{i}",
                "postId": f"b-{i}",
                "timestamp": 1893456000,
                "inputUrl": "https://facebook.com/b/",
            }
            for i in range(5)
        ]

    monkeypatch.setattr(crawler, "_run_actor", fake_run_actor)

    posts = crawler.crawl_all(
        [
            {"url": "https://facebook.com/a", "tier": 2, "broker_name": "A", "default_area": "TDM"},
            {"url": "https://facebook.com/b", "tier": 2, "broker_name": "B", "default_area": "TDM"},
        ],
        mode="incremental",
    )

    assert len(posts) == 4
    assert [p["broker_name"] for p in posts].count("A") == 2
    assert [p["broker_name"] for p in posts].count("B") == 2


def test_facebook_apify_pool_treats_remaining_usage_error_as_exhausted(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    tokens = pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 950,
        "active": True,
    })
    key_a = tokens[0]["id"]
    pool.upsert_token({
        "label": "Key B",
        "token": "apify_api_BBBBBBBBBBBBB",
        "monthly_quota": 950,
        "active": True,
    })

    class FakeActor:
        def __init__(self, token):
            self.token = token

        def call(self, run_input):
            if self.token.endswith("AAAAAAAAAAAAA"):
                raise RuntimeError(
                    "By launching this job you will exceed your remaining usage of $0.001522. "
                    "Please consider upgrading to a paid plan at https://console.apify.com/billing/subscription"
                )
            return {"defaultDatasetId": "dataset-1"}

    class FakeDataset:
        def iterate_items(self):
            return [{"id": "1"}]

    class FakeClient:
        def __init__(self, token):
            self.token = token

        def actor(self, actor_id):
            return FakeActor(self.token)

        def dataset(self, dataset_id):
            return FakeDataset()

    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = True
    crawler._client_cls = FakeClient
    crawler.actor = "apify/facebook-posts-scraper"

    crawler._run_actor({"startUrls": []}, required_posts=1)
    key_a_public = next(t for t in pool.list_tokens_public() if t["id"] == key_a)

    assert key_a_public["used_this_month"] == 950
    assert key_a_public["remaining"] == 0
    assert key_a_public["active"] is False
    assert "remaining usage" in key_a_public["last_error"]

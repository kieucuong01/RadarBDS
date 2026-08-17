import pytest

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

    def fake_run_actor(run_input, required_posts, token_rec=None):
        assert token_rec is None
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

    def fake_run_actor(run_input, required_posts, token_rec=None):
        assert token_rec is None
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


def test_facebook_apify_splits_profile_group_by_token_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 25,
        "active": True,
    })
    pool.upsert_token({
        "label": "Key B",
        "token": "apify_api_BBBBBBBBBBBBB",
        "monthly_quota": 25,
        "active": True,
    })
    calls = []

    class FakeActor:
        def __init__(self, token):
            self.token = token

        def call(self, run_input):
            calls.append((self.token, run_input))
            return {
                "defaultDatasetId": self.token,
                "items": [
                    {
                        "id": f"post-{index}",
                        "text": "Ban dat Tan An",
                        "url": f"https://facebook.test/posts/{index}",
                        "timestamp": 1893456000,
                        "inputUrl": start["url"],
                    }
                    for index, start in enumerate(run_input["startUrls"], start=1)
                ],
            }

    class FakeDataset:
        def __init__(self, items):
            self.items = items

        def iterate_items(self):
            return list(self.items)

    class FakeClient:
        datasets = {}

        def __init__(self, token):
            self.token = token

        def actor(self, _actor_id):
            actor = FakeActor(self.token)
            original_call = actor.call

            def call(run_input):
                result = original_call(run_input)
                self.datasets[result["defaultDatasetId"]] = result["items"]
                return result

            actor.call = call
            return actor

        def dataset(self, dataset_id):
            return FakeDataset(self.datasets[dataset_id])

    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = True
    crawler._client_cls = FakeClient
    crawler.actor = "apify/facebook-posts-scraper"

    posts = crawler.crawl_all(
        [
            {
                "url": f"https://facebook.com/broker-{index}",
                "tier": 10,
                "broker_name": f"Broker {index}",
                "default_area": "TDM",
            }
            for index in range(4)
        ],
        mode="incremental",
    )

    assert [len(call[1]["startUrls"]) for call in calls] == [2, 2]
    assert calls[0][0] != calls[1][0]
    assert len(posts) == 4
    assert crawler.last_run_report == {
        "partial": False,
        "messages": [],
        "completed_profiles": 4,
        "unattempted_profiles": 0,
        "actor_runs": 2,
    }


def test_facebook_apify_exhausted_token_is_zeroed_and_profiles_are_replanned(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    tokens = pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 30,
        "active": True,
    })
    key_a = tokens[0]["id"]
    pool.upsert_token({
        "label": "Key B",
        "token": "apify_api_BBBBBBBBBBBBB",
        "monthly_quota": 15,
        "active": True,
    })
    calls = []

    class FakeActor:
        def __init__(self, token):
            self.token = token

        def call(self, run_input):
            calls.append((self.token, len(run_input["startUrls"])))
            if self.token.endswith("AAAAAAAAAAAAA"):
                raise RuntimeError("Monthly usage hard limit exceeded")
            return {
                "defaultDatasetId": self.token,
                "items": [
                    {
                        "id": start["url"].rsplit("-", 1)[-1],
                        "text": "Ban dat Tan An",
                        "url": f"https://facebook.test/posts/{index}",
                        "timestamp": 1893456000,
                        "inputUrl": start["url"],
                    }
                    for index, start in enumerate(run_input["startUrls"], start=1)
                ],
            }

    class FakeDataset:
        def __init__(self, items):
            self.items = items

        def iterate_items(self):
            return list(self.items)

    class FakeClient:
        datasets = {}

        def __init__(self, token):
            self.token = token

        def actor(self, _actor_id):
            actor = FakeActor(self.token)
            original_call = actor.call

            def call(run_input):
                result = original_call(run_input)
                self.datasets[result["defaultDatasetId"]] = result["items"]
                return result

            actor.call = call
            return actor

        def dataset(self, dataset_id):
            return FakeDataset(self.datasets[dataset_id])

    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = True
    crawler._client_cls = FakeClient
    crawler.actor = "apify/facebook-posts-scraper"

    posts = crawler.crawl_all(
        [
            {
                "url": f"https://facebook.com/broker-{index}",
                "tier": 10,
                "broker_name": f"Broker {index}",
                "default_area": "TDM",
            }
            for index in range(2)
        ],
        mode="incremental",
    )

    key_a_public = next(t for t in pool.list_tokens_public() if t["id"] == key_a)
    assert calls == [
        ("apify_api_AAAAAAAAAAAAA", 2),
        ("apify_api_BBBBBBBBBBBBB", 1),
        ("apify_api_BBBBBBBBBBBBB", 1),
    ]
    assert len(posts) == 2
    assert key_a_public["used_this_month"] == 30
    assert key_a_public["remaining"] == 0
    assert key_a_public["active"] is False
    assert key_a_public["last_error"] == "Monthly usage hard limit exceeded"
    assert crawler.last_run_report["partial"] is False
    assert crawler.last_run_report["completed_profiles"] == 2


def test_facebook_apify_transient_error_does_not_zero_token(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    tokens = pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 30,
        "active": True,
    })
    key_a = tokens[0]["id"]

    class FakeActor:
        def call(self, run_input):
            assert run_input["resultsLimit"] == 10
            raise RuntimeError("temporary network timeout")

    class FakeClient:
        def __init__(self, _token):
            pass

        def actor(self, _actor_id):
            return FakeActor()

    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = True
    crawler._client_cls = FakeClient
    crawler.actor = "apify/facebook-posts-scraper"

    with pytest.raises(RuntimeError, match="temporary network timeout"):
        crawler.crawl_all(
            [{
                "url": "https://facebook.com/broker-1",
                "tier": 10,
                "broker_name": "Broker 1",
                "default_area": "TDM",
            }],
            mode="incremental",
        )

    key_a_public = next(t for t in pool.list_tokens_public() if t["id"] == key_a)
    assert key_a_public["used_this_month"] == 0
    assert key_a_public["remaining"] == 30
    assert key_a_public["active"] is True
    assert key_a_public["last_error"] == "temporary network timeout"


def test_facebook_apify_preserves_partial_posts_and_runs_smaller_group(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 15,
        "active": True,
    })
    calls = []

    class FakeActor:
        def call(self, run_input):
            per_profile = run_input["resultsLimit"]
            calls.append((per_profile, len(run_input["startUrls"])))
            return {
                "defaultDatasetId": f"dataset-{len(calls)}",
                "items": [
                    {
                        "id": f"{per_profile}-{index}",
                        "text": "Ban dat Tan An",
                        "url": f"https://facebook.test/posts/{per_profile}-{index}",
                        "timestamp": 1893456000,
                        "inputUrl": run_input["startUrls"][0]["url"],
                    }
                    for index in range(per_profile)
                ],
            }

    class FakeDataset:
        def __init__(self, items):
            self.items = items

        def iterate_items(self):
            return list(self.items)

    class FakeClient:
        datasets = {}

        def __init__(self, _token):
            pass

        def actor(self, _actor_id):
            actor = FakeActor()
            original_call = actor.call

            def call(run_input):
                result = original_call(run_input)
                self.datasets[result["defaultDatasetId"]] = result["items"]
                return result

            actor.call = call
            return actor

        def dataset(self, dataset_id):
            return FakeDataset(self.datasets[dataset_id])

    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = True
    crawler._client_cls = FakeClient
    crawler.actor = "apify/facebook-posts-scraper"

    posts = crawler.crawl_all(
        [
            {
                "url": "https://facebook.com/broker-a",
                "tier": 10,
                "broker_name": "Broker A",
                "default_area": "TDM",
            },
            {
                "url": "https://facebook.com/broker-b",
                "tier": 10,
                "broker_name": "Broker B",
                "default_area": "TDM",
            },
            {
                "url": "https://facebook.com/broker-c",
                "tier": 5,
                "broker_name": "Broker C",
                "default_area": "TDM",
            },
        ],
        mode="incremental",
    )

    assert calls == [(10, 1), (5, 1)]
    assert len(posts) == 15
    assert crawler.last_run_report["partial"] is True
    assert crawler.last_run_report["completed_profiles"] == 2
    assert crawler.last_run_report["unattempted_profiles"] == 1
    assert any("limit=10" in msg for msg in crawler.last_run_report["messages"])


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

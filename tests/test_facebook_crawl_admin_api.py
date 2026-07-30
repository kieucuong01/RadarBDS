from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest import mock


def sample_profiles():
    return [
        {
            "city": "Thủ Dầu Một",
            "url": "https://www.facebook.com/broker-a",
            "broker_name": "Broker A",
            "daily_limit": 30,
            "range_days": 7,
            "crawl_every_days": 1,
            "active": True,
        },
        {
            "city": "Bến Cát",
            "url": "https://www.facebook.com/broker-b",
            "broker_name": "Broker B",
            "daily_limit": 20,
            "range_days": 14,
            "crawl_every_days": 3,
            "active": True,
        },
    ]


def test_profile_url_normalization_accepts_canonical_variants_and_rejects_non_profiles():
    from services.admin_quality import normalize_facebook_profile_url

    expected = "https://www.facebook.com/broker-a"
    assert normalize_facebook_profile_url("facebook.com/broker-a/") == expected
    assert normalize_facebook_profile_url("https://m.facebook.com/broker-a?ref=bookmarks") == expected
    assert normalize_facebook_profile_url("https://www.facebook.com/broker-a/posts/123") == expected
    assert normalize_facebook_profile_url("http://www.facebook.com/broker-a") == ""
    assert normalize_facebook_profile_url("https://example.com/broker-a") == ""
    assert normalize_facebook_profile_url("https://www.facebook.com/groups/123") == ""


def test_profile_normalization_deduplicates_canonical_urls_and_revision_is_stable():
    from services.admin_quality import (
        facebook_profile_revision,
        normalize_facebook_profiles,
    )

    raw = sample_profiles() + [{
        **sample_profiles()[0],
        "url": "https://m.facebook.com/broker-a/",
        "broker_name": "Duplicate",
    }]
    normalized = normalize_facebook_profiles(raw)

    assert [item["url"] for item in normalized] == [
        "https://www.facebook.com/broker-a",
        "https://www.facebook.com/broker-b",
    ]
    assert facebook_profile_revision(normalized) == facebook_profile_revision(
        [{key: item[key] for key in reversed(item)} for item in reversed(normalized)]
    )
    changed = [{**normalized[0], "daily_limit": 31}, normalized[1]]
    assert facebook_profile_revision(changed) != facebook_profile_revision(normalized)


def test_profile_due_metadata_reuses_scheduler_bucket():
    from crawler.facebook_apify import profile_due_on
    from services.admin_quality import facebook_profile_due_metadata

    profile = {
        "url": "https://www.facebook.com/broker-b",
        "crawl_every_days": 3,
    }
    today = date(2026, 7, 30)
    metadata = facebook_profile_due_metadata(profile, {}, today=today)

    assert metadata["due_today"] is profile_due_on(profile, today)
    next_due = date.fromisoformat(metadata["next_due_date"])
    assert next_due >= today
    assert profile_due_on(profile, next_due)
    assert (next_due - today).days < 3


def test_duplicate_analysis_paging_defaults_to_actionable_and_filters_before_slice():
    from services.admin_quality import paginate_facebook_duplicate_analysis

    analysis = {
        "comparisons": [
            {"city": "Thủ Dầu Một", "recommended_crawl_every_days": 7, "shared_lots": 20},
            {"city": "Bến Cát", "recommended_crawl_every_days": None, "shared_lots": 18},
            {"city": "Thủ Dầu Một", "recommended_crawl_every_days": 3, "shared_lots": 12},
            {"city": "Bến Cát", "recommended_crawl_every_days": 7, "shared_lots": 10},
        ],
        "by_profile": {},
    }

    page = paginate_facebook_duplicate_analysis(
        analysis,
        actionable=True,
        city="Thủ Dầu Một",
        limit=20,
        offset=0,
    )

    assert page["total"] == 4
    assert page["actionable"] == 3
    assert page["filtered"] == 2
    assert [item["shared_lots"] for item in page["items"]] == [20, 12]


def test_duplicate_analysis_paging_caps_limit_at_fifty():
    from services.admin_quality import paginate_facebook_duplicate_analysis

    analysis = {
        "comparisons": [
            {"city": "Thủ Dầu Một", "recommended_crawl_every_days": 3, "shared_lots": n}
            for n in range(75)
        ],
        "by_profile": {},
    }
    page = paginate_facebook_duplicate_analysis(
        analysis,
        actionable=False,
        limit=500,
        offset=10,
    )

    assert page["filtered"] == 75
    assert len(page["items"]) == 50
    assert page["offset"] == 10
    assert page["limit"] == 50


def test_overview_builder_never_calls_profile_or_duplicate_loaders():
    from services.admin_quality import facebook_crawl_overview

    def forbidden(*_args, **_kwargs):
        raise AssertionError("expensive profile loader must not run")

    overview = facebook_crawl_overview(
        schedule_status_fn=lambda: {
            "installed": True,
            "next_run_time": "2026-07-30T21:00:00+07:00",
            "state": "active",
        },
        crawl_ops_summary_fn=lambda: {
            "last_run": {"source": "facebook", "status": "done"},
            "source_errors": [],
            "lock_blockers": [],
        },
        active_job_fn=lambda: None,
        recent_jobs_fn=lambda _limit: [{"id": "done-1", "status": "succeeded"}],
        apify_tokens_fn=lambda: [{"id": "token-1", "remaining_usd": 9.5, "enabled": True}],
        profile_stats_fn=forbidden,
        duplicate_analysis_fn=forbidden,
    )

    assert overview["schedule"]["installed"] is True
    assert overview["last_facebook_run"]["source"] == "facebook"
    assert overview["latest_job"]["id"] == "done-1"
    assert overview["apify"]["enabled_tokens"] == 1
    assert overview["problems"] == []


def test_routes_register_focused_facebook_crawl_endpoints():
    source = Path("routes/admin_api.py").read_text(encoding="utf-8")

    assert '"/admin/api/facebook-crawl/overview"' in source
    assert '"/admin/api/facebook-crawl/profiles"' in source
    assert '"/admin/api/facebook-crawl/duplicates"' in source
    assert '"/admin/api/facebook-crawl/config"' in source


def test_overview_endpoint_returns_light_payload_without_profile_queries():
    import app as app_module

    with mock.patch.object(app_module, "_admin_request_authorized", return_value=True), \
         mock.patch.object(app_module, "_daily_crawl_schedule_status", return_value={
             "installed": True,
             "next_run_time": "2026-07-30 21:00",
         }), \
         mock.patch.object(app_module, "_crawl_ops_summary", return_value={
             "last_run": {"source": "facebook", "status": "done"},
             "source_errors": [],
             "lock_blockers": [],
         }), \
         mock.patch.object(app_module, "_active_facebook_crawl_job", return_value=None), \
         mock.patch.object(
             app_module.admin_job_service.POSTGRES_ADMIN_JOBS,
             "list",
             return_value=[{"id": "job-1", "status": "succeeded"}],
         ), \
         mock.patch.object(app_module, "_apify_tokens_public", return_value=[
             {"id": "token-1", "enabled": True},
         ]), \
         mock.patch.object(
             app_module,
             "_facebook_profile_stats",
             side_effect=AssertionError("overview loaded profile stats"),
         ), \
         mock.patch.object(
             app_module,
             "_facebook_profile_duplicate_analysis",
             side_effect=AssertionError("overview loaded duplicates"),
         ):
        response = app_module.app.test_client().get(
            "/admin/api/facebook-crawl/overview"
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["latest_job"]["id"] == "job-1"
    assert payload["problems"] == []


def test_profiles_endpoint_returns_revision_stats_and_due_metadata():
    import app as app_module

    profiles = sample_profiles()
    stats = {
        profile["url"]: {
            "raw_count": index + 1,
            "latest_crawled_at": None,
            "activity": {},
            "data_quality": {"score": 80},
        }
        for index, profile in enumerate(profiles)
    }
    with mock.patch.object(app_module, "_admin_request_authorized", return_value=True), \
         mock.patch.object(app_module, "_read_facebook_profile_config", return_value=profiles), \
         mock.patch.object(app_module, "_facebook_profile_stats", return_value=stats):
        response = app_module.app.test_client().get(
            "/admin/api/facebook-crawl/profiles"
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["revision"]) == 64
    assert payload["profiles"][0]["raw_count"] == 1
    assert isinstance(payload["profiles"][0]["due_today"], bool)
    assert payload["profiles"][0]["next_due_date"]


def test_manual_run_canonicalizes_mobile_profile_url_before_enqueue():
    import app as app_module

    repository = mock.Mock()
    repository.reconcile_stale.return_value = 0
    repository.active.return_value = None
    repository.create.side_effect = lambda job: dict(job)

    class DeferredThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            self.daemon = daemon

        def start(self):
            return None

    with mock.patch.object(app_module, "_admin_request_authorized", return_value=True), \
         mock.patch.object(
             app_module.admin_job_service,
             "POSTGRES_ADMIN_JOBS",
             repository,
         ), \
         mock.patch.object(
             app_module.admin_job_service.threading,
             "Thread",
             DeferredThread,
         ):
        response = app_module.app.test_client().post(
            "/admin/api/facebook-crawl/run",
            json={
                "url": "https://m.facebook.com/broker-a/?ref=bookmarks",
                "mode": "daily",
                "limit": 30,
                "download_images": False,
            },
        )

    assert response.status_code == 200
    assert response.get_json()["job"]["profile_url"] == (
        "https://www.facebook.com/broker-a"
    )


def test_profiles_endpoint_rejects_stale_revision_without_overwriting(tmp_path):
    import app as app_module
    from services.admin_quality import facebook_profile_revision

    profile_path = tmp_path / "facebook_profiles.json"
    current = sample_profiles()
    grouped = {}
    for item in current:
        saved = dict(item)
        city = saved.pop("city")
        grouped.setdefault(city, []).append(saved)
    profile_path.write_text(
        json.dumps(grouped, ensure_ascii=False),
        encoding="utf-8",
    )
    before = profile_path.read_text(encoding="utf-8")

    class FakeConnection:
        def execute(self, sql, params=None):
            assert "pg_advisory_xact_lock" in sql
            return self

    @contextmanager
    def fake_get_conn():
        yield FakeConnection()

    with mock.patch.object(app_module, "_admin_request_authorized", return_value=True), \
         mock.patch.object(app_module, "FACEBOOK_PROFILE_PATH", profile_path), \
         mock.patch.object(app_module, "get_conn", fake_get_conn):
        response = app_module.app.test_client().post(
            "/admin/api/facebook-crawl/profiles",
            json={
                "profiles": [{**current[0], "daily_limit": 99}, current[1]],
                "revision": "0" * 64,
            },
        )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload["error"] == "profile_revision_conflict"
    assert payload["revision"] == facebook_profile_revision(current)
    assert profile_path.read_text(encoding="utf-8") == before


def test_profile_writer_canonicalizes_and_leaves_no_temporary_file(tmp_path):
    from services.admin_quality import write_facebook_profile_config

    profile_path = tmp_path / "facebook_profiles.json"
    saved = write_facebook_profile_config(
        profile_path,
        [{
            **sample_profiles()[0],
            "url": "https://m.facebook.com/broker-a/?ref=bookmarks",
        }],
    )

    assert saved[0]["url"] == "https://www.facebook.com/broker-a"
    assert list(tmp_path.glob(".facebook_profiles.json.*.tmp")) == []
    parsed = json.loads(profile_path.read_text(encoding="utf-8"))
    assert parsed["Thủ Dầu Một"][0]["url"] == "https://www.facebook.com/broker-a"


def test_duplicates_endpoint_validates_and_pages_analysis():
    import app as app_module

    analysis = {
        "comparisons": [
            {
                "city": "Thủ Dầu Một",
                "recommended_crawl_every_days": 3,
                "shared_lots": index,
            }
            for index in range(30)
        ],
        "by_profile": {},
    }
    profiles = sample_profiles()
    with mock.patch.object(app_module, "_admin_request_authorized", return_value=True), \
         mock.patch.object(app_module, "_read_facebook_profile_config", return_value=profiles), \
         mock.patch.object(app_module, "_facebook_profile_stats", return_value={}), \
         mock.patch.object(
             app_module,
             "_facebook_profile_duplicate_analysis",
             return_value=analysis,
         ):
        response = app_module.app.test_client().get(
            "/admin/api/facebook-crawl/duplicates"
            "?actionable=1&city=Th%E1%BB%A7%20D%E1%BA%A7u%20M%E1%BB%99t&limit=20&offset=5"
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["filtered"] == 30
    assert payload["offset"] == 5
    assert len(payload["items"]) == 20

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app as radar_app
from db import connection
from db.connection import get_conn
from db.schema import init_schema
from services.radar_ask.config import RadarAskSettings
from services.radar_ask.quota_settings import save_radar_ask_quota_settings
from services.radar_ask.repository import RadarAskRepository


NOW = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)
SECRET = "PRIVATE-QUESTION-DO-NOT-EXPOSE-7dc95b"


def _empty_metrics() -> dict:
    empty_window = {
        "questions": 0,
        "runs": 0,
        "by_tier": {},
        "by_model": {},
        "by_depth": {},
        "by_outcome": {},
        "latency_ms": {"p50": None, "p95": None},
        "rates": {
            "provider_failure": 0.0,
            "validation_failure": 0.0,
            "insufficient": 0.0,
        },
        "tokens": {"input": 0, "output": 0, "cache_hit": 0, "cache_miss": 0},
        "feedback_by_question_cohort": {"helpful": 0, "not_helpful": 0},
    }
    return {
        "generated_at": NOW.isoformat(),
        "windows": {
            "today": dict(empty_window),
            "last_7_days": dict(empty_window),
            "month": dict(empty_window),
        },
        "cost": {
            "usage_month": "2026-08-01",
            "actual_usd": "0.000000",
            "reserved_usd": "0.000000",
            "projected_usd": "0.000000",
            "warning_usd": "20.000000",
            "hard_stop_usd": "50.000000",
            "state": "normal",
        },
        "queue": {"depth": 0, "oldest_age_seconds": None},
    }


class _FakeRepository:
    def admin_metrics(self, **_kwargs):
        return _empty_metrics()


@pytest.fixture
def metrics_client(monkeypatch):
    import routes.admin_api as admin_routes

    monkeypatch.delenv("ADMIN_BASIC_USER", raising=False)
    monkeypatch.delenv("ADMIN_BASIC_PASS", raising=False)
    monkeypatch.setenv("RADAR_ASK_MONTHLY_WARN_USD", "20")
    monkeypatch.setenv("RADAR_ASK_MONTHLY_HARD_USD", "50")
    monkeypatch.setattr(admin_routes, "get_repository", lambda: _FakeRepository(), raising=False)
    return radar_app.app.test_client()


@pytest.mark.parametrize("tier", ("guest", "free", "vip"))
def test_metrics_denies_every_non_admin_tier(metrics_client, monkeypatch, tier):
    monkeypatch.setattr(radar_app, "current_tier", lambda: tier)

    response = metrics_client.get("/admin/api/radar-ask/metrics")

    assert response.status_code == 403
    assert response.get_json() == {"ok": False, "error": "admin_required"}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in response.headers


def test_admin_metrics_are_private_and_feature_off_remains_observable(metrics_client, monkeypatch):
    monkeypatch.setattr(radar_app, "current_tier", lambda: "admin")
    monkeypatch.delenv("RADAR_ASK_ENABLED", raising=False)

    response = metrics_client.get("/admin/api/radar-ask/metrics")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["enabled"] is False
    assert payload["metrics"]["cost"]["warning_usd"] == "20.000000"
    assert payload["metrics"]["cost"]["hard_stop_usd"] == "50.000000"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in response.headers


def test_admin_control_room_includes_resilient_radar_ask_health_surface(monkeypatch):
    monkeypatch.setattr(radar_app, "current_tier", lambda: "admin")
    monkeypatch.setattr(
        radar_app,
        "current_user",
        lambda: {"id": 1, "tier": "admin", "identifier_type": "email"},
    )

    response = radar_app.app.test_client().get("/admin/infrastructure")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="radarAskMetrics"' in html
    assert 'id="radarAskMetricsState"' in html
    assert 'id="refreshRadarAskMetricsBtn"' in html
    assert 'aria-live="polite"' in html
    assert "Hỏi Radar BDS" in html
    admin_js = (Path(__file__).resolve().parent.parent / "static/js/admin.js").read_text(encoding="utf-8")
    assert "feedback_by_question_cohort" in admin_js
    assert "Phản hồi theo cohort câu hỏi" in admin_js


def test_admin_control_room_includes_radar_ask_quota_settings_form(monkeypatch):
    monkeypatch.setattr(radar_app, "current_tier", lambda: "admin")
    monkeypatch.setattr(
        radar_app,
        "current_user",
        lambda: {"id": 1, "tier": "admin", "identifier_type": "email"},
    )

    response = radar_app.app.test_client().get("/admin/infrastructure")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="radarAskQuotaSettings"' in html
    assert 'id="radarAskFreeDailyLimit"' in html
    assert 'id="radarAskVipDailyLimit"' in html
    admin_js = (Path(__file__).resolve().parent.parent / "static/js/admin.js").read_text(encoding="utf-8")
    assert "loadRadarAskSettings" in admin_js


def test_admin_radar_ask_quota_settings_get_and_post(monkeypatch):
    connection.close_all()
    init_schema()
    save_radar_ask_quota_settings(free_daily_limit=5, vip_daily_limit=20, updated_by="pytest-reset")
    monkeypatch.setattr(radar_app, "current_tier", lambda: "admin")
    monkeypatch.setattr(
        radar_app,
        "current_user",
        lambda: {"id": 7, "tier": "admin", "identifier": "owner@example.test"},
    )
    client = radar_app.app.test_client()

    initial = client.get("/admin/api/radar-ask/settings")
    assert initial.status_code == 200
    assert initial.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in initial.headers
    assert initial.get_json()["settings"]["daily_limits"] == {"free": 5, "vip": 20}
    assert initial.get_json()["settings"]["admin_unlimited"] is True

    saved = client.post(
        "/admin/api/radar-ask/settings",
        json={"daily_limits": {"free": 4, "vip": 25}},
    )
    payload = saved.get_json()

    assert saved.status_code == 200
    assert payload["ok"] is True
    assert payload["settings"]["daily_limits"] == {"free": 4, "vip": 25}
    assert payload["settings"]["admin_unlimited"] is True

    invalid = client.post(
        "/admin/api/radar-ask/settings",
        json={"daily_limits": {"free": -1, "vip": 25}},
    )
    assert invalid.status_code == 400
    assert invalid.get_json() == {"ok": False, "error": "invalid_daily_limit"}

    save_radar_ask_quota_settings(free_daily_limit=5, vip_daily_limit=20, updated_by="pytest-reset")
    connection.close_all()


@pytest.mark.parametrize("tier", ("guest", "free", "vip"))
def test_radar_ask_quota_settings_denies_non_admin(monkeypatch, tier):
    monkeypatch.setattr(radar_app, "current_tier", lambda: tier)

    response = radar_app.app.test_client().get("/admin/api/radar-ask/settings")

    assert response.status_code == 403
    assert response.get_json() == {"ok": False, "error": "admin_required"}


@pytest.fixture
def aggregate_rows():
    connection.close_all()
    init_schema()
    run_ids: list = []
    user_ids: list[int] = []
    with get_conn() as conn:
        database = conn.execute("SELECT current_database() AS name").fetchone()
        assert database is not None
        assert database["name"] == "radar_bds_test"
        for tier in ("free", "vip", "admin"):
            user = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier)
                VALUES (?, 'email', 'test-hash', ?)
                """,
                (f"radar-ask-admin-{tier}-{uuid4().hex}@example.test", tier),
            )
            user_ids.append(int(user.lastrowid))

        session_id = uuid4()
        conn.execute(
            """
            INSERT INTO radar_ask_sessions (id, user_id, title, summary_json, created_at, updated_at)
            VALUES (?, ?, ?, '{}'::jsonb, ?, ?)
            """,
            (session_id, user_ids[0], f"Secret session {SECRET}", NOW - timedelta(days=20), NOW),
        )

        def seed_run(
            *,
            tier: str,
            model: str,
            depth: str,
            status: str,
            outcome: str | None,
            age: timedelta,
            latency_ms: int | None,
            actual: str,
            reserved: str = "0",
            settlement: str = "settled",
            expires: datetime | None = None,
            prompt: int = 0,
            completion: int = 0,
            cache_hit: int = 0,
            cache_miss: int = 0,
        ):
            run_id = uuid4()
            run_ids.append(run_id)
            created_at = NOW - age
            started_at = created_at + timedelta(seconds=1) if latency_ms is not None else None
            completed_at = (
                started_at + timedelta(milliseconds=latency_ms)
                if started_at is not None
                else None
            )
            conn.execute(
                """
                INSERT INTO radar_ask_runs (
                    id, session_id, user_id, idempotency_key, question,
                    requested_depth, effective_depth, status, outcome, model,
                    available_at, created_at, started_at, completed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    session_id,
                    user_ids[("free", "vip", "admin").index(tier)],
                    f"admin-metrics-{run_id}",
                    f"{SECRET} {run_id}",
                    depth,
                    depth,
                    status,
                    outcome,
                    model,
                    created_at,
                    created_at,
                    started_at,
                    completed_at,
                    completed_at or created_at,
                ),
            )
            usage_date = created_at.astimezone(timezone(timedelta(hours=7))).date()
            conn.execute(
                """
                INSERT INTO radar_ask_usage (
                    id, run_key, user_id, tier, model, depth, usage_date, usage_month,
                    settlement_status, question_status, reserved_usd, actual_usd,
                    prompt_tokens, completion_tokens, cache_hit_tokens, cache_miss_tokens,
                    reservation_expires_at, outcome, created_at, updated_at, settled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4(),
                    run_id,
                    user_ids[("free", "vip", "admin").index(tier)],
                    tier,
                    model,
                    depth,
                    usage_date,
                    usage_date.replace(day=1),
                    settlement,
                    "answered" if outcome in {"answered", "insufficient"} else "reserved",
                    Decimal(reserved),
                    Decimal(actual),
                    prompt,
                    completion,
                    cache_hit,
                    cache_miss,
                    expires or NOW,
                    outcome,
                    created_at,
                    completed_at or created_at,
                    completed_at,
                ),
            )
            return run_id

        def seed_unreserved_run(
            *,
            tier: str,
            model: str | None,
            depth: str | None,
            status: str,
            outcome: str,
            age: timedelta,
            latency_ms: int,
        ):
            run_id = uuid4()
            run_ids.append(run_id)
            created_at = NOW - age
            started_at = created_at + timedelta(seconds=1)
            completed_at = started_at + timedelta(milliseconds=latency_ms)
            conn.execute(
                """
                INSERT INTO radar_ask_runs (
                    id, session_id, user_id, idempotency_key, question,
                    requested_depth, effective_depth, status, outcome, model,
                    available_at, created_at, started_at, completed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    session_id,
                    user_ids[("free", "vip", "admin").index(tier)],
                    f"admin-metrics-no-usage-{run_id}",
                    f"{SECRET} no usage {run_id}",
                    depth,
                    depth,
                    status,
                    outcome,
                    model,
                    created_at,
                    created_at,
                    started_at,
                    completed_at,
                    completed_at,
                ),
            )
            return run_id

        answered = seed_run(
            tier="free", model="deepseek-v4-flash", depth="fast",
            status="completed", outcome="answered", age=timedelta(hours=1),
            latency_ms=1000, actual="19.000000", prompt=100, completion=20,
            cache_hit=40, cache_miss=60,
        )
        seed_run(
            tier="vip", model="deepseek-v4-pro", depth="deep",
            status="failed", outcome="provider_failure", age=timedelta(hours=2),
            latency_ms=2000, actual="1.500000", prompt=200, completion=30,
            cache_hit=50, cache_miss=150,
        )
        seed_run(
            tier="admin", model="deepseek-v4-pro", depth="standard",
            status="insufficient", outcome="insufficient", age=timedelta(hours=3),
            latency_ms=3000, actual="0.500000", prompt=300, completion=40,
        )
        seed_run(
            tier="vip", model="private-model-name-do-not-expose", depth="standard",
            status="failed", outcome="validation_failure", age=timedelta(days=3),
            latency_ms=4000, actual="0.250000",
        )
        queued = seed_run(
            tier="admin", model="deepseek-v4-pro", depth="deep",
            status="queued", outcome=None, age=timedelta(minutes=10), latency_ms=None,
            actual="0.000000", reserved="2.000000", settlement="reserved",
            expires=NOW + timedelta(minutes=10),
        )
        no_usage_budget = seed_unreserved_run(
            tier="vip", model="deepseek-v4-pro", depth="deep",
            status="cancelled", outcome="budget_hard_stop", age=timedelta(hours=4),
            latency_ms=5000,
        )
        no_usage_validation = seed_unreserved_run(
            tier="free", model=None, depth=None,
            status="failed", outcome="validation_failure", age=timedelta(hours=5),
            latency_ms=6000,
        )

        message_id = uuid4()
        conn.execute(
            """
            INSERT INTO radar_ask_messages (id, session_id, run_id, role, content, created_at)
            VALUES (?, ?, ?, 'assistant', ?, ?)
            """,
            (message_id, session_id, answered, f"Secret answer {SECRET}", NOW - timedelta(minutes=30)),
        )
        conn.execute(
            """
            INSERT INTO radar_ask_feedback (id, message_id, user_id, rating, note, created_at)
            VALUES (?, ?, ?, 'helpful', ?, ?)
            """,
            (uuid4(), message_id, user_ids[0], f"Private note {SECRET}", NOW - timedelta(minutes=20)),
        )

    yield SimpleNamespace(
        run_ids=run_ids,
        user_ids=user_ids,
        queued=queued,
        no_usage_budget=no_usage_budget,
        no_usage_validation=no_usage_validation,
    )

    with get_conn() as conn:
        conn.execute("DELETE FROM radar_ask_usage WHERE run_key=ANY(?)", (run_ids,))
        conn.execute("DELETE FROM radar_ask_sessions WHERE user_id=ANY(?)", (user_ids,))
        conn.execute("DELETE FROM users WHERE id=ANY(?)", (user_ids,))
    connection.close_all()


def _settings() -> RadarAskSettings:
    return replace(
        RadarAskSettings.from_env(),
        monthly_warning_usd=Decimal("20"),
        monthly_hard_stop_usd=Decimal("50"),
    )


def _all_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _all_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_keys(child)


def test_repository_returns_bounded_aggregate_health_without_content_or_pii(aggregate_rows):
    metrics = RadarAskRepository().admin_metrics(now=NOW, settings=_settings())

    today = metrics["windows"]["today"]
    seven_days = metrics["windows"]["last_7_days"]
    assert today["questions"] == today["runs"] == 6
    assert today["by_tier"] == {"admin": 2, "free": 1, "unassigned": 2, "vip": 1}
    assert today["by_outcome"] == {
        "answered": 1,
        "budget_hard_stop": 1,
        "insufficient": 1,
        "pending": 1,
        "provider_failure": 1,
        "validation_failure": 1,
    }
    assert today["latency_ms"] == {"p50": 3000, "p95": 6000}
    assert today["rates"]["provider_failure"] == pytest.approx(1 / 5, abs=0.000001)
    assert today["rates"]["validation_failure"] == pytest.approx(1 / 5, abs=0.000001)
    assert today["rates"]["insufficient"] == pytest.approx(1 / 5, abs=0.000001)
    assert today["tokens"] == {"input": 600, "output": 90, "cache_hit": 90, "cache_miss": 210}
    assert today["feedback_by_question_cohort"] == {"helpful": 1, "not_helpful": 0}
    assert seven_days["by_model"] == {
        "deepseek-v4-flash": 1,
        "deepseek-v4-pro": 4,
        "other": 1,
        "unassigned": 1,
    }
    assert metrics["queue"]["depth"] == 1
    assert metrics["queue"]["oldest_age_seconds"] == 600
    assert metrics["cost"] == {
        "usage_month": "2026-08-01",
        "actual_usd": "21.250000",
        "reserved_usd": "2.000000",
        "projected_usd": "23.250000",
        "warning_usd": "20.000000",
        "hard_stop_usd": "50.000000",
        "state": "warning",
    }

    serialized = json.dumps(metrics, ensure_ascii=False, sort_keys=True)
    assert SECRET not in serialized
    assert "private-model-name-do-not-expose" not in serialized
    forbidden_keys = {
        "question", "answer", "evidence", "arguments", "results", "session_title",
        "phone", "url", "user_id", "email", "display_name", "note", "content",
    }
    assert forbidden_keys.isdisjoint(set(_all_keys(metrics)))


def test_pre_reservation_failures_without_usage_are_counted_operationally(aggregate_rows):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id,outcome FROM radar_ask_runs WHERE id=ANY(?) ORDER BY outcome",
            ([aggregate_rows.no_usage_budget, aggregate_rows.no_usage_validation],),
        ).fetchall()
        usage_count = conn.execute(
            "SELECT COUNT(*) AS total FROM radar_ask_usage WHERE run_key=ANY(?)",
            ([aggregate_rows.no_usage_budget, aggregate_rows.no_usage_validation],),
        ).fetchone()
    assert {row["outcome"] for row in rows} == {"budget_hard_stop", "validation_failure"}
    assert usage_count is not None and usage_count["total"] == 0

    metrics = RadarAskRepository().admin_metrics(now=NOW, settings=_settings())

    today = metrics["windows"]["today"]
    assert today["questions"] == 6
    assert today["by_outcome"]["budget_hard_stop"] == 1
    assert today["by_outcome"]["validation_failure"] == 1
    assert today["rates"]["validation_failure"] == pytest.approx(0.2)


def test_tier_breakdown_uses_immutable_usage_cohort_not_current_user_tier(aggregate_rows):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET tier='vip' WHERE id=?",
            (aggregate_rows.user_ids[0],),
        )
        usage = conn.execute(
            "SELECT tier FROM radar_ask_usage WHERE user_id=? ORDER BY created_at LIMIT 1",
            (aggregate_rows.user_ids[0],),
        ).fetchone()
    assert usage is not None and usage["tier"] == "free"

    metrics = RadarAskRepository().admin_metrics(now=NOW, settings=_settings())

    assert metrics["windows"]["today"]["questions"] == 6
    assert metrics["windows"]["today"]["by_tier"] == {
        "admin": 2,
        "free": 1,
        "unassigned": 2,
        "vip": 1,
    }


def test_arbitrary_configured_model_labels_are_bucketed_as_other(aggregate_rows):
    arbitrary = replace(
        _settings(),
        router_model="tenant-private-router-name",
        free_model="private-model-name-do-not-expose",
        smart_model="tenant-private-smart-name",
    )

    metrics = RadarAskRepository().admin_metrics(now=NOW, settings=arbitrary)

    assert metrics["windows"]["last_7_days"]["by_model"]["other"] == 1
    serialized = json.dumps(metrics, ensure_ascii=False, sort_keys=True)
    assert "private-model-name-do-not-expose" not in serialized
    assert "tenant-private-router-name" not in serialized
    assert "tenant-private-smart-name" not in serialized


def test_admin_endpoint_serializes_only_repository_aggregates(aggregate_rows, monkeypatch):
    import routes.admin_api as admin_routes

    class ClockedRepository:
        def admin_metrics(self, *, settings):
            return RadarAskRepository().admin_metrics(now=NOW, settings=settings)

    monkeypatch.setattr(radar_app, "current_tier", lambda: "admin")
    monkeypatch.setattr(admin_routes, "get_repository", lambda: ClockedRepository())
    response = radar_app.app.test_client().get("/admin/api/radar-ask/metrics")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["metrics"]["windows"]["today"]["questions"] == 6
    assert response.headers["Cache-Control"] == "private, no-store"
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert SECRET not in serialized
    assert "private-model-name-do-not-expose" not in serialized


def test_metric_queries_have_their_expected_supporting_indexes(aggregate_rows):
    expected = {
        "idx_radar_ask_usage_month",
        "radar_ask_usage_run_key_key",
        "radar_ask_runs_pkey",
        "idx_radar_ask_runs_created",
        "idx_radar_ask_runs_queue",
        "idx_radar_ask_messages_run_created",
        "idx_radar_ask_feedback_message",
    }
    with get_conn() as conn:
        indexes = {
            row["indexname"]
            for row in conn.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname='public'
                  AND tablename=ANY(?::text[])
                """,
                (["radar_ask_usage", "radar_ask_runs", "radar_ask_messages", "radar_ask_feedback"],),
            ).fetchall()
        }

    assert expected <= indexes


def test_cost_state_warns_at_canonical_twenty_dollars(aggregate_rows):
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_usage SET actual_usd=20, reserved_usd=0, settlement_status='settled' WHERE run_key=?",
            (aggregate_rows.run_ids[0],),
        )
        conn.execute(
            "UPDATE radar_ask_usage SET actual_usd=0, reserved_usd=0, settlement_status='settled' WHERE run_key<>ALL(?) AND usage_month=?",
            ([aggregate_rows.run_ids[0]], date(2026, 8, 1)),
        )

    metrics = RadarAskRepository().admin_metrics(now=NOW, settings=_settings())

    assert metrics["cost"]["projected_usd"] == "20.000000"
    assert metrics["cost"]["state"] == "warning"


def test_cost_state_locks_at_canonical_fifty_dollars(aggregate_rows):
    with get_conn() as conn:
        conn.execute(
            "UPDATE radar_ask_usage SET actual_usd=50, reserved_usd=0, settlement_status='settled' WHERE run_key=?",
            (aggregate_rows.run_ids[0],),
        )
        conn.execute(
            "UPDATE radar_ask_usage SET actual_usd=0, reserved_usd=0, settlement_status='settled' WHERE run_key<>ALL(?) AND usage_month=?",
            ([aggregate_rows.run_ids[0]], date(2026, 8, 1)),
        )

    metrics = RadarAskRepository().admin_metrics(now=NOW, settings=_settings())

    assert metrics["cost"]["projected_usd"] == "50.000000"
    assert metrics["cost"]["state"] == "hard_stop"


def test_last_seven_days_crosses_calendar_month_without_widening_month_bucket(aggregate_rows):
    august_run = aggregate_rows.run_ids[0]
    august_31 = datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc)
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE radar_ask_runs
            SET created_at=?,started_at=?,completed_at=?,updated_at=?
            WHERE id=?
            """,
            (august_31, august_31, august_31 + timedelta(seconds=1), august_31, august_run),
        )
        conn.execute(
            "UPDATE radar_ask_usage SET usage_date='2026-08-31',usage_month='2026-08-01' WHERE run_key=?",
            (august_run,),
        )

    metrics = RadarAskRepository().admin_metrics(
        now=datetime(2026, 9, 2, 6, 0, tzinfo=timezone.utc),
        settings=_settings(),
    )

    assert metrics["windows"]["last_7_days"]["questions"] == 1
    assert metrics["windows"]["month"]["questions"] == 0

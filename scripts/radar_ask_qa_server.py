"""Loopback-only Radar Ask QA server using the real backend and an offline provider.

The server refuses every database except ``radar_bds_test``. Authentication,
HTTP routes, orchestration, repositories, evidence SQL, quotas, and the Deep
worker are real. Only the paid model boundary is replaced with a deterministic
provider that never opens a network connection.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_urlsafe
from time import monotonic
from urllib.parse import quote, urlparse, urlunparse

import psycopg
from werkzeug.serving import run_simple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QA_PASSWORD = "radar-ask-local-qa-only"
QA_IDENTIFIER = "radar-ask-admin-000@example.test"
QA_CAPABILITY_HEADER = ("X-Radar-Ask-QA-Provider", "fake")


def _assert_test_database() -> tuple[str, str]:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL must point to radar_bds_test")
    with psycopg.connect(database_url, connect_timeout=3) as connection:
        database = str(connection.execute("SELECT current_database()").fetchone()[0])
    if database != "radar_bds_test":
        raise RuntimeError("QA server refuses any database except radar_bds_test")
    return database_url, database


def _read_role_url(database_url: str, password: str) -> str:
    parsed = urlparse(database_url)
    hostname = parsed.hostname or ""
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    netloc = f"radar_ask_ro:{quote(password, safe='')}@{host}"
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _seed_signal() -> None:
    from db.connection import get_conn

    now = datetime.now(timezone.utc)
    with get_conn() as connection:
        connection.execute(
            """
            INSERT INTO listings (
                source, source_id, url, title, area, price_ty, price_per_m2,
                area_m2, property_type, price_dropped, price_drop_pct,
                price_first_ty, price_updated_at, is_active, source_status,
                crawled_at, last_seen_at
            ) VALUES (
                'facebook', 'radar-ask-qa-signal',
                'https://example.test/radar-ask-qa-signal',
                'Radar Ask QA signal', 'Phu My', 1.85, 18.5,
                100, 'dat_nen', 1, 12.5, 2.1, ?, 1, 'active', ?, ?
            )
            ON CONFLICT (url) DO UPDATE SET
                price_dropped=1, price_drop_pct=12.5, price_updated_at=EXCLUDED.price_updated_at,
                is_active=1, source_status='active', last_seen_at=EXCLUDED.last_seen_at
            """,
            (now, now.isoformat(), now.isoformat()),
        )
        row = connection.execute(
            "SELECT id FROM listings WHERE url=?",
            ("https://example.test/radar-ask-qa-signal",),
        ).fetchone()
        if row is None:
            raise RuntimeError("failed to seed the QA signal")
        listing_id = int(row["id"])
        connection.execute(
            """
            INSERT INTO signal_card_read_model (
                listing_id, title, source, source_status, ward, property_type,
                area_m2, price_ty, listing_price_per_m2, actual_ppm2, fair_ppm2,
                mos_pct, signal_score, is_actionable, listing_is_signal,
                price_dropped, price_drop_pct, price_first_ty, activity_at,
                price_updated_at, publisher_visible_public, refreshed_at
            ) VALUES (
                ?, 'Radar Ask QA signal', 'facebook', 'active', 'Phu My', 'dat_nen',
                100, 1.85, 18.5, 18.5, 23.125,
                20, 80, TRUE, TRUE, TRUE, 12.5, 2.1, ?, ?, TRUE, ?
            )
            ON CONFLICT (listing_id) DO UPDATE SET
                is_actionable=TRUE, listing_is_signal=TRUE, price_dropped=TRUE,
                price_drop_pct=12.5, mos_pct=20, publisher_visible_public=TRUE,
                activity_at=EXCLUDED.activity_at,
                price_updated_at=EXCLUDED.price_updated_at,
                refreshed_at=EXCLUDED.refreshed_at
            """,
            (listing_id, now, now.isoformat(), now),
        )


def _configure_read_boundary(database_url: str) -> str:
    from scripts.configure_radar_ask_db_role import apply_configuration

    password = token_urlsafe(32)
    with psycopg.connect(database_url) as connection:
        apply_configuration(
            connection,
            password=password,
            phase="foundation",
            statement_timeout_ms=2_000,
        )
    role_url = _read_role_url(database_url, password)
    with psycopg.connect(role_url, connect_timeout=3) as connection:
        database = str(connection.execute("SELECT current_database()").fetchone()[0])
        connection.execute("SELECT 1 FROM public.radar_ask_v_signal_cards LIMIT 1")
    if database != "radar_bds_test":
        raise RuntimeError("read-only QA boundary is not connected to radar_bds_test")
    return role_url


def _seed_users(count: int) -> list[dict[str, str]]:
    from auth.core import hash_password
    from db.connection import get_conn
    from services.radar_ask.repository import RadarAskRepository

    password_hash = hash_password(QA_PASSWORD)
    repository = RadarAskRepository()
    users: list[dict[str, str]] = []
    for index in range(count):
        identifier = f"radar-ask-admin-{index:03d}@example.test"
        with get_conn() as connection:
            connection.execute(
                """
                INSERT INTO users (
                    identifier, identifier_type, email, password_hash,
                    display_name, tier, is_banned
                ) VALUES (?, 'email', ?, ?, 'Radar Ask QA', 'admin', 0)
                ON CONFLICT (identifier) DO UPDATE SET
                    password_hash=EXCLUDED.password_hash,
                    display_name=EXCLUDED.display_name,
                    tier='admin', is_banned=0
                """,
                (identifier, identifier, password_hash),
            )
            row = connection.execute(
                "SELECT id FROM users WHERE identifier=?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise RuntimeError("failed to seed a QA user")
            user_id = int(row["id"])
            connection.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
            connection.execute("DELETE FROM radar_ask_sessions WHERE user_id=?", (user_id,))
        seeded = repository.create_run(
            user_id=user_id,
            question="Seeded Radar Ask QA history",
            idempotency_key=f"qa-seed-{index:03d}",
            requested_depth="fast",
        )
        users.append(
            {
                "identifier": identifier,
                "password": QA_PASSWORD,
                "session_id": str(seeded.session_id),
                "run_id": str(seeded.id),
            }
        )
    return users


def _write_seed_file(path: Path, users: list[dict[str, str]]) -> None:
    resolved = path.resolve()
    local_root = (ROOT / ".local").resolve()
    try:
        resolved.relative_to(local_root)
    except ValueError as exc:
        raise RuntimeError("seed output must stay under ignored .local/") from exc
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(users, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, resolved)
    finally:
        temporary.unlink(missing_ok=True)


class OfflineQaProvider:
    """Deterministic model boundary for local QA; no HTTP client is constructed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0

    def complete(self, request):
        return self.complete_until(request, deadline=monotonic() + 30)

    def complete_until(self, request, *, deadline: float):
        from services.radar_ask.contracts import ProviderResponse, ProviderUsage

        if monotonic() >= deadline:
            raise TimeoutError("offline QA provider deadline expired")
        with self._lock:
            self.calls += 1
        system = request.messages[0].content or ""
        if "RouteDecision" in system:
            value = {
                "depth": "standard",
                "question_type": "qa_market_review",
                "tool_calls": [
                    {
                        "call_id": "qa-price-drop-ranking",
                        "name": "rank_price_drop_areas",
                        "arguments": {"window_days": 30, "limit": 10},
                    }
                ],
                "generated": False,
                "use_thinking": False,
                "needs_clarification": False,
                "clarification_question": None,
                "required_freshness_hours": 24,
            }
        else:
            raw = json.loads(request.messages[-1].content or "{}")
            bundles = raw.get("evidence") if isinstance(raw, dict) else []
            items = [
                item
                for bundle in (bundles if isinstance(bundles, list) else [])
                if isinstance(bundle, dict)
                for item in (bundle.get("items") or [])
                if isinstance(item, dict)
            ]
            as_of = max(
                (str(item.get("as_of")) for item in items if item.get("as_of")),
                default=datetime.now(timezone.utc).isoformat(),
            )
            dataset_version = str(items[0].get("dataset_version")) if items else "qa-backend:1"
            value = {
                "answered": False,
                "depth": str(raw.get("approved_depth") or "standard"),
                "verdict": "khong_du_du_lieu",
                "direct_answer": "Du lieu QA can duoc doi chieu them truoc khi ket luan.",
                "claims": [],
                "key_metrics": [],
                "risks": [],
                "confidence_reasons": [],
                "next_verification_steps": ["Kiem tra phap ly va vi tri thuc dia"],
                "source_cards": [],
                "suggested_followups": [],
                "as_of": as_of,
                "dataset_version": dataset_version[:120],
            }
        return ProviderResponse(
            json_value=value,
            usage=ProviderUsage(),
            finish_reason="stop",
        )


class CapabilityMiddleware:
    """Expose only fail-closed QA proof; every product route goes to Flask."""

    def __init__(self, application, provider: OfflineQaProvider) -> None:
        self.application = application
        self.provider = provider

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET").upper()
        if path != "/api/radar-ask/qa-capabilities" or method != "GET":
            return self.application(environ, start_response)
        payload = json.dumps(
            {
                "mode": "radar_ask_test",
                "provider": "fake",
                "database": "radar_bds_test",
                "backend_pipeline": "real",
                "live_provider_allowed": False,
                "provider_calls": self.provider.calls,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        start_response(
            "200 OK",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(payload))),
                ("Cache-Control", "private, no-store"),
                QA_CAPABILITY_HEADER,
            ],
        )
        return [payload]


def _build_dependencies(provider: OfflineQaProvider):
    from services.radar_ask.burst import get_burst_limiter
    from services.radar_ask.config import RadarAskSettings
    from services.radar_ask.limits import RadarAskLimitService
    from services.radar_ask.orchestrator import OrchestratorDependencies
    from services.radar_ask.planner import DeepSeekTypedPlanner
    from services.radar_ask.registry import DEFAULT_TOOL_REGISTRY
    from services.radar_ask.repository import RadarAskRepository
    from services.radar_ask.routing import route_question

    settings = RadarAskSettings.from_env()
    return OrchestratorDependencies(
        settings=settings,
        repository=RadarAskRepository(),
        limits=RadarAskLimitService(settings=settings),
        burst=get_burst_limiter(),
        router=route_question,
        registry=DEFAULT_TOOL_REGISTRY,
        provider=provider,
        clock=lambda: datetime.now(timezone.utc),
        planner=DeepSeekTypedPlanner(
            settings=settings,
            provider=provider,
            registry=DEFAULT_TOOL_REGISTRY,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5077)
    parser.add_argument("--seed-count", type=int, default=100)
    parser.add_argument(
        "--seed-output",
        type=Path,
        default=ROOT / ".local" / "radar-ask-load-users.json",
    )
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or not 4 <= args.seed_count <= 200:
        parser.error("port or seed-count is outside the safe QA range")

    database_url, database = _assert_test_database()
    if args.check_config:
        print(f"qa_server=ok database={database} provider=fake backend_pipeline=real")
        return 0

    os.environ.pop("DEEPSEEK_API_KEY", None)
    os.environ["RADAR_ASK_ENABLED"] = "1"
    os.environ["RADAR_ASK_ALLOWED_TIERS"] = "admin"
    os.environ["RADAR_ASK_DB_POOL_MAX"] = "4"
    os.environ["RADAR_ASK_DB_POOL_TIMEOUT_SECONDS"] = "2"
    os.environ["PUBLIC_BASE_URL"] = f"http://127.0.0.1:{args.port}"
    os.environ["DASHBOARD_BASE_URL"] = f"http://127.0.0.1:{args.port}"

    from db.schema import init_schema

    init_schema()
    _seed_signal()
    os.environ["RADAR_ASK_DATABASE_URL"] = _configure_read_boundary(database_url)
    users = _seed_users(args.seed_count)
    _write_seed_file(args.seed_output, users)

    import app as radar_app
    import services.radar_ask.service as ask_service
    from services.radar_ask.worker import RadarAskWorker

    provider = OfflineQaProvider()
    dependencies = _build_dependencies(provider)
    ask_service._dependencies = lambda: dependencies
    worker = RadarAskWorker(
        dependencies=dependencies,
        worker_id="radar-ask-local-qa",
        poll_seconds=0.05,
    )
    threading.Thread(
        target=worker.run_forever,
        name="radar-ask-local-qa-worker",
        daemon=True,
    ).start()
    print(
        f"qa_server=starting url=http://127.0.0.1:{args.port} "
        f"database={database} provider=fake backend_pipeline=real "
        f"seed_output={args.seed_output}"
    )
    run_simple(
        "127.0.0.1",
        args.port,
        CapabilityMiddleware(radar_app.app, provider),
        use_reloader=False,
        threaded=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

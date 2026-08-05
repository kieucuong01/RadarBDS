"""Loopback-only Radar Ask QA harness with fake APIs and a test-DB proof.

This process never constructs a DeepSeek provider. It renders the real Flask
page/static assets while intercepting auth and Radar Ask APIs in memory.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from werkzeug.serving import run_simple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QA_PASSWORD = "radar-ask-local-qa-only"
QA_IDENTIFIER = "radar-ask-admin-000@example.test"
QA_CAPABILITY_HEADER = ("X-Radar-Ask-QA-Provider", "fake")
TERMINAL_STATUSES = {"completed", "clarifying", "insufficient"}


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert_test_database() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL must point to radar_bds_test")
    with psycopg.connect(database_url, connect_timeout=3) as connection:
        database = str(connection.execute("SELECT current_database()").fetchone()[0])
    if database != "radar_bds_test":
        raise RuntimeError("QA harness refuses any database except radar_bds_test")
    return database


def _seed_users(count: int) -> list[dict[str, str]]:
    return [
        {
            "identifier": f"radar-ask-admin-{index:03d}@example.test",
            "password": QA_PASSWORD,
            "session_id": str(uuid4()),
            "run_id": str(uuid4()),
        }
        for index in range(count)
    ]


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


def _answer(depth: str) -> dict[str, object]:
    return {
        "answered": True,
        "depth": "deep" if depth == "deep" else "fast",
        "verdict": "can_kiem_tra_them",
        "direct_answer": (
            "Du lieu QA cho thay gia chao can duoc doi chieu them voi phap ly, "
            "quy hoach va vi tri thuc dia."
        ),
        "key_metrics": [
            {"label": "Gia chao", "value": 18.5, "unit": "trieu/m2"},
            {"label": "So tin so sanh", "value": 7, "unit": "tin"},
        ],
        "claims": [
            {
                "text": "Muc gia chao thap hon trung vi nhom so sanh QA.",
                "evidence_ids": ["qa-market-1"],
            }
        ],
        "favorable_thesis": "Gia chao co bien an toan trong mau QA.",
        "counter_thesis": "Mau QA khong thay the tham dinh phap ly.",
        "risks": ["Can kiem tra lo gioi", "Can doi chieu so hong"],
        "confidence": 0.82,
        "confidence_reasons": ["Co mau so sanh gia lap on dinh"],
        "next_checks": ["Kiem tra quy hoach", "Khao sat mat tien duong"],
        "source_cards": [
            {
                "evidence_id": "qa-market-1",
                "title": "Mau Radar Ask QA",
                "source_kind": "market_comparables",
                "as_of": _stamp(),
                "href": "/dashboard?tab=signals",
            }
        ],
        "as_of": _stamp(),
        "dataset_version": "qa-harness:1",
        "suggested_followups": ["Can kiem tra them du lieu nao?"],
    }


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sessions: list[dict[str, object]] = []
        self.messages: dict[str, list[dict[str, object]]] = {}
        self.runs: dict[str, dict[str, object]] = {}

    def create(self, question: str, depth: str) -> tuple[dict[str, object], int]:
        now = _stamp()
        session_id = str(uuid4())
        run_id = str(uuid4())
        answer = _answer(depth)
        session = {
            "id": session_id,
            "title": question[:80],
            "summary": {},
            "created_at": now,
            "updated_at": now,
        }
        messages = [
            {
                "id": str(uuid4()),
                "session_id": session_id,
                "role": "user",
                "content": question,
                "answer": None,
                "created_at": now,
            },
            {
                "id": str(uuid4()),
                "session_id": session_id,
                "role": "assistant",
                "content": answer["direct_answer"],
                "answer": answer,
                "created_at": now,
            },
        ]
        completed = {
            "run_id": run_id,
            "session_id": session_id,
            "status": "completed",
            "answer": answer,
            "retryable": False,
            "quota": {"tier": "admin", "limit": 100, "used": 1, "remaining": 99},
            "cost_state": {"state": "normal"},
        }
        with self.lock:
            self.sessions.insert(0, session)
            self.messages[session_id] = messages
            self.runs[run_id] = completed
        if depth == "deep":
            return {
                "run_id": run_id,
                "session_id": session_id,
                "status": "queued",
                "retryable": False,
                "quota": completed["quota"],
                "cost_state": completed["cost_state"],
            }, 202
        return completed, 200

    def session_payload(self, session_id: str) -> dict[str, object]:
        with self.lock:
            session = next(
                (item for item in self.sessions if item["id"] == session_id),
                None,
            )
            messages = list(self.messages.get(session_id, []))
        if session is None:
            now = _stamp()
            session = {
                "id": session_id,
                "title": "Seeded QA history",
                "summary": {},
                "created_at": now,
                "updated_at": now,
            }
            messages = []
        return {
            "session": session,
            "messages": messages,
            "message_limit": 100,
            "next_message_cursor": None,
        }

    def run_payload(self, run_id: str) -> dict[str, object]:
        with self.lock:
            run = self.runs.get(run_id)
        if run is not None:
            return run
        return {
            "run_id": run_id,
            "session_id": str(uuid4()),
            "status": "completed",
            "answer": _answer("deep"),
            "retryable": False,
            "quota": {"tier": "admin", "limit": 100, "used": 1, "remaining": 99},
            "cost_state": {"state": "normal"},
        }


STATE = _State()


def _response(start_response, payload: object, status: int = 200, *, qa=False):
    raw = b"" if status == 204 else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    labels = {200: "200 OK", 202: "202 Accepted", 204: "204 No Content", 400: "400 Bad Request"}
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(raw))),
        ("Cache-Control", "private, no-store"),
    ]
    if qa:
        headers.append(QA_CAPABILITY_HEADER)
    start_response(labels[status], headers)
    return [raw]


class QaMiddleware:
    def __init__(self, application, valid_identifiers: set[str]) -> None:
        self.application = application
        self.valid_identifiers = valid_identifiers

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET").upper()
        if path == "/api/radar-ask/qa-capabilities" and method == "GET":
            return _response(
                start_response,
                {
                    "mode": "radar_ask_test",
                    "provider": "fake",
                    "database": "radar_bds_test",
                    "live_provider_allowed": False,
                },
                qa=True,
            )
        if path == "/api/auth/login" and method == "POST":
            length = int(environ.get("CONTENT_LENGTH") or 0)
            payload = json.loads(environ["wsgi.input"].read(length) or b"{}")
            if payload.get("identifier") not in self.valid_identifiers or payload.get("password") != QA_PASSWORD:
                return _response(start_response, {"ok": False, "error": "invalid_credentials"}, 400)
            return _response(
                start_response,
                {"ok": True, "user": {"id": 9001, "tier": "admin", "name": "Radar Ask QA"}},
            )
        if not path.startswith("/api/radar-ask/"):
            return self.application(environ, start_response)
        if path == "/api/radar-ask/questions" and method == "POST":
            length = int(environ.get("CONTENT_LENGTH") or 0)
            payload = json.loads(environ["wsgi.input"].read(length) or b"{}")
            result, status = STATE.create(
                str(payload.get("question") or "Radar Ask QA"),
                str(payload.get("requested_depth") or "fast"),
            )
            return _response(start_response, result, status)
        if path == "/api/radar-ask/sessions" and method == "GET":
            with STATE.lock:
                sessions = list(STATE.sessions[:50])
            return _response(
                start_response,
                {"sessions": sessions, "limit": 50, "next_cursor": None},
            )
        if path.startswith("/api/radar-ask/runs/") and method == "GET":
            run_id = path.rsplit("/", 1)[-1]
            try:
                UUID(run_id)
            except ValueError:
                return _response(start_response, {"error": {"code": "not_found"}}, 400)
            return _response(start_response, STATE.run_payload(run_id))
        if path.startswith("/api/radar-ask/sessions/"):
            session_id = path.rsplit("/", 1)[-1]
            if method == "DELETE":
                with STATE.lock:
                    STATE.sessions = [item for item in STATE.sessions if item["id"] != session_id]
                    STATE.messages.pop(session_id, None)
                return _response(start_response, {}, 204)
            if method == "GET":
                return _response(start_response, STATE.session_payload(session_id))
        return _response(start_response, {"error": {"code": "not_found"}}, 400)


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

    database = _assert_test_database()
    users = _seed_users(args.seed_count)
    if args.check_config:
        print(f"qa_harness=ok database={database} provider=fake seed_count={len(users)}")
        return 0

    _write_seed_file(args.seed_output, users)
    os.environ.pop("DEEPSEEK_API_KEY", None)
    os.environ["RADAR_ASK_ENABLED"] = "1"
    os.environ["RADAR_ASK_ALLOWED_TIERS"] = "admin"
    import app as radar_app
    import routes.public as public_routes

    qa_user = {"id": 9001, "tier": "admin", "name": "Radar Ask QA"}
    public_routes.feature_enabled = lambda: True
    public_routes.tier_allowed = lambda _tier: True
    public_routes.current_user = lambda: qa_user
    public_routes.current_tier = lambda: "admin"
    valid_identifiers = {user["identifier"] for user in users}
    print(
        f"qa_harness=starting url=http://127.0.0.1:{args.port} "
        f"database={database} provider=fake seed_output={args.seed_output}"
    )
    run_simple(
        "127.0.0.1",
        args.port,
        QaMiddleware(radar_app.app, valid_identifiers),
        use_reloader=False,
        threaded=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest


class RecordingConnection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return RecordingCursor(self.rows.pop(0) if self.rows else [])


class RecordingCursor:
    def __init__(self, rows):
        self.rows = rows if isinstance(rows, list) else [rows]
        self.rowcount = len(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


@contextmanager
def connection_factory(connection):
    yield connection


def sample_job(job_id="job-a"):
    return {
        "id": job_id,
        "kind": "facebook_crawl",
        "status": "queued",
        "stage": "queued",
        "mode": "daily",
        "profile_url": "https://www.facebook.com/broker-a",
        "source": "facebook",
        "broker_name": "Broker A",
        "limit": 30,
        "days": 7,
        "download_images": False,
        "maintenance_action": "",
        "progress_pct": 0,
        "progress_label": "Đang chờ chạy",
        "stats": {},
        "logs": [],
        "context": {"city": "Thủ Dầu Một"},
        "created_by": "admin:test",
    }


def persisted_row(job_id="job-a", **overrides):
    row = {
        "id": job_id,
        "kind": "facebook_crawl",
        "status": "queued",
        "stage": "queued",
        "mode": "daily",
        "profile_url": "https://www.facebook.com/broker-a",
        "source": "facebook",
        "broker_name": "Broker A",
        "item_limit": 30,
        "days": 7,
        "download_images": False,
        "maintenance_action": "",
        "progress_pct": 0,
        "progress_label": "Đang chờ chạy",
        "stats": {},
        "logs": [],
        "error": None,
        "context": {"city": "Thủ Dầu Một"},
        "created_by": "admin:test",
        "created_at": datetime(2026, 7, 30, tzinfo=timezone.utc),
        "started_at": None,
        "heartbeat_at": None,
        "finished_at": None,
    }
    row.update(overrides)
    return row


def test_admin_job_migration_is_idempotent_and_enforces_one_active_job():
    from db.schema import _migrate_admin_jobs

    connection = RecordingConnection()
    _migrate_admin_jobs(connection)
    _migrate_admin_jobs(connection)

    ddl = "\n".join(sql for sql, _params in connection.executed)
    assert ddl.count("CREATE TABLE IF NOT EXISTS admin_jobs") == 2
    compact_ddl = " ".join(ddl.split())
    assert "CHECK (status IN ( 'queued', 'running', 'succeeded', 'failed' ))" in compact_ddl
    assert "stats JSONB NOT NULL DEFAULT '{}'::jsonb" in ddl
    assert "logs JSONB NOT NULL DEFAULT '[]'::jsonb" in ddl
    assert "heartbeat_at TIMESTAMPTZ" in ddl
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_jobs_one_active" in ddl
    assert "WHERE status IN ('queued', 'running')" in ddl
    assert "DROP TABLE" not in ddl.upper()
    assert "TRUNCATE" not in ddl.upper()


def test_create_admin_job_locks_reconciles_and_commits_before_returning():
    from db.admin_jobs import create_admin_job

    row = persisted_row()
    connection = RecordingConnection(rows=[[], [], [], row])

    created = create_admin_job(
        sample_job(),
        conn_factory=lambda: connection_factory(connection),
        now=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    assert created["id"] == "job-a"
    assert created["limit"] == 30
    sql = [statement for statement, _params in connection.executed]
    assert "pg_advisory_xact_lock" in sql[0]
    assert "UPDATE admin_jobs" in sql[1]
    assert "status IN ('queued', 'running')" in sql[2]
    assert "INSERT INTO admin_jobs" in sql[3]


def test_create_admin_job_returns_existing_active_job_without_inserting():
    from db.admin_jobs import AdminJobAlreadyActive, create_admin_job

    active = persisted_row("job-active", status="running")
    connection = RecordingConnection(rows=[[], [], active])

    with pytest.raises(AdminJobAlreadyActive) as caught:
        create_admin_job(
            sample_job("job-new"),
            conn_factory=lambda: connection_factory(connection),
            now=datetime(2026, 7, 30, tzinfo=timezone.utc),
        )

    assert caught.value.active_job["id"] == "job-active"
    assert not any("INSERT INTO admin_jobs" in sql for sql, _params in connection.executed)


def test_append_admin_job_log_uses_postgres_bounded_json_update():
    from db.admin_jobs import append_admin_job_log

    connection = RecordingConnection(rows=[persisted_row(logs=["newest"])])
    updated = append_admin_job_log(
        "job-a",
        "newest",
        conn_factory=lambda: connection_factory(connection),
        now=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    sql, params = connection.executed[0]
    assert "jsonb_array_elements" in sql
    assert "OFFSET GREATEST" in sql
    assert "200" in sql
    assert params[0] == "2026-07-30T00:00:00Z newest"
    assert updated["logs"] == ["newest"]


def test_reconcile_stale_jobs_uses_heartbeat_cutoff_and_safe_error():
    from db.admin_jobs import STALE_JOB_ERROR, reconcile_stale_admin_jobs

    connection = RecordingConnection(rows=[])
    now = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)
    reconcile_stale_admin_jobs(
        conn_factory=lambda: connection_factory(connection),
        now=now,
        stale_after_seconds=120,
    )

    sql, params = connection.executed[0]
    assert "COALESCE(heartbeat_at, started_at, created_at) < ?" in sql
    assert "status IN ('queued', 'running')" in sql
    assert STALE_JOB_ERROR in params
    assert now - timedelta(seconds=120) in params


def test_public_job_row_excludes_internal_context_and_creator():
    from db.admin_jobs import row_to_admin_job

    job = row_to_admin_job(persisted_row())

    assert job["limit"] == 30
    assert job["context"] == {"city": "Thủ Dầu Một"}
    assert job["created_by"] == "admin:test"
    assert job["created_at"] == "2026-07-30T00:00:00Z"


class InMemoryAdminJobRepository:
    def __init__(self):
        self.jobs = {}
        self.events = []

    def create(self, job):
        self.events.append(("create", job["id"]))
        self.jobs[job["id"]] = dict(job)
        return dict(self.jobs[job["id"]])

    def get(self, job_id):
        value = self.jobs.get(job_id)
        return dict(value) if value else None

    def update(self, job_id, changes):
        self.events.append(("update", job_id, dict(changes)))
        self.jobs[job_id].update(changes)
        return dict(self.jobs[job_id])

    def append_log(self, job_id, message):
        self.events.append(("log", job_id, message))
        self.jobs[job_id].setdefault("logs", []).append(message)
        self.jobs[job_id]["logs"] = self.jobs[job_id]["logs"][-200:]
        return dict(self.jobs[job_id])

    def heartbeat(self, job_id):
        self.events.append(("heartbeat", job_id))


class DeferredThread:
    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True
        self.target()


def test_enqueue_persists_job_before_starting_runner_thread():
    from services.admin_jobs import enqueue_admin_job

    repository = InMemoryAdminJobRepository()
    events = repository.events

    def runner(job_id):
        events.append(("runner", job_id))

    created = enqueue_admin_job(
        sample_job(),
        runner,
        repository=repository,
        thread_factory=DeferredThread,
    )

    assert created["id"] == "job-a"
    assert events[:2] == [("create", "job-a"), ("runner", "job-a")]


def test_reporter_updates_shared_state_and_public_payload_is_allowlisted():
    from services.admin_jobs import AdminJobReporter, public_admin_job

    repository = InMemoryAdminJobRepository()
    repository.create(sample_job())
    reporter = AdminJobReporter("job-a", repository=repository, heartbeat_interval=3600)

    reporter.start("crawl", "Đang gọi Apify")
    reporter.progress(35, "crawl", "Đã lấy dữ liệu từ Facebook")
    reporter.log("fetched=12 imported=3")
    reporter.succeed({"crawl": {"fetched": 12}})

    public = public_admin_job(repository.get("job-a"))
    assert public["status"] == "succeeded"
    assert public["progress_pct"] == 100
    assert public["stats"] == {"crawl": {"fetched": 12}}
    assert "context" not in public
    assert "created_by" not in public
    assert "heartbeat_at" not in public


def test_reporter_failure_never_persists_secret_exception_text():
    from services.admin_jobs import AdminJobReporter, SAFE_JOB_ERROR

    repository = InMemoryAdminJobRepository()
    repository.create(sample_job())
    reporter = AdminJobReporter("job-a", repository=repository, heartbeat_interval=3600)

    reporter.start("crawl", "Đang chạy")
    reporter.fail(RuntimeError("request failed token=secret-value"))

    stored = repository.get("job-a")
    assert stored["error"] == SAFE_JOB_ERROR
    assert "secret-value" not in str(stored)

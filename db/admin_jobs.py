"""PostgreSQL repository for worker-safe admin asynchronous job state."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from db.connection import get_conn

ACTIVE_STATUSES = frozenset({"queued", "running"})
TERMINAL_STATUSES = frozenset({"succeeded", "failed"})
JOB_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
JOB_KINDS = frozenset({
    "facebook_crawl",
    "crawl_maintenance",
    "missing_image_backfill",
    "source_retry",
})
STALE_JOB_ERROR = "Job dừng vì tiến trình máy chủ không còn hoạt động."
_ACTIVE_LOCK_NAME = "radar-admin-jobs-active"
_MAX_LOG_ENTRIES = 200


class AdminJobAlreadyActive(RuntimeError):
    """Raised when another queued/running admin job owns the shared slot."""

    def __init__(self, active_job: dict):
        super().__init__("An admin job is already queued or running")
        self.active_job = active_job


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(value: Any) -> Any:
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback
    return value


def row_to_admin_job(row: Any | None) -> dict | None:
    """Convert PgRow/dict storage fields to the existing job payload shape."""
    if row is None:
        return None
    values = dict(row.items()) if hasattr(row, "items") else dict(row)
    return {
        "id": values.get("id"),
        "kind": values.get("kind"),
        "status": values.get("status"),
        "stage": values.get("stage"),
        "mode": values.get("mode"),
        "profile_url": values.get("profile_url"),
        "source": values.get("source"),
        "broker_name": values.get("broker_name"),
        "limit": values.get("item_limit"),
        "days": values.get("days"),
        "download_images": bool(values.get("download_images")),
        "maintenance_action": values.get("maintenance_action"),
        "progress_pct": int(values.get("progress_pct") or 0),
        "progress_label": values.get("progress_label"),
        "stats": _json_value(values.get("stats"), {}),
        "logs": _json_value(values.get("logs"), []),
        "error": values.get("error"),
        "context": _json_value(values.get("context"), {}),
        "created_by": values.get("created_by"),
        "created_at": _iso_z(values.get("created_at")),
        "started_at": _iso_z(values.get("started_at")),
        "heartbeat_at": _iso_z(values.get("heartbeat_at")),
        "finished_at": _iso_z(values.get("finished_at")),
    }


def _reconcile_stale_with_conn(
    conn,
    *,
    now: datetime,
    stale_after_seconds: int,
) -> int:
    cutoff = now - timedelta(seconds=max(1, int(stale_after_seconds)))
    cursor = conn.execute(
        """
        UPDATE admin_jobs
        SET status = 'failed',
            stage = 'failed',
            progress_label = ?,
            error = ?,
            finished_at = ?
        WHERE status IN ('queued', 'running')
          AND COALESCE(heartbeat_at, started_at, created_at) < ?
        """,
        (STALE_JOB_ERROR, STALE_JOB_ERROR, now, cutoff),
    )
    return max(0, int(getattr(cursor, "rowcount", 0) or 0))


def reconcile_stale_admin_jobs(
    *,
    conn_factory: Callable = get_conn,
    now: datetime | None = None,
    stale_after_seconds: int = 120,
) -> int:
    with conn_factory() as conn:
        return _reconcile_stale_with_conn(
            conn,
            now=now or _utc_now(),
            stale_after_seconds=stale_after_seconds,
        )


def create_admin_job(
    job: dict,
    *,
    conn_factory: Callable = get_conn,
    now: datetime | None = None,
) -> dict:
    """Atomically claim the single active-job slot and persist the job."""
    current_time = now or _utc_now()
    kind = str(job.get("kind") or "")
    status = str(job.get("status") or "queued")
    if kind not in JOB_KINDS:
        raise ValueError("invalid admin job kind")
    if status not in JOB_STATUSES:
        raise ValueError("invalid admin job status")
    with conn_factory() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(?))",
            (_ACTIVE_LOCK_NAME,),
        )
        _reconcile_stale_with_conn(conn, now=current_time, stale_after_seconds=120)
        active_row = conn.execute(
            """
            SELECT *
            FROM admin_jobs
            WHERE status IN ('queued', 'running')
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if active_row:
            raise AdminJobAlreadyActive(row_to_admin_job(active_row))
        inserted = conn.execute(
            """
            INSERT INTO admin_jobs (
                id, kind, status, stage, mode, profile_url, source,
                broker_name, item_limit, days, download_images,
                maintenance_action, progress_pct, progress_label,
                stats, logs, error, context, created_by, created_at,
                started_at, heartbeat_at, finished_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?::jsonb, ?::jsonb, ?, ?::jsonb, ?, ?, ?, ?, ?
            )
            RETURNING *
            """,
            (
                str(job.get("id") or ""),
                kind,
                status,
                str(job.get("stage") or "queued"),
                str(job.get("mode") or ""),
                str(job.get("profile_url") or ""),
                str(job.get("source") or ""),
                str(job.get("broker_name") or ""),
                job.get("limit"),
                job.get("days"),
                bool(job.get("download_images")),
                str(job.get("maintenance_action") or ""),
                max(0, min(100, int(job.get("progress_pct") or 0))),
                str(job.get("progress_label") or ""),
                json.dumps(job.get("stats") or {}, ensure_ascii=False),
                json.dumps(job.get("logs") or [], ensure_ascii=False),
                job.get("error"),
                json.dumps(job.get("context") or {}, ensure_ascii=False),
                str(job.get("created_by") or ""),
                current_time,
                job.get("started_at"),
                job.get("heartbeat_at"),
                job.get("finished_at"),
            ),
        ).fetchone()
    return row_to_admin_job(inserted)


def get_admin_job(job_id: str, *, conn_factory: Callable = get_conn) -> dict | None:
    with conn_factory() as conn:
        row = conn.execute(
            "SELECT * FROM admin_jobs WHERE id = ?",
            (str(job_id),),
        ).fetchone()
    return row_to_admin_job(row)


def list_admin_jobs(limit: int = 20, *, conn_factory: Callable = get_conn) -> list[dict]:
    safe_limit = max(1, min(100, int(limit or 20)))
    with conn_factory() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM admin_jobs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [row_to_admin_job(row) for row in rows]


def get_active_admin_job(*, conn_factory: Callable = get_conn) -> dict | None:
    with conn_factory() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM admin_jobs
            WHERE status IN ('queued', 'running')
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    return row_to_admin_job(row)


_UPDATE_COLUMNS = {
    "status": "status",
    "stage": "stage",
    "mode": "mode",
    "profile_url": "profile_url",
    "source": "source",
    "broker_name": "broker_name",
    "limit": "item_limit",
    "days": "days",
    "download_images": "download_images",
    "maintenance_action": "maintenance_action",
    "progress_pct": "progress_pct",
    "progress_label": "progress_label",
    "stats": "stats",
    "error": "error",
    "context": "context",
    "started_at": "started_at",
    "heartbeat_at": "heartbeat_at",
    "finished_at": "finished_at",
}


def update_admin_job(
    job_id: str,
    changes: dict,
    *,
    conn_factory: Callable = get_conn,
) -> dict:
    assignments = []
    params = []
    for key, value in changes.items():
        column = _UPDATE_COLUMNS.get(key)
        if not column:
            continue
        if key in {"stats", "context"}:
            assignments.append(f"{column} = ?::jsonb")
            params.append(json.dumps(value or {}, ensure_ascii=False))
        else:
            assignments.append(f"{column} = ?")
            params.append(value)
    if not assignments:
        current = get_admin_job(job_id, conn_factory=conn_factory)
        if current is None:
            raise KeyError(job_id)
        return current
    params.append(str(job_id))
    with conn_factory() as conn:
        row = conn.execute(
            f"""
            UPDATE admin_jobs
            SET {", ".join(assignments)}
            WHERE id = ?
            RETURNING *
            """,
            tuple(params),
        ).fetchone()
    if row is None:
        raise KeyError(job_id)
    return row_to_admin_job(row)


def append_admin_job_log(
    job_id: str,
    message: str,
    *,
    conn_factory: Callable = get_conn,
    now: datetime | None = None,
) -> dict:
    timestamp = _iso_z(now or _utc_now())
    entry = f"{timestamp} {str(message or '')[:1000]}"
    with conn_factory() as conn:
        row = conn.execute(
            """
            UPDATE admin_jobs
            SET logs = (
                SELECT COALESCE(jsonb_agg(value ORDER BY ordinal), '[]'::jsonb)
                FROM (
                    SELECT value, ordinal
                    FROM jsonb_array_elements(
                        COALESCE(logs, '[]'::jsonb)
                        || jsonb_build_array(to_jsonb(?::text))
                    ) WITH ORDINALITY AS entries(value, ordinal)
                    OFFSET GREATEST(
                        jsonb_array_length(COALESCE(logs, '[]'::jsonb)) + 1 - 200,
                        0
                    )
                ) bounded
            )
            WHERE id = ?
            RETURNING *
            """,
            (entry, str(job_id)),
        ).fetchone()
    if row is None:
        raise KeyError(job_id)
    return row_to_admin_job(row)


def heartbeat_admin_job(
    job_id: str,
    *,
    conn_factory: Callable = get_conn,
    now: datetime | None = None,
) -> None:
    with conn_factory() as conn:
        cursor = conn.execute(
            """
            UPDATE admin_jobs
            SET heartbeat_at = ?
            WHERE id = ? AND status IN ('queued', 'running')
            """,
            (now or _utc_now(), str(job_id)),
        )
    if int(getattr(cursor, "rowcount", 0) or 0) == 0:
        return

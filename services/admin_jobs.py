"""Service boundary for persisted admin jobs and local runner coordination."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from db import admin_jobs as admin_job_db

logger = logging.getLogger(__name__)

SAFE_JOB_ERROR = "Tác vụ thất bại. Xem log máy chủ để kiểm tra chi tiết."
_PUBLIC_FIELDS = (
    "id",
    "status",
    "stage",
    "mode",
    "profile_url",
    "source",
    "broker_name",
    "limit",
    "days",
    "download_images",
    "maintenance_action",
    "started_at",
    "finished_at",
    "progress_pct",
    "progress_label",
    "stats",
    "error",
    "logs",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresAdminJobRepository:
    """Object adapter that keeps service code independent of SQL functions."""

    def create(self, job: dict) -> dict:
        return admin_job_db.create_admin_job(job)

    def get(self, job_id: str) -> dict | None:
        return admin_job_db.get_admin_job(job_id)

    def list(self, limit: int = 20) -> list[dict]:
        return admin_job_db.list_admin_jobs(limit=limit)

    def active(self) -> dict | None:
        return admin_job_db.get_active_admin_job()

    def update(self, job_id: str, changes: dict) -> dict:
        return admin_job_db.update_admin_job(job_id, changes)

    def append_log(self, job_id: str, message: str) -> dict:
        return admin_job_db.append_admin_job_log(job_id, message)

    def heartbeat(self, job_id: str) -> None:
        admin_job_db.heartbeat_admin_job(job_id)

    def reconcile_stale(self) -> int:
        return admin_job_db.reconcile_stale_admin_jobs()


POSTGRES_ADMIN_JOBS = PostgresAdminJobRepository()


def public_admin_job(job: dict | None) -> dict | None:
    """Return only the compatibility fields safe for Admin JSON responses."""
    if not job:
        return None
    public = {field: job.get(field) for field in _PUBLIC_FIELDS}
    public["progress_pct"] = max(0, min(100, int(public.get("progress_pct") or 0)))
    public["progress_label"] = public.get("progress_label") or public.get("stage")
    public["stats"] = public.get("stats") if isinstance(public.get("stats"), dict) else {}
    public["logs"] = public.get("logs") if isinstance(public.get("logs"), list) else []
    public["logs"] = public["logs"][-200:]
    if public.get("error"):
        public["error"] = str(public["error"])[:300]
    return public


def enqueue_admin_job(
    job: dict,
    target: Callable[[str], None],
    *,
    repository=None,
    thread_factory=None,
) -> dict:
    """Persist the active slot before any local daemon thread can execute."""
    repository = repository or POSTGRES_ADMIN_JOBS
    thread_factory = thread_factory or threading.Thread
    created = repository.create(job)

    def run_and_log_failure() -> None:
        try:
            target(created["id"])
        except Exception as exc:  # runner normally owns terminal state
            logger.error("Unhandled admin job runner failure: %s", type(exc).__name__)
            current = repository.get(created["id"])
            if current and current.get("status") in {"queued", "running"}:
                repository.update(
                    created["id"],
                    {
                        "status": "failed",
                        "stage": "failed",
                        "progress_label": SAFE_JOB_ERROR,
                        "error": SAFE_JOB_ERROR,
                        "finished_at": _utc_now(),
                    },
                )

    thread = thread_factory(target=run_and_log_failure, daemon=True)
    thread.start()
    return created


class AdminJobReporter:
    """Write runner progress through the shared repository with heartbeats."""

    def __init__(
        self,
        job_id: str,
        *,
        repository=None,
        heartbeat_interval: float = 15.0,
    ):
        self.job_id = str(job_id)
        self.repository = repository or POSTGRES_ADMIN_JOBS
        self.heartbeat_interval = max(1.0, float(heartbeat_interval))
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def start(self, stage: str, label: str) -> dict:
        now = _utc_now()
        job = self.repository.update(
            self.job_id,
            {
                "status": "running",
                "stage": str(stage or "running"),
                "progress_pct": 3,
                "progress_label": str(label or "Đang chạy"),
                "started_at": now,
                "heartbeat_at": now,
            },
        )
        self._start_heartbeat()
        return job

    def _start_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        def loop() -> None:
            while not self._heartbeat_stop.wait(self.heartbeat_interval):
                try:
                    self.repository.heartbeat(self.job_id)
                except Exception as exc:
                    logger.warning(
                        "Admin job heartbeat failed for %s: %s",
                        self.job_id,
                        type(exc).__name__,
                    )

        self._heartbeat_thread = threading.Thread(target=loop, daemon=True)
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()

    def progress(self, pct: int, stage: str | None = None, label: str | None = None) -> dict:
        changes = {"progress_pct": max(0, min(100, int(pct or 0)))}
        if stage:
            changes["stage"] = str(stage)
        if label:
            changes["progress_label"] = str(label)
        return self.repository.update(self.job_id, changes)

    def log(self, message: str) -> dict:
        return self.repository.append_log(self.job_id, str(message or "")[:1000])

    def succeed(self, stats: dict | None = None) -> dict:
        self.stop_heartbeat()
        return self.repository.update(
            self.job_id,
            {
                "status": "succeeded",
                "stage": "done",
                "progress_pct": 100,
                "progress_label": "Hoàn tất",
                "stats": stats or {},
                "error": None,
                "finished_at": _utc_now(),
            },
        )

    def fail(self, exc: Exception, *, public_message: str | None = None) -> dict:
        self.stop_heartbeat()
        logger.error(
            "Admin job %s failed with %s",
            self.job_id,
            type(exc).__name__,
        )
        safe_message = str(public_message or SAFE_JOB_ERROR)[:300]
        return self.repository.update(
            self.job_id,
            {
                "status": "failed",
                "stage": "failed",
                "progress_label": safe_message,
                "error": safe_message,
                "finished_at": _utc_now(),
            },
        )

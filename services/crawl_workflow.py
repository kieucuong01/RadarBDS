"""Whole-job status and timings, separate from per-source crawl_runs rows."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
import sys
import time

logger = logging.getLogger(__name__)
STATUS_DIR = Path(__file__).resolve().parent.parent / "logs"
_active = ContextVar("crawl_workflow", default=None)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(source):
    if source not in {"facebook", "guland", "all"}:
        raise ValueError("Unsupported crawl workflow source")
    return STATUS_DIR / f"crawl-workflow-{source}.json"


def _save(state):
    path = _path(state["source"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def load_workflow_status(source):
    try:
        return json.loads(_path(source).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _alert(message):
    from alerts.ops import send_ops_alert
    try:
        delivered = send_ops_alert(message)
        logger.warning("Workflow OPS alert delivered=%s", delivered)
    except Exception:
        logger.exception("Workflow OPS alert failed")


def mark_partial(reason):
    state = _active.get()
    if state is not None:
        state["status"] = "partial"
        state["warnings"].append(reason)
        _save(state)


@contextmanager
def timed_stage(name):
    state = _active.get()
    previous = state.get("stage") if state else None
    started = time.monotonic()
    if state is not None:
        state["stage"] = name
        _save(state)
    try:
        yield
    finally:
        elapsed = round(time.monotonic() - started, 3)
        logger.info("[crawl-stage] %s seconds=%.3f", name, elapsed)
        if state is not None:
            state["timings"].append({"stage": name, "seconds": elapsed})
            # Preserve the failing stage for the job error report.
            if sys.exc_info()[0] is None:
                state["stage"] = previous
            _save(state)


@contextmanager
def crawl_workflow(source):
    previous = load_workflow_status(source)
    if previous and previous.get("status") == "running":
        _alert(f"Crawl {source}: lần trước bị gián đoạn ở bước {previous.get('stage') or 'unknown'}.")
    state = {"source": source, "pid": os.getpid(), "started_at": _now(),
             "finished_at": None, "status": "running", "stage": "startup",
             "timings": [], "warnings": []}
    _save(state)
    token = _active.set(state)
    old_handler = signal.getsignal(signal.SIGTERM)

    def terminated(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminated)
    try:
        yield state
    except BaseException as exc:
        state["status"] = "error"
        state["error_type"] = type(exc).__name__
        _alert(f"Crawl {source} thất bại ở bước {state['stage']}: {type(exc).__name__}. Xem logs/crawl-daily.log.")
        raise
    else:
        if state["status"] == "running":
            state["status"] = "done"
        elif state["status"] == "partial":
            _alert(f"Crawl {source} hoàn tất một phần: " + "; ".join(state["warnings"]))
        state["stage"] = "finished"
    finally:
        state["finished_at"] = _now()
        _save(state)
        signal.signal(signal.SIGTERM, old_handler)
        _active.reset(token)


def record_service_result(source, result):
    """ExecStopPost also catches SIGKILL/OOM, which Python cannot handle."""
    if result == "success":
        return
    state = load_workflow_status(source) or {"source": source, "stage": "service"}
    if result == "exit-code" and os.getenv("EXIT_STATUS") == "2" and state.get("status") == "partial":
        state["service_result"] = result
        _save(state)
        return
    state.update(status="error", service_result=result, finished_at=_now())
    _save(state)
    _alert(f"systemd crawl {source}: {result}; bước {state.get('stage')}. Xem logs/crawl-daily.log.")


if __name__ == "__main__":
    import argparse
    import config.settings  # load the usual ignored env overrides
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=["facebook", "guland"])
    args = parser.parse_args()
    record_service_result(args.source, os.getenv("SERVICE_RESULT", "unknown"))

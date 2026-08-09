"""Safe rendering and exit classification for the data trust audit."""
from __future__ import annotations

from datetime import datetime, timezone
import json

from services.data_trust_audit import run_data_trust_audit


def _unverified_report() -> dict[str, object]:
    return {
        "overall_status": "unverified",
        "reason": "audit_execution_error",
        "target": {"scheme": "", "host": "", "port": None, "database": ""},
        "generated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "duration_ms": 0,
        "deep": False,
        "limit": 0,
        "checks": [],
    }


def _exit_code(report: dict[str, object]) -> int:
    overall = str(report.get("overall_status") or "").lower()
    checks = report.get("checks")
    if not isinstance(checks, list):
        return 2
    if any(not isinstance(check, dict) for check in checks):
        return 2
    statuses = {
        str(check.get("status") or "").lower()
        for check in checks
    }
    if overall == "unverified" or "unverified" in statuses:
        return 2
    if overall not in {"pass", "warn", "fail"}:
        return 2
    if any(status not in {"pass", "warn", "fail", "skipped"} for status in statuses):
        return 2
    if overall == "fail" or "fail" in statuses:
        return 1
    return 0


def _text_value(value) -> str:
    if value is None:
        return "none"
    return str(value).replace("\r", "").replace("\n", "")[:256]


def _render_text(report: dict[str, object]) -> None:
    print(
        "data_trust "
        f"overall={_text_value(report.get('overall_status'))} "
        f"reason={_text_value(report.get('reason', 'none'))} "
        f"generated_at={_text_value(report.get('generated_at'))} "
        f"duration_ms={_text_value(report.get('duration_ms'))} "
        f"deep={str(bool(report.get('deep'))).lower()} "
        f"limit={_text_value(report.get('limit'))}"
    )
    target = report.get("target")
    target = target if isinstance(target, dict) else {}
    print(
        "target "
        f"scheme={_text_value(target.get('scheme'))} "
        f"host={_text_value(target.get('host'))} "
        f"port={_text_value(target.get('port'))} "
        f"database={_text_value(target.get('database'))}"
    )
    checks = report.get("checks")
    for check in checks if isinstance(checks, list) else []:
        if not isinstance(check, dict):
            continue
        measurements = check.get("measurements")
        rendered_measurements = json.dumps(
            measurements if isinstance(measurements, dict) else {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        line = (
            f"check={_text_value(check.get('name'))} "
            f"status={_text_value(check.get('status'))} "
            f"reason={_text_value(check.get('reason'))} "
            f"measurements={rendered_measurements}"
        )
        if "threshold" in check:
            line += " threshold=" + json.dumps(
                check.get("threshold"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        if "source_timestamp" in check:
            line += f" source_timestamp={_text_value(check.get('source_timestamp'))}"
        print(line)


def cmd_data_trust_audit(args):
    try:
        report = run_data_trust_audit(
            deep=bool(getattr(args, "deep", False)),
            limit=int(getattr(args, "limit", 200)),
        )
    except Exception:
        report = _unverified_report()

    if bool(getattr(args, "as_json", False)):
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        _render_text(report)

    exit_code = _exit_code(report)
    if exit_code:
        raise SystemExit(exit_code)
    return report

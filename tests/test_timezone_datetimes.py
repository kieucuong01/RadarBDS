from pathlib import Path
from datetime import date, datetime, timezone

import pytest


@pytest.mark.parametrize('instant,activity,expected', [
    ('2026-10-24T23:30:00+00:00', '2026-10-25 06:15:00', 0),
    ('2026-10-25T00:30:00+00:00', '2026-10-24T23:55:00+00:00', 0),
    ('2026-10-25T00:30:00+00:00', '2026-10-24 06:00:00', 1),
])
def test_listing_age_uses_vietnam_calendar_across_utc_midnight(monkeypatch, instant, activity, expected):
    from services import market_data
    now = datetime.fromisoformat(instant)

    class UtcHostDate(date):
        @classmethod
        def today(cls):
            return now.date()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(market_data, 'date', UtcHostDate)
    monkeypatch.setattr(market_data, 'datetime', FrozenDatetime)
    assert market_data._days_ago(activity) == expected


def test_runtime_code_does_not_use_deprecated_datetime_utcnow():
    root = Path(__file__).resolve().parent.parent
    scan_targets = [
        root / "app.py",
        root / "alerts",
        root / "analytics",
        root / "cleansing",
        root / "cli",
        root / "config",
        root / "crawler",
        root / "db",
        root / "routes",
        root / "scripts",
        root / "services",
    ]
    offenders = []
    for target in scan_targets:
        files = [target] if target.is_file() else target.rglob("*.py")
        for path in files:
            text = path.read_text(encoding="utf-8")
            if "datetime.utcnow(" in text:
                offenders.append(path.relative_to(root).as_posix())

    assert offenders == []

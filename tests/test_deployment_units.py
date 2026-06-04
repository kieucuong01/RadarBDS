from pathlib import Path


def test_guland_secondary_systemd_timer_runs_after_primary_daily_crawl():
    base = Path("deployment/ubuntu24")
    service = (base / "radar-bds-guland-crawl.service").read_text(encoding="utf-8")
    timer = (base / "radar-bds-guland-crawl.timer").read_text(encoding="utf-8")

    assert "radar.py crawl-daily --source guland --no-alert --no-groq" in service
    assert "/run/radar-bds/crawl.lock" in service
    assert "OnCalendar=*-*-* 22:30:00" in timer
    assert "Unit=radar-bds-guland-crawl.service" in timer

import importlib.util
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "radar_growth_14d.py"
    spec = importlib.util.spec_from_file_location("radar_growth_14d", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_growth_report_counts_social_state_and_scores_targets(monkeypatch, tmp_path):
    module = _load_module()
    now = datetime(2026, 7, 27, 9, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

    (tmp_path / "group-autopost").mkdir()
    (tmp_path / "public-post-comment").mkdir()
    (tmp_path / "posted_slugs.json").write_text(
        '{"posted":{"a":{"posted_at":"2026-07-26T09:00:00+07:00"}}}', encoding="utf-8"
    )
    (tmp_path / "group-autopost" / "state.json").write_text(
        '{"actions":[{"at":"2026-07-26T09:00:00+07:00","status":"published"}]}', encoding="utf-8"
    )
    (tmp_path / "public-post-comment" / "state.json").write_text(
        '{"actions":[{"at":"2026-07-26T09:00:00+07:00","status":"published"}]}', encoding="utf-8"
    )
    monkeypatch.setattr(module, "STATE_ROOT", tmp_path)
    monkeypatch.setattr(module, "_db_counts", lambda cutoff: {
        "action_counts": {"social_utm_visit": 120},
        "content_views": 240,
        "social_utm_visits": 120,
        "cta_clicks": 8,
        "lead_submit_events": 1,
        "leads": 1,
        "attributed_leads": 1,
    })

    report = module.build_report(days=14, now=now)

    assert report["metrics"]["page_posts"] == 1
    assert report["metrics"]["group_posts"] == 1
    assert report["metrics"]["comments"] == 1
    assert report["targets_14d"]["social_utm_visits"]["met"] is True
    assert report["targets_14d"]["leads"]["met"] is True
    assert report["utm_convention"]["page"].startswith("facebook / organic_social")

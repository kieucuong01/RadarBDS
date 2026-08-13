from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path("/opt/radar-bds/current/scripts/radar_social_auto_post.py")
spec = importlib.util.spec_from_file_location("radar_social_auto_post", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_posted_today_requires_same_day_and_real_permalink():
    posted = {
        "false-positive": {
            "posted_at": "2026-08-01T08:00:00+07:00",
            "post_url": "https://www.facebook.com/radarbdsvn/",
        },
        "real-post": {
            "posted_at": "2026-08-01T10:00:00+07:00",
            "post_url": "https://www.facebook.com/radarbdsvn/posts/pfbid123",
            "photo_url": "https://www.facebook.com/photo/?fbid=456&set=a.789",
            "verified_text": True,
            "verified_visual": True,
        },
    }
    ok, item = mod.posted_today(posted, today=dt.date(2026, 8, 1))
    assert ok is True
    assert item["post_url"].endswith("pfbid123")


def test_posted_today_ignores_old_valid_permalink():
    ok, _ = mod.posted_today(
        {"old": {"posted_at": "2026-07-31T18:00:00+07:00", "post_url": "https://www.facebook.com/radarbdsvn/posts/pfbidold"}},
        today=dt.date(2026, 8, 1),
    )
    assert ok is False


def test_posted_today_rejects_post_without_verified_native_visual():
    ok, _ = mod.posted_today(
        {
            "text-only": {
                "posted_at": "2026-08-01T18:00:00+07:00",
                "post_url": "https://www.facebook.com/radarbdsvn/posts/pfbid123",
                "verified_text": True,
                "verified_visual": False,
            }
        },
        today=dt.date(2026, 8, 1),
    )
    assert ok is False


def test_posted_today_accepts_production_nested_browser_result():
    item = {
        "posted_at": "2026-08-04T21:19:01+07:00",
        "post_url": "https://www.facebook.com/radarbdsvn/posts/pfbid123",
        "browser_result": {
            "verified_text": True,
            "verified_visual": True,
            "verified_comment": True,
            "permalink": "https://www.facebook.com/radarbdsvn/posts/pfbid123",
            "photo_permalink": "https://www.facebook.com/photo/?fbid=456&set=a.789",
        },
    }
    ok, found = mod.posted_today({"production-shape": item}, today=dt.date(2026, 8, 4))
    assert ok is True
    assert found is item


def test_main_checks_daily_cap_before_browser_health(monkeypatch):
    item = {
        "posted_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "post_url": "https://www.facebook.com/radarbdsvn/posts/pfbid123",
        "browser_result": {
            "verified_text": True,
            "verified_visual": True,
            "permalink": "https://www.facebook.com/radarbdsvn/posts/pfbid123",
            "photo_permalink": "https://www.facebook.com/photo/?fbid=456&set=a.789",
        },
    }
    monkeypatch.setattr(mod, "load_state", lambda: {"posted": {"today": item}})

    def browser_must_not_be_touched():
        raise AssertionError("daily-cap no-op must not depend on CDP")

    monkeypatch.setattr(mod, "ensure_browser", browser_must_not_be_touched)
    assert mod.main() == 0


def test_parse_post_wrapper_stdout_requires_browser_permalink():
    wrapper = {
        "returncode": 0,
        "browser_result": {
            "ok": True,
            "verified_text": True,
            "verified_visual": True,
            "verified_comment": True,
            "permalink": "https://www.facebook.com/radarbdsvn/posts/pfbid123",
            "photo_permalink": "https://www.facebook.com/photo/?fbid=456&set=a.789",
        },
    }
    parsed = mod.parse_post_wrapper_stdout(__import__("json").dumps(wrapper))
    assert parsed["browser_result"]["permalink"].endswith("pfbid123")


def test_parse_post_wrapper_stdout_rejects_missing_permalink():
    with pytest.raises(SystemExit, match="missing verified permalink"):
        mod.parse_post_wrapper_stdout('{"returncode": 0, "browser_result": {"ok": true, "verified_text": true}}')


def test_parse_post_wrapper_stdout_rejects_missing_native_visual():
    with pytest.raises(SystemExit, match="native visual"):
        mod.parse_post_wrapper_stdout(
            '{"returncode": 0, "browser_result": {'
            '"ok": true, "verified_text": true, "verified_visual": false, '
            '"permalink": "https://www.facebook.com/radarbdsvn/posts/pfbid123"}}'
        )


def test_parse_post_wrapper_stdout_rejects_browser_result_not_ok():
    with pytest.raises(SystemExit, match="browser_result.ok=true"):
        mod.parse_post_wrapper_stdout(
            '{"returncode": 0, "browser_result": {'
            '"ok": false, "verified_text": true, "verified_visual": true, '
            '"permalink": "https://www.facebook.com/radarbdsvn/posts/pfbid123", '
            '"photo_permalink": "https://www.facebook.com/photo/?fbid=456&set=a.789"}}'
        )


def test_parse_post_wrapper_stdout_rejects_missing_self_comment():
    with pytest.raises(SystemExit, match="self-comment"):
        mod.parse_post_wrapper_stdout(
            '{"returncode": 0, "browser_result": {'
            '"ok": true, "verified_text": true, "verified_visual": true, '
            '"permalink": "https://www.facebook.com/radarbdsvn/posts/pfbid123", '
            '"photo_permalink": "https://www.facebook.com/photo/?fbid=456&set=a.789"}}'
        )


def test_page_care_style_rotates_on_tuesday_and_thursday():
    assert mod.page_care_style_for_date(dt.date(2026, 8, 10)) == "data_post"
    assert mod.page_care_style_for_date(dt.date(2026, 8, 11)) == "market_pulse"
    assert mod.page_care_style_for_date(dt.date(2026, 8, 13)) == "market_pulse"

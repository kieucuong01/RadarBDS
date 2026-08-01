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


def test_parse_post_wrapper_stdout_requires_browser_permalink():
    wrapper = {
        "returncode": 0,
        "browser_result": {
            "ok": True,
            "verified_text": True,
            "permalink": "https://www.facebook.com/radarbdsvn/posts/pfbid123",
        },
    }
    parsed = mod.parse_post_wrapper_stdout(__import__("json").dumps(wrapper))
    assert parsed["browser_result"]["permalink"].endswith("pfbid123")


def test_parse_post_wrapper_stdout_rejects_missing_permalink():
    with pytest.raises(SystemExit, match="missing verified permalink"):
        mod.parse_post_wrapper_stdout('{"returncode": 0, "browser_result": {"ok": true, "verified_text": true}}')

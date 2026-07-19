import json
from datetime import date, timedelta

from crawler import facebook_apify
from services.admin_quality import read_facebook_profile_config, write_facebook_profile_config


def test_profile_config_round_trips_cadence_and_defaults_invalid_to_daily(tmp_path):
    path = tmp_path / "facebook_profiles.json"
    path.write_text(json.dumps({"Bến Cát": [
        {"url": "https://www.facebook.com/three", "crawl_every_days": 3},
        {"url": "https://www.facebook.com/invalid", "crawl_every_days": 5},
    ]}), encoding="utf-8")

    profiles = read_facebook_profile_config(path)
    assert [profile["crawl_every_days"] for profile in profiles] == [3, 1]

    saved = write_facebook_profile_config(path, profiles)
    loaded = facebook_apify.load_profiles(path)
    assert [profile["crawl_every_days"] for profile in saved] == [3, 1]
    assert [profile["crawl_every_days"] for profile in loaded] == [3, 1]


def test_profile_due_on_is_stable_for_all_cadences():
    assert hasattr(facebook_apify, "profile_due_on"), "profile_due_on must be implemented"
    profile_due_on = facebook_apify.profile_due_on
    start = date(2026, 7, 19)
    daily = {"url": "https://www.facebook.com/daily", "crawl_every_days": 1}
    three = {"url": "https://www.facebook.com/three", "crawl_every_days": 3}
    weekly = {"url": "https://www.facebook.com/weekly", "crawl_every_days": 7}

    assert all(profile_due_on(daily, start + timedelta(days=index)) for index in range(21))
    assert sum(profile_due_on(three, start + timedelta(days=index)) for index in range(21)) == 7
    assert sum(profile_due_on(weekly, start + timedelta(days=index)) for index in range(21)) == 3

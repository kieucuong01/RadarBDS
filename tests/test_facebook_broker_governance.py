import json
from datetime import date, timedelta

from crawler import facebook_apify
from services import admin_quality
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


def _profile(url, name, city="Thu Dau Mot"):
    return {"url": url, "broker_name": name, "city": city}


def _stats(score_a=90, score_b=70):
    return {
        "https://www.facebook.com/a": {
            "data_quality": {"score": score_a},
            "latest_crawled_at": "2026-07-19 10:00:00",
        },
        "https://www.facebook.com/b": {
            "data_quality": {"score": score_b},
            "latest_crawled_at": "2026-07-18 10:00:00",
        },
    }


def test_duplicate_analysis_is_directional_and_keeps_cleaner_broker():
    assert hasattr(admin_quality, "build_facebook_duplicate_analysis")
    profiles = [
        _profile("https://www.facebook.com/a", "A"),
        _profile("https://www.facebook.com/b", "B"),
    ]
    rows = [{"cluster_id": i, "profile_url": profiles[0]["url"]} for i in range(1, 21)]
    rows += [{"cluster_id": i, "profile_url": profiles[1]["url"]} for i in range(1, 11)]

    result = admin_quality.build_facebook_duplicate_analysis(profiles, _stats(), rows)
    item = result["comparisons"][0]
    assert item["shared_lots"] == 10
    assert item["broker_a_overlap_pct"] == 50.0
    assert item["broker_b_overlap_pct"] == 100.0
    assert item["keep_url"] == profiles[0]["url"]
    assert item["reduce_url"] == profiles[1]["url"]
    assert item["recommended_crawl_every_days"] == 7
    assert result["by_profile"][profiles[1]["url"]]["shared_lots"] == 10


def test_duplicate_analysis_rejects_cross_city_pairs():
    assert hasattr(admin_quality, "build_facebook_duplicate_analysis")
    profiles = [
        _profile("https://www.facebook.com/a", "A"),
        _profile("https://www.facebook.com/b", "B", "Ben Cat"),
    ]
    rows = [{"cluster_id": i, "profile_url": profile["url"]} for i in range(1, 20) for profile in profiles]
    result = admin_quality.build_facebook_duplicate_analysis(profiles, _stats(), rows)
    assert result["comparisons"] == []

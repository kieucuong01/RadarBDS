import json
import subprocess
from pathlib import Path


NEWS_HUB_SCRIPT = Path("static/js/seo_news_hub.js")


def _run_node(expression: str):
    result = subprocess.run(
        [
            "node",
            "-e",
            (
                f"const hub = require({json.dumps(str(NEWS_HUB_SCRIPT.resolve()))});"
                f"process.stdout.write(JSON.stringify({expression}));"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_news_hub_search_is_vietnamese_accent_insensitive():
    result = _run_node(
        "hub.filterArticles(["
        "{category:'du-lieu-gia-dat',searchText:'Giá đất Phú Tân'},"
        "{category:'kiem-tra-tin-rao',searchText:'Tin rẻ bất thường'}"
        "], 'all', 'gia dat phu tan')"
    )

    assert result == [0]


def test_news_hub_filter_combines_category_and_query():
    result = _run_node(
        "hub.filterArticles(["
        "{category:'so-sanh-khu-vuc',searchText:'Phú Mỹ và Định Hòa'},"
        "{category:'du-lieu-gia-dat',searchText:'Giá đất Phú Mỹ'},"
        "{category:'so-sanh-khu-vuc',searchText:'Phú Lợi và Phú Tân'}"
        "], 'so-sanh-khu-vuc', 'phu my')"
    )

    assert result == [0]


def test_news_hub_malformed_category_hash_falls_back_to_all():
    result = _run_node(
        "hub.categoryFromHash("
        "{location:{hash:'#cat-%'}},"
        "['all','kiem-tra-tin-rao']"
        ")"
    )

    assert result == "all"


def test_news_hub_visible_count_advances_in_fixed_batches():
    assert _run_node("hub.nextVisibleCount(8, 23, 8)") == 16
    assert _run_node("hub.nextVisibleCount(16, 23, 8)") == 23
    assert _run_node("hub.nextVisibleCount(0, 5, 8)") == 5

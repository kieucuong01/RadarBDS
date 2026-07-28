import json
import subprocess
from pathlib import Path


PLANNING_HUB_SCRIPT = Path("static/js/planning_hub.js")


def _run_node(expression: str):
    result = subprocess.run(
        [
            "node",
            "-e",
            (
                f"const hub = require({json.dumps(str(PLANNING_HUB_SCRIPT.resolve()))});"
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


def test_planning_hub_filter_returns_matching_indexes():
    result = _run_node(
        "hub.filterIndexes(["
        "{category:'transport'},"
        "{category:'boundary'},"
        "{category:'transport'}"
        "], 'transport')"
    )

    assert result == [0, 2]


def test_planning_hub_all_filter_keeps_every_card():
    result = _run_node(
        "hub.filterIndexes(["
        "{category:'transport'},"
        "{category:'boundary'}"
        "], 'all')"
    )

    assert result == [0, 1]


def test_planning_hub_hash_supports_valid_categories():
    result = _run_node(
        "hub.categoryFromHash("
        "{location:{hash:'#cat-boundary'}},"
        "['all','transport','boundary']"
        ")"
    )

    assert result == "boundary"


def test_planning_hub_invalid_or_malformed_hash_falls_back_to_all():
    assert _run_node(
        "hub.categoryFromHash("
        "{location:{hash:'#cat-landuse'}},"
        "['all','transport','boundary']"
        ")"
    ) == "all"
    assert _run_node(
        "hub.categoryFromHash("
        "{location:{hash:'#cat-%'}},"
        "['all','transport','boundary']"
        ")"
    ) == "all"


def test_planning_hub_tracking_context_has_no_raw_content():
    result = _run_node("hub.filterTrackContext('transport', 4)")

    assert result == {"category": "transport", "result_count": 4}

from __future__ import annotations

import json
import subprocess
from pathlib import Path


SCRIPT = Path("static/js/public_content_hub.js")


def _run_node(expression: str):
    result = subprocess.run(
        [
            "node",
            "-e",
            (
                f"const hub = require({json.dumps(str(SCRIPT.resolve()))});"
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


def test_normalize_text_matches_accented_and_unaccented_queries():
    assert _run_node("hub.normalizeText('Thủ Dầu Một')") == "thu dau mot"
    assert _run_node("hub.normalizeText('quyết định 1703')") == (
        "quyet dinh 1703"
    )


def test_combined_search_and_facets_filter_items():
    result = _run_node(
        "hub.filterIndexes(["
        "{search:'quyet dinh 1703 thu dau mot',facet:'UBND',topic:'ha-tang',type:'Quyết định',year:'2025'},"
        "{search:'nghi quyet di an',facet:'HĐND',topic:'thi-truong',type:'Nghị quyết',year:'2024'}"
        "],{query:'1703',facet:'UBND',topic:'hạ tầng',type:'Quyết định',year:'2025'})"
    )
    assert result == [0]


def test_empty_filters_keep_all_items():
    assert _run_node(
        "hub.filterIndexes([{search:'a'},{search:'b'}],{})"
    ) == [0, 1]


def test_tracking_context_never_contains_raw_query():
    context = _run_node("hub.filterTrackContext('bí mật', 7, 'CafeLand')")

    assert context == {
        "query_length": 6,
        "result_count": 7,
        "facet": "CafeLand",
    }
    assert "query" not in context

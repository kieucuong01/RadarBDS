from contextlib import contextmanager
from unittest import mock
from argparse import Namespace
import json

import pytest

from services.listing_location_resolver import ResolutionIssue


class _Cursor:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.executed = []
        self.executemany_calls = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return _Cursor(self.rows)

    def executemany(self, sql, params):
        self.executemany_calls.append((sql, list(params)))
        return _Cursor()


@contextmanager
def _connection_context(connection):
    yield connection


def test_location_candidates_include_map_text_but_exclude_sensitive_fields():
    from db import listing_map_locations

    connection = _Connection()
    with mock.patch.object(
        listing_map_locations,
        "get_conn",
        return_value=_connection_context(connection),
    ):
        listing_map_locations.iter_location_candidates([9])

    sql = connection.executed[0][0].lower()
    assert "l.title" in sql
    assert "l.description" in sql
    assert "coalesce(l.probably_sold, 0) = 0" in sql
    assert "coalesce(l.is_blacklisted, 0) = 0" in sql
    assert "coalesce(l.review_hidden, 0) = 0" in sql
    assert "possibly_duplicate" not in sql
    for forbidden in ("phone", "url", "seller", "image"):
        assert forbidden not in sql


def test_ward_fallback_loader_is_active_ward_precision_and_private():
    from db import listing_map_locations

    connection = _Connection()
    with mock.patch.object(
        listing_map_locations,
        "get_conn",
        return_value=_connection_context(connection),
    ):
        listing_map_locations.load_ward_fallback_listings(
            ["An Phú", "An Phu"]
        )

    sql, params = connection.executed[0]
    lowered = sql.lower()
    assert "ml.location_precision = 'ward'" in lowered
    assert "coalesce(l.probably_sold, 0) = 0" in lowered
    assert "coalesce(l.is_blacklisted, 0) = 0" in lowered
    assert "coalesce(l.review_hidden, 0) = 0" in lowered
    assert params == ["An Phu", "An Phú"]
    for forbidden in ("phone", "url", "seller", "image"):
        assert forbidden not in lowered


def test_coverage_upsert_bounds_samples_and_preserves_first_seen():
    from db import listing_location_coverage

    row = listing_location_coverage.CoverageRow(
        candidate_key="road:thu-dau-mot:phu-tan:duong-so-88",
        city="THỦ DẦU MỘT",
        ward="Phú Tân",
        road_candidate="duong so 88",
        landmark_candidate="tdc phu chanh d",
        relation="on",
        status="not_found",
        affected_listing_count=12,
        sample_listing_ids=tuple(range(20, 5, -1)),
        resolution_note="Chưa có đường trong nguồn được xác minh",
    )
    connection = _Connection()
    with mock.patch.object(
        listing_location_coverage,
        "get_conn",
        return_value=_connection_context(connection),
    ):
        assert listing_location_coverage.upsert_listing_location_coverage([row]) == 1

    sql, values = connection.executemany_calls[0]
    assert "first_seen_at=listing_map_location_coverage.first_seen_at" in sql
    assert "last_seen_at=NOW()" in sql
    assert values[0][8] == "[6, 7, 8, 9, 10, 11, 12, 13, 14, 15]"


def test_coverage_repository_rejects_unknown_status_and_bounds_load_limit():
    from db import listing_location_coverage

    invalid = listing_location_coverage.CoverageRow(
        candidate_key="bad",
        city="THỦ DẦU MỘT",
        status="pending",
    )
    with pytest.raises(ValueError, match="status"):
        listing_location_coverage.upsert_listing_location_coverage([invalid])

    connection = _Connection(
        [
            {
                "candidate_key": "road:test",
                "status": "not_found",
                "sample_listing_ids": [3, 1],
            }
        ]
    )
    with mock.patch.object(
        listing_location_coverage,
        "get_conn",
        return_value=_connection_context(connection),
    ):
        rows = listing_location_coverage.load_listing_location_coverage(
            status="not_found",
            limit=50_000,
        )

    assert rows[0]["candidate_key"] == "road:test"
    assert connection.executed[0][1] == ["not_found", 1000]


def _issue(listing_id, *, road="", landmark="", status="not_found"):
    return ResolutionIssue(
        listing_id=listing_id,
        candidate_key=f"road:test:{road or landmark}",
        city="THỦ DẦU MỘT",
        ward="Tân An",
        road_candidate=road,
        landmark_candidate=landmark,
        relation="on",
        status=status,
        resolution_note=f"{status}_candidate",
    )


def test_coverage_issues_group_by_normalized_candidate():
    from services.listing_location_coverage import aggregate_coverage_issues

    rows = aggregate_coverage_issues(
        [
            _issue(11, road="DX 120"),
            _issue(10, road="dx 120"),
            _issue(10, road="đx-120"),
        ]
    )

    assert len(rows) == 1
    assert rows[0].affected_listing_count == 2
    assert rows[0].sample_listing_ids == (10, 11)
    assert len(rows[0].candidate_key) == 64


def test_map_location_coverage_cli_expands_unresolved_and_redacts_text(capsys):
    from cli import map_locations

    items = [
        {
            "candidate_key": "abc",
            "city": "THỦ DẦU MỘT",
            "ward": "Tân An",
            "road_candidate": "dx 120",
            "landmark_candidate": "",
            "relation": "on",
            "status": "not_found",
            "affected_listing_count": 2,
            "sample_listing_ids": [10, 11],
            "resolution_note": "road_not_found",
        }
    ]
    with mock.patch.object(
        map_locations,
        "load_listing_location_coverage",
        side_effect=[[], items, []],
    ) as load_rows:
        payload = map_locations.cmd_map_location_coverage(
            Namespace(status="unresolved", limit=50)
        )

    printed = json.loads(capsys.readouterr().out)
    assert payload == printed
    assert payload["status"] == ["ambiguous", "not_found", "invalid"]
    assert payload["total_candidates"] == 1
    assert payload["affected_listings"] == 2
    assert [call.args for call in load_rows.call_args_list] == [
        ("ambiguous", 50),
        ("not_found", 50),
        ("invalid", 50),
    ]
    assert "description" not in printed["items"][0]


def test_map_location_coverage_cli_filters_city_ward_and_alias(capsys):
    from cli import map_locations

    items = [
        {
            "candidate_key": "phu-tan",
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Tân",
            "road_candidate": "duong so 84",
            "landmark_candidate": "",
            "relation": "on",
            "status": "not_found",
            "affected_listing_count": 2,
            "sample_listing_ids": [10, 11],
            "resolution_note": "road_not_found",
        },
        {
            "candidate_key": "phu-chanh",
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Chánh",
            "road_candidate": "",
            "landmark_candidate": "",
            "relation": "",
            "status": "not_found",
            "affected_listing_count": 3,
            "sample_listing_ids": [12, 13, 14],
            "resolution_note": "ward_not_found",
        },
        {
            "candidate_key": "phu-my",
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Mỹ",
            "road_candidate": "n 5",
            "landmark_candidate": "",
            "relation": "on",
            "status": "not_found",
            "affected_listing_count": 99,
            "sample_listing_ids": [15],
            "resolution_note": "road_not_found",
        },
    ]
    with mock.patch.object(
        map_locations,
        "load_listing_location_coverage",
        return_value=items,
    ):
        payload = map_locations.cmd_map_location_coverage(
            Namespace(
                status="not_found",
                limit=50,
                city="THỦ DẦU MỘT",
                ward="Phú Tân",
                include_ward_alias=["Phú Chánh"],
            )
        )

    printed = json.loads(capsys.readouterr().out)
    assert payload == printed
    assert [item["candidate_key"] for item in payload["items"]] == [
        "phu-chanh",
        "phu-tan",
    ]
    assert payload["affected_listings"] == 5


def test_map_location_research_queue_filters_city_ward_and_alias(capsys):
    from cli import map_locations

    items = [
        {
            "candidate_key": "phu-tan",
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Tân",
            "road_candidate": "Đường số 84",
            "landmark_candidate": "",
            "relation": "on",
            "status": "not_found",
            "affected_listing_count": 2,
            "sample_listing_ids": [10, 11],
            "resolution_note": "road_not_found",
        },
        {
            "candidate_key": "phu-chanh",
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Chánh",
            "road_candidate": "Đường số 35",
            "landmark_candidate": "",
            "relation": "on",
            "status": "not_found",
            "affected_listing_count": 3,
            "sample_listing_ids": [12, 13, 14],
            "resolution_note": "road_not_found",
        },
        {
            "candidate_key": "phu-my",
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Mỹ",
            "road_candidate": "Đường số 86",
            "landmark_candidate": "",
            "relation": "on",
            "status": "not_found",
            "affected_listing_count": 99,
            "sample_listing_ids": [15],
            "resolution_note": "road_not_found",
        },
    ]
    with mock.patch.object(
        map_locations,
        "_accepted_recheck_items",
        return_value=[],
    ), mock.patch.object(
        map_locations,
        "load_listing_location_coverage",
        return_value=items,
    ):
        payload = map_locations.cmd_map_location_research_queue(
            Namespace(
                limit=50,
                candidate_type="road",
                city="THỦ DẦU MỘT",
                ward="Phú Tân",
                include_ward_alias=["Phú Chánh"],
            )
        )

    printed = json.loads(capsys.readouterr().out)
    assert payload == printed
    assert [item["ward"] for item in payload["items"]] == [
        "Phú Chánh",
        "Phú Tân",
    ]
    assert payload["returned_candidates"] == 2


def test_radar_parser_accepts_coverage_audit_options():
    import radar

    args = radar.build_parser().parse_args(
        [
            "map-location-coverage",
            "--status",
            "unresolved",
            "--limit",
            "50",
            "--city",
            "THỦ DẦU MỘT",
            "--ward",
            "Phú Tân",
            "--include-ward-alias",
            "Phú Chánh",
        ]
    )

    assert args.cmd == "map-location-coverage"
    assert args.status == "unresolved"
    assert args.limit == 50
    assert args.city == "THỦ DẦU MỘT"
    assert args.ward == "Phú Tân"
    assert args.include_ward_alias == ["Phú Chánh"]


def test_radar_parser_accepts_research_queue_location_filters():
    import radar

    args = radar.build_parser().parse_args(
        [
            "map-location-research-queue",
            "--limit",
            "40",
            "--candidate-type",
            "road",
            "--city",
            "THỦ DẦU MỘT",
            "--ward",
            "Phú Tân",
            "--include-ward-alias",
            "Phú Chánh",
        ]
    )

    assert args.cmd == "map-location-research-queue"
    assert args.limit == 40
    assert args.candidate_type == "road"
    assert args.city == "THỦ DẦU MỘT"
    assert args.ward == "Phú Tân"
    assert args.include_ward_alias == ["Phú Chánh"]

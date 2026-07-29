import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cli import map_locations
from radar import build_parser


def _evidence_payload(**changes):
    data = {
        "candidate_key": "landmark:thu-dau-mot:phu-tan:tdc-phu-chanh-b",
        "candidate_type": "landmark",
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Tân",
        "canonical": "TĐC Phú Chánh B",
        "aliases": [
            "TDC Phu Chanh B",
            "Khu tái định cư Phú Chánh B",
        ],
        "query": "TĐC Phú Chánh B, Phú Tân, Thủ Dầu Một",
        "result_title": "Khu tái định cư Phú Chánh B",
        "result_address": "Đ. Số 55, Khu TĐC Phú Chánh B",
        "result_type": "Housing complex",
        "source_url": (
            "https://www.google.com/maps/"
            "@11.058782,106.7015151,17z"
        ),
        "unique_result": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    data.update(changes)
    return data


def test_research_queue_outputs_bounded_google_maps_search_urls(monkeypatch):
    row = {
        "candidate_key": "coverage-hash",
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Tân",
        "road_candidate": "",
        "landmark_candidate": "tdc phu chanh b",
        "relation": "at",
        "status": "not_found",
        "affected_listing_count": 25,
        "sample_listing_ids": [1, 2],
        "resolution_note": "landmark_not_found",
    }
    monkeypatch.setattr(
        map_locations,
        "load_listing_location_coverage",
        lambda status, limit: [row] if status == "not_found" else [],
    )

    payload = map_locations.cmd_map_location_research_queue(
        SimpleNamespace(limit=50, candidate_type="all")
    )

    assert payload["total_candidates"] == 1
    assert payload["items"][0]["candidate_key"] == (
        "landmark:thu-dau-mot:phu-tan:tdc-phu-chanh-b"
    )
    assert payload["items"][0]["aliases"] == [
        "khu tai dinh cu phu chanh b"
    ]
    assert payload["items"][0]["query"] == (
        "tdc phu chanh b, Phú Tân, THỦ DẦU MỘT"
    )
    assert payload["items"][0]["search_url"] == (
        "https://www.google.com/maps/search/?"
        "api=1&query=tdc+phu+chanh+b%2C+Ph%C3%BA+T%C3%A2n%2C+"
        "TH%E1%BB%A6+D%E1%BA%A6U+M%E1%BB%98T"
    )
    assert "sample_listing_ids" not in payload["items"][0]


def test_research_queue_emits_separate_scoped_road_and_landmark_items(
    monkeypatch,
):
    row = {
        "candidate_key": "coverage-hash",
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Tân",
        "road_candidate": "duong so 35",
        "landmark_candidate": "tdc phu chanh b",
        "relation": "near",
        "status": "not_found",
        "affected_listing_count": 12,
        "resolution_note": "nearby_road_not_found",
    }
    monkeypatch.setattr(
        map_locations,
        "load_listing_location_coverage",
        lambda status, limit: [row] if status == "not_found" else [],
    )

    roads = map_locations.cmd_map_location_research_queue(
        SimpleNamespace(limit=50, candidate_type="road")
    )
    landmarks = map_locations.cmd_map_location_research_queue(
        SimpleNamespace(limit=50, candidate_type="landmark")
    )

    assert roads["items"][0]["candidate_key"] == (
        "road:thu-dau-mot:phu-tan:duong-so-35:tdc-phu-chanh-b"
    )
    assert roads["items"][0]["query"].startswith(
        "duong so 35, tdc phu chanh b,"
    )
    assert roads["items"][0]["landmark_scope"] == "tdc phu chanh b"
    assert landmarks["items"][0]["candidate_type"] == "landmark"


def test_research_queue_quarantines_obvious_listing_copy_from_road_candidates(
    monkeypatch,
):
    row = {
        "candidate_key": "coverage-hash",
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Tân",
        "road_candidate": "trệt 1 lầu 3 phòng ngủ",
        "landmark_candidate": "tdc phu chanh b",
        "relation": "at",
        "status": "not_found",
        "affected_listing_count": 14,
        "resolution_note": "road_not_found",
    }
    monkeypatch.setattr(
        map_locations,
        "load_listing_location_coverage",
        lambda status, limit: [row] if status == "not_found" else [],
    )

    payload = map_locations.cmd_map_location_research_queue(
        SimpleNamespace(limit=50, candidate_type="all")
    )

    assert [item["candidate_type"] for item in payload["items"]] == [
        "landmark"
    ]
    assert payload["filtered_candidates"] == 1


@pytest.mark.parametrize(
    "road_candidate",
    (
        "mat tien",
        "hem rong",
        "gan cho",
        "duong nhua",
    ),
)
def test_research_queue_filters_generic_listing_copy(
    monkeypatch,
    road_candidate,
):
    row = {
        "candidate_key": road_candidate,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Tân",
        "road_candidate": road_candidate,
        "landmark_candidate": "",
        "status": "not_found",
        "affected_listing_count": 1,
        "resolution_note": "road_not_found",
    }
    monkeypatch.setattr(
        map_locations,
        "load_listing_location_coverage",
        lambda status, limit: [row] if status == "not_found" else [],
    )

    payload = map_locations.cmd_map_location_research_queue(
        SimpleNamespace(limit=50, candidate_type="road")
    )

    assert payload["items"] == []
    assert payload["filtered_candidates"] == 1


def test_research_queue_sums_impact_and_reports_pre_limit_total(monkeypatch):
    rows = [
        {
            "candidate_key": f"row-{index}",
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Tân",
            "road_candidate": road,
            "landmark_candidate": "",
            "status": "not_found",
            "affected_listing_count": count,
            "resolution_note": "road_not_found",
        }
        for index, (road, count) in enumerate(
            (
                ("dx 120", 2),
                ("dx 120", 3),
                ("dx 121", 4),
            )
        )
    ]
    monkeypatch.setattr(
        map_locations,
        "load_listing_location_coverage",
        lambda status, limit: rows if status == "not_found" else [],
    )

    payload = map_locations.cmd_map_location_research_queue(
        SimpleNamespace(limit=1, candidate_type="road")
    )

    assert payload["total_candidates"] == 2
    assert payload["returned_candidates"] == 1
    assert payload["items"][0]["affected_listing_count"] == 5


def test_ingest_evidence_dry_run_does_not_write(tmp_path, monkeypatch):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps({"items": [_evidence_payload()]}, ensure_ascii=False),
        encoding="utf-8",
    )
    auto_path = tmp_path / "auto.json"
    auto_path.write_text(
        json.dumps({"resolver_version": "test-v3", "entries": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        map_locations,
        "LISTING_MAP_AUTO_OVERRIDE_PATH",
        auto_path,
    )
    monkeypatch.setattr(
        map_locations,
        "load_manual_override_keys",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        map_locations,
        "point_is_in_scoped_ward",
        lambda *args: True,
    )

    payload = map_locations.cmd_map_location_ingest_evidence(
        SimpleNamespace(input=evidence_path, apply=False)
    )

    assert payload == {
        "attempted": 1,
        "accepted": 1,
        "quarantined": 0,
        "applied": 0,
    }
    assert json.loads(auto_path.read_text(encoding="utf-8"))["entries"] == []


def test_ingest_evidence_apply_writes_only_accepted_entries_atomically(
    tmp_path,
    monkeypatch,
):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "items": [
                    _evidence_payload(),
                    _evidence_payload(
                        candidate_key=(
                            "landmark:thu-dau-mot:phu-tan:"
                            "tdc-phu-chanh-c"
                        ),
                        canonical="TĐC Phú Chánh C",
                        aliases=[
                            "TDC Phu Chanh C",
                            "Khu tái định cư Phú Chánh C",
                        ],
                        query=(
                            "TĐC Phú Chánh C, Phú Tân, "
                            "Thủ Dầu Một"
                        ),
                        result_title=(
                            "Khu tái định cư Phú Chánh C"
                        ),
                        unique_result=False,
                    ),
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    auto_path = tmp_path / "auto.json"
    auto_path.write_text(
        json.dumps({"resolver_version": "test-v3", "entries": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        map_locations,
        "LISTING_MAP_AUTO_OVERRIDE_PATH",
        auto_path,
    )
    monkeypatch.setattr(
        map_locations,
        "load_manual_override_keys",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        map_locations,
        "point_is_in_scoped_ward",
        lambda *args: True,
    )

    payload = map_locations.cmd_map_location_ingest_evidence(
        SimpleNamespace(input=evidence_path, apply=True)
    )

    saved = json.loads(auto_path.read_text(encoding="utf-8"))
    assert payload == {
        "attempted": 2,
        "accepted": 1,
        "quarantined": 1,
        "applied": 1,
    }
    assert len(saved["entries"]) == 1
    assert saved["entries"][0]["status"] == "accepted"


def test_ingest_quarantines_duplicate_candidate_keys(tmp_path, monkeypatch):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "items": [
                    _evidence_payload(),
                    _evidence_payload(
                        source_url=(
                            "https://www.google.com/maps/"
                            "@11.059000,106.702000,17z"
                        )
                    ),
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    auto_path = tmp_path / "auto.json"
    auto_path.write_text(
        json.dumps({"resolver_version": "test-v3", "entries": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        map_locations,
        "LISTING_MAP_AUTO_OVERRIDE_PATH",
        auto_path,
    )
    monkeypatch.setattr(
        map_locations,
        "load_manual_override_keys",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        map_locations,
        "point_is_in_scoped_ward",
        lambda *args: True,
    )

    payload = map_locations.cmd_map_location_ingest_evidence(
        SimpleNamespace(input=evidence_path, apply=True)
    )

    assert payload == {
        "attempted": 2,
        "accepted": 0,
        "quarantined": 2,
        "applied": 0,
    }
    assert json.loads(auto_path.read_text(encoding="utf-8"))[
        "entries"
    ] == []


def test_ingest_does_not_move_existing_candidate_automatically(
    tmp_path,
    monkeypatch,
):
    evidence_path = tmp_path / "evidence.json"
    auto_path = tmp_path / "auto.json"
    auto_path.write_text(
        json.dumps({"resolver_version": "test-v3", "entries": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        map_locations,
        "LISTING_MAP_AUTO_OVERRIDE_PATH",
        auto_path,
    )
    monkeypatch.setattr(
        map_locations,
        "load_manual_override_keys",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        map_locations,
        "point_is_in_scoped_ward",
        lambda *args: True,
    )

    evidence_path.write_text(
        json.dumps(
            {"items": [_evidence_payload()]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    first = map_locations.cmd_map_location_ingest_evidence(
        SimpleNamespace(input=evidence_path, apply=True)
    )
    original = auto_path.read_text(encoding="utf-8")
    evidence_path.write_text(
        json.dumps(
            {
                "items": [
                    _evidence_payload(
                        source_url=(
                            "https://www.google.com/maps/"
                            "@11.059000,106.702000,17z"
                        )
                    )
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    second = map_locations.cmd_map_location_ingest_evidence(
        SimpleNamespace(input=evidence_path, apply=True)
    )

    assert first["applied"] == 1
    assert second == {
        "attempted": 1,
        "accepted": 0,
        "quarantined": 1,
        "applied": 0,
    }
    assert auto_path.read_text(encoding="utf-8") == original


def test_ingest_rejects_unbounded_batch(tmp_path):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps({"items": [_evidence_payload()] * 51}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="at most 50"):
        map_locations.cmd_map_location_ingest_evidence(
            SimpleNamespace(input=evidence_path, apply=False)
        )


def test_parser_registers_map_research_and_ingest_commands():
    parser = build_parser()

    queue = parser.parse_args([
        "map-location-research-queue",
        "--limit",
        "25",
        "--candidate-type",
        "road",
    ])
    ingest = parser.parse_args([
        "map-location-ingest-evidence",
        "--input",
        "evidence.json",
        "--apply",
    ])

    assert queue.limit == 25
    assert queue.candidate_type == "road"
    assert ingest.input.name == "evidence.json"
    assert ingest.apply is True

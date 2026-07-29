import copy
import hashlib
import json
from pathlib import Path

import pytest

from config.listing_map import (
    LISTING_MAP_BOUNDS,
    LISTING_MAP_MANIFEST_PATH,
    LISTING_MAP_RESOLVER_VERSION,
    LISTING_MAP_ROAD_REGISTRY_PATH,
    LISTING_MAP_SUPPORTED_CITIES,
    LISTING_MAP_WARD_REGISTRY_PATH,
)
from scripts.build_listing_location_registry import build_location_registries
from services.listing_location_resolver import load_location_registry
from services.market_data import CITY_MAP


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "listing-map"


def _payloads():
    osm = json.loads((FIXTURE_DIR / "osm-roads.json").read_text(encoding="utf-8"))
    sources = json.loads(
        (FIXTURE_DIR / "location-sources.json").read_text(encoding="utf-8")
    )
    return osm, sources


def test_registry_builder_is_byte_stable_and_records_input_hashes(tmp_path):
    osm, sources = _payloads()
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first_paths = build_location_registries(osm, sources, first_dir)
    second_paths = build_location_registries(osm, sources, second_dir)

    assert [path.name for path in first_paths] == [
        "ward-centers.json",
        "road-centers.json",
        "manifest.json",
    ]
    for first, second in zip(first_paths, second_paths, strict=True):
        assert first.read_bytes() == second.read_bytes()

    wards = json.loads(first_paths[0].read_text(encoding="utf-8"))
    roads = json.loads(first_paths[1].read_text(encoding="utf-8"))
    manifest = json.loads(first_paths[2].read_text(encoding="utf-8"))
    assert wards["wards"][0]["normalized_ward"] == "phu loi"
    assert roads["roads"][0]["normalized_road"] == "dx 43"
    assert roads["roads"][0]["osm_way_ids"] == [2001, 2002]
    assert manifest["ward_count"] == 1
    assert manifest["road_count"] == 1
    for field in ("osm_sha256", "sources_sha256"):
        assert len(manifest[field]) == 64
        int(manifest[field], 16)
    assert manifest["ward_registry_sha256"] == hashlib.sha256(
        first_paths[0].read_bytes()
    ).hexdigest()
    assert manifest["road_registry_sha256"] == hashlib.sha256(
        first_paths[1].read_bytes()
    ).hexdigest()


def test_registry_manifest_preserves_explicit_unmatched_counts(tmp_path):
    osm, sources = _payloads()
    sources["ambiguous_road_count"] = 4
    sources["rejected_road_count"] = 7

    _ward_path, _road_path, manifest_path = build_location_registries(
        osm, sources, tmp_path
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["ambiguous_road_count"] == 4
    assert manifest["rejected_road_count"] == 7


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda _osm, sources: sources["roads"][0].update(
                {"osm_way_ids": [123456]}
            ),
            "missing OSM",
        ),
        (
            lambda _osm, sources: sources["roads"].append(
                {
                    **sources["roads"][0],
                    "road_name": "đx.43",
                }
            ),
            "duplicate normalized road",
        ),
        (
            lambda _osm, sources: sources["wards"][0].update({"osm_id": 9001}),
            "outside listing map bounds",
        ),
        (
            lambda _osm, sources: sources["roads"][0].update(
                {"osm_way_ids": [2999]}
            ),
            "not a highway",
        ),
        (
            lambda _osm, sources: sources["canonical_wards"].append(
                {"city": "THỦ DẦU MỘT", "ward": "Phú Hòa"}
            ),
            "missing canonical ward",
        ),
    ],
)
def test_registry_builder_rejects_invalid_or_ambiguous_sources(
    tmp_path, mutate, message
):
    osm, sources = _payloads()
    mutate(osm, sources)

    with pytest.raises(ValueError, match=message):
        build_location_registries(osm, sources, tmp_path)


def test_registry_builder_keeps_existing_outputs_after_validation_failure(tmp_path):
    osm, sources = _payloads()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    sentinels = {}
    for name in ("ward-centers.json", "road-centers.json", "manifest.json"):
        path = output_dir / name
        path.write_bytes(f"old-{name}".encode())
        sentinels[name] = path.read_bytes()

    broken = copy.deepcopy(sources)
    broken["roads"][0]["osm_way_ids"] = [123456]

    with pytest.raises(ValueError, match="missing OSM"):
        build_location_registries(osm, broken, output_dir)

    for name, expected in sentinels.items():
        assert (output_dir / name).read_bytes() == expected


def test_registry_builder_accepts_verified_ward_point_with_provenance(tmp_path):
    osm, sources = _payloads()
    sources["wards"][0] = {
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        "point": {"lat": 10.990696, "lng": 106.67406},
        "label": "Tâm phường Phú Lợi",
        "source": "Wikidata Q1901452 revision 2362556003",
        "source_url": (
            "https://www.wikidata.org/w/index.php"
            "?title=Q1901452&oldid=2362556003"
        ),
    }

    ward_path, _road_path, _manifest_path = build_location_registries(
        osm, sources, tmp_path
    )

    ward = json.loads(ward_path.read_text(encoding="utf-8"))["wards"][0]
    assert ward["lat"] == 10.990696
    assert ward["lng"] == 106.67406
    assert ward["label"] == "Tâm phường Phú Lợi"
    assert ward["source"] == "Wikidata Q1901452 revision 2362556003"
    assert ward["source_url"].startswith("https://www.wikidata.org/")
    assert "osm_id" not in ward


def test_registry_builder_labels_parent_zone_fallback_honestly(tmp_path):
    osm, sources = _payloads()
    sources["wards"][0] = {
        "city": "BẾN CÁT",
        "ward": "Mỹ Phước 1",
        "point": {"lat": 11.147617, "lng": 106.611713},
        "fallback_parent": "Mỹ Phước",
        "source": "Verified parent-zone point",
        "source_url": "https://example.test/source",
    }
    sources["canonical_wards"] = [
        {"city": "BẾN CÁT", "ward": "Mỹ Phước 1"}
    ]
    sources["roads"] = []

    ward_path, _road_path, _manifest_path = build_location_registries(
        osm, sources, tmp_path
    )

    ward = json.loads(ward_path.read_text(encoding="utf-8"))["wards"][0]
    assert ward["fallback_parent"] == "Mỹ Phước"
    assert (
        ward["label"]
        == "Theo trung tâm Mỹ Phước (xấp xỉ cho Mỹ Phước 1)"
    )


@pytest.mark.parametrize(
    "point_source",
    [
        {
            "point": {"lat": 20.0, "lng": 105.0},
            "source": "Verified source",
            "source_url": "https://example.test/source",
        },
        {
            "point": {"lat": 10.99, "lng": 106.67},
            "source": "Verified source",
            "source_url": "http://example.test/source",
        },
    ],
)
def test_registry_builder_rejects_invalid_verified_ward_point(
    tmp_path, point_source
):
    osm, sources = _payloads()
    sources["wards"][0] = {
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        **point_source,
    }

    with pytest.raises(ValueError, match="verified ward point"):
        build_location_registries(osm, sources, tmp_path)


def test_production_registry_covers_supported_wards_and_matches_manifest():
    manifest = json.loads(
        LISTING_MAP_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    wards = json.loads(
        LISTING_MAP_WARD_REGISTRY_PATH.read_text(encoding="utf-8")
    )
    roads = json.loads(
        LISTING_MAP_ROAD_REGISTRY_PATH.read_text(encoding="utf-8")
    )
    sources = json.loads(
        Path("config/listing_map_location_sources.json").read_text(
            encoding="utf-8"
        )
    )

    expected_wards = {
        (city, ward)
        for city in LISTING_MAP_SUPPORTED_CITIES
        for ward in CITY_MAP[city]
    }
    actual_wards = {
        (row["city"], row["ward"])
        for row in wards["wards"]
    }
    assert tuple(sources["coverage_cities"]) == LISTING_MAP_SUPPORTED_CITIES
    assert actual_wards == expected_wards
    assert manifest["resolver_version"] == LISTING_MAP_RESOLVER_VERSION
    assert wards["resolver_version"] == LISTING_MAP_RESOLVER_VERSION
    assert roads["resolver_version"] == LISTING_MAP_RESOLVER_VERSION
    assert manifest["ward_count"] == len(wards["wards"]) == 26
    assert manifest["road_count"] == len(roads["roads"]) == 110
    assert manifest["ward_registry_sha256"] == hashlib.sha256(
        LISTING_MAP_WARD_REGISTRY_PATH.read_bytes()
    ).hexdigest()
    assert manifest["road_registry_sha256"] == hashlib.sha256(
        LISTING_MAP_ROAD_REGISTRY_PATH.read_bytes()
    ).hexdigest()
    for row in (*wards["wards"], *roads["roads"]):
        (south, west), (north, east) = LISTING_MAP_BOUNDS
        assert south <= row["lat"] <= north
        assert west <= row["lng"] <= east

    registry = load_location_registry()
    assert (
        registry.roads[
            ("THỦ DẦU MỘT", "dinh hoa", "dx 63")
        ]["source"]
        == "OpenStreetMap"
    )
    assert (
        registry.wards[("BẾN CÁT", "my phuoc 1")]["label"]
        == "Theo trung tâm Mỹ Phước (xấp xỉ cho Mỹ Phước 1)"
    )

import json
from argparse import Namespace

from services.listing_location_resolver import LocationRegistry
from services.listing_map_fallback_audit import audit_ward_fallbacks


def _registry(*roads):
    road_index = {}
    for road in roads:
        entry = {
            "city": "THUẬN AN",
            "normalized_ward": "an phu",
            "normalized_road": road["canonical"],
            "aliases": road.get("aliases", []),
        }
        for alias in {road["canonical"], *road.get("aliases", [])}:
            key = ("THUẬN AN", "an phu", alias)
            road_index.setdefault(key, []).append(entry)
    return LocationRegistry(
        resolver_version="test",
        roads={key: tuple(value) for key, value in road_index.items()},
        landmarks={},
        wards={
            ("THUẬN AN", "an phu"): {
                "city": "THUẬN AN",
                "normalized_ward": "an phu",
            }
        },
    )


def test_audit_finds_named_registry_road_missed_by_primary_extractor():
    registry = _registry(
        {"canonical": "phan dinh giot", "aliases": ["phan dinh gio"]}
    )
    listings = [
        {
            "id": 101,
            "title": "Nhà đẹp gần chợ",
            "description": "Vị trí Phan Đình Giót, phường An Phú.",
            "road_name": "",
        }
    ]

    result = audit_ward_fallbacks(
        listings,
        registry,
        city="THUẬN AN",
        ward="An Phú",
    )

    assert result["known_registry_missed"] == [
        {
            "candidate": "phan dinh giot",
            "affected_listing_count": 1,
            "sample_listing_ids": [101],
        }
    ]


def test_audit_requires_road_context_for_short_numbered_alias():
    registry = _registry({"canonical": "d 1", "aliases": ["d1"]})
    listings = [
        {
            "id": 102,
            "title": "Ngang 5m dài 20m",
            "description": "Kết cấu 1 trệt 1 lầu, ký hiệu D1 nội bộ.",
            "road_name": "",
        }
    ]

    result = audit_ward_fallbacks(
        listings,
        registry,
        city="THUẬN AN",
        ward="An Phú",
    )

    assert result["known_registry_missed"] == []


def test_audit_accepts_short_numbered_alias_with_explicit_road_context():
    registry = _registry({"canonical": "d 1", "aliases": ["d1"]})
    listings = [
        {
            "id": 103,
            "title": "Bán đất đường D1 KDC Việt Sing",
            "description": "Phường An Phú, Thuận An.",
            "road_name": "",
        }
    ]

    result = audit_ward_fallbacks(
        listings,
        registry,
        city="THUẬN AN",
        ward="An Phú",
    )

    assert result["known_registry_missed"] == [
        {
            "candidate": "d 1",
            "affected_listing_count": 1,
            "sample_listing_ids": [103],
        }
    ]


def test_audit_does_not_choose_an_ambiguous_registry_alias():
    registry = _registry(
        {"canonical": "duong so 22 thang 12", "aliases": ["duong so 22"]},
        {"canonical": "duong so 22", "aliases": ["duong so 22"]},
    )
    listings = [
        {
            "id": 104,
            "title": "Bán đất đường số 22",
            "description": "Phường An Phú, Thuận An.",
            "road_name": "",
        }
    ]

    result = audit_ward_fallbacks(
        listings,
        registry,
        city="THUẬN AN",
        ward="An Phú",
    )

    assert result["known_registry_missed"] == []
    assert result["ambiguous_registry_matches"] == [
        {
            "candidate": "duong so 22",
            "affected_listing_count": 1,
            "sample_listing_ids": [104],
        }
    ]


def test_audit_can_omit_listing_ids_from_privacy_safe_output():
    registry = _registry({"canonical": "phan dinh giot"})
    listings = [
        {
            "id": 105,
            "title": "Bán nhà Phan Đình Giót",
            "description": "Phường An Phú.",
            "road_name": "",
        }
    ]

    result = audit_ward_fallbacks(
        listings,
        registry,
        city="THUẬN AN",
        ward="An Phú",
        include_sample_ids=False,
    )

    assert result["known_registry_missed"] == [
        {
            "candidate": "phan dinh giot",
            "affected_listing_count": 1,
        }
    ]


def test_ward_fallback_cli_outputs_only_aggregates(monkeypatch, capsys):
    import cli.map_locations as map_cli

    registry = _registry({"canonical": "phan dinh giot"})
    monkeypatch.setattr(map_cli, "load_location_registry", lambda: registry)
    monkeypatch.setattr(
        map_cli,
        "load_ward_fallback_listings",
        lambda wards: [
            {
                "id": 901,
                "title": "Nhà Phan Đình Giót",
                "description": "An Phú",
                "road_name": "",
            }
        ],
    )

    payload = map_cli.cmd_map_location_ward_audit(
        Namespace(
            city="THUẬN AN",
            ward="An Phú",
            include_ward_alias=[],
        )
    )

    assert payload == json.loads(capsys.readouterr().out)
    assert payload["ward_fallback_listing_count"] == 1
    assert payload["known_registry_missed"] == [
        {"candidate": "phan dinh giot", "affected_listing_count": 1}
    ]
    assert "sample_listing_ids" not in json.dumps(payload)
    assert "Nhà Phan Đình Giót" not in json.dumps(payload, ensure_ascii=False)


def test_radar_parser_accepts_ward_fallback_audit_options():
    import radar

    args = radar.build_parser().parse_args(
        [
            "map-location-ward-audit",
            "--city",
            "THUẬN AN",
            "--ward",
            "An Phú",
            "--include-ward-alias",
            "An Phu",
        ]
    )

    assert args.cmd == "map-location-ward-audit"
    assert args.city == "THUẬN AN"
    assert args.ward == "An Phú"
    assert args.include_ward_alias == ["An Phu"]

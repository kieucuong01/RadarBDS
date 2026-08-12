import inspect
import json
from pathlib import Path

import pytest

from services.listing_location_resolver import (
    LocationRegistry,
    listing_location_signature,
    load_location_registry,
    normalize_location_token,
    normalize_road_token,
    resolve_listing_location,
)
from services.listing_map_context import extract_map_location_context


PHU_TAN_FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "phu_tan_map_ward_road_candidates.json"
)


def _road(*, lat=10.981, lng=106.689, landmark_keys=()):
    return {
        "lat": lat,
        "lng": lng,
        "accuracy_radius_m": 90,
        "label": "Theo tên đường ĐX 43, Phú Lợi",
        "source": "OpenStreetMap",
        "landmark_keys": list(landmark_keys),
    }


def _registry():
    return LocationRegistry(
        resolver_version="osm-test-v2",
        roads={
            ("THỦ DẦU MỘT", "phu loi", "dx 43"): (_road(),),
            ("THỦ DẦU MỘT", "phu loi", "duong so 35"): (
                _road(
                    lat=10.982,
                    lng=106.690,
                    landmark_keys=("tdc phu chanh b",),
                ),
                _road(
                    lat=10.983,
                    lng=106.691,
                    landmark_keys=("tdc phu chanh d",),
                ),
            ),
        },
        landmarks={
            ("THỦ DẦU MỘT", "phu loi", "tdc phu chanh b"): {
                "lat": 10.982,
                "lng": 106.690,
                "accuracy_radius_m": 140,
                "label": "Theo địa danh TĐC Phú Chánh B",
                "source": "OpenStreetMap",
            },
            ("THỦ DẦU MỘT", "phu loi", "tdc phu chanh d"): {
                "lat": 10.983,
                "lng": 106.691,
                "accuracy_radius_m": 140,
                "label": "Theo địa danh TĐC Phú Chánh D",
                "source": "OpenStreetMap",
            },
        },
        wards={
            ("THỦ DẦU MỘT", "phu loi"): {
                "lat": 10.984,
                "lng": 106.684,
                "label": "Theo trung tâm Phú Lợi",
                "source": "OpenStreetMap",
            }
        },
    )


def _resolve(text="", **extra):
    listing = {
        "id": extra.pop("id", 10),
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        "title": text,
        "description": "",
        "road_name": extra.pop("road_name", ""),
        **extra,
    }
    context = extract_map_location_context(
        listing["title"],
        listing["description"],
        listing["road_name"],
    )
    return resolve_listing_location(listing, _registry(), context)


def _load_phu_tan_fixture():
    return json.loads(PHU_TAN_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_resolution_precedence_exact_road_landmark_ward():
    exact = _resolve(source_lat=10.991, source_lng=106.701)
    road = _resolve(text="Mặt tiền DX43")
    landmark = _resolve(text="TĐC Phú Chánh D")
    nearby = _resolve(text="Cách DX43 100m")
    ward = _resolve(text="Đất đẹp dân cư đông")

    assert [
        item.location.precision for item in (exact, road, landmark, nearby, ward)
    ] == ["exact", "road", "landmark", "road", "ward"]
    assert nearby.location.relation == "near"


def test_nearby_and_direct_references_share_one_road_location_key():
    direct = _resolve(text="Mặt tiền DX43")
    nearby = _resolve(text="Cách DX43 100m")
    alley = _resolve(text="1 sẹc đường DX43")

    assert direct.location.precision == "road"
    assert nearby.location.precision == "road"
    assert alley.location.precision == "road"
    assert {
        direct.location.location_key,
        nearby.location.location_key,
        alley.location.location_key,
    } == {"road:thu-dau-mot:phu-loi:dx-43"}
    assert nearby.location.relation == "near"
    assert alley.location.relation == "alley"


def test_explicit_nearby_road_beats_ambiguous_generic_stored_ward_road():
    registry = _registry()
    registry = LocationRegistry(
        resolver_version=registry.resolver_version,
        roads={
            **registry.roads,
            ("THỦ DẦU MỘT", "phu loi", "phu loi"): (
                _road(lat=10.98, lng=106.66),
                _road(lat=10.99, lng=106.67),
            ),
        },
        landmarks=registry.landmarks,
        wards=registry.wards,
    )
    listing = {
        "id": 11,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        "title": "Nhà 1 sẹc đường DX43",
        "description": "",
        "road_name": "Phú Lợi",
    }
    context = extract_map_location_context(
        listing["title"], listing["description"], listing["road_name"]
    )

    result = resolve_listing_location(listing, registry, context)

    assert result.location.precision == "road"
    assert result.location.reference_road == "dx 43"
    assert result.location.relation == "alley"


def test_nearby_road_keeps_landmark_scope_without_creating_nearby_key():
    result = _resolve(
        text="Cách Đường số 35 100m, TĐC Phú Chánh B"
    )

    assert result.location.precision == "road"
    assert result.location.location_key == (
        "road:thu-dau-mot:phu-loi:duong-so-35:tdc-phu-chanh-b"
    )
    assert result.location.relation == "near"
    assert result.location.landmark_key == "tdc phu chanh b"


def test_ambiguous_road_uses_honest_ward_until_landmark_disambiguates():
    ambiguous = _resolve(text="Mặt tiền Đường số 35")
    scoped = _resolve(text="Đường số 35, TĐC Phú Chánh D")

    assert ambiguous.location.precision == "ward"
    assert ambiguous.location.resolution_status == "ambiguous"
    assert ambiguous.issue.status == "ambiguous"
    assert scoped.location.precision == "road"
    assert scoped.location.landmark_key == "tdc phu chanh d"
    assert (scoped.location.lat, scoped.location.lng) == (10.983, 106.691)


def test_road_landmark_conflict_does_not_silently_choose_road():
    registry = _registry()
    registry = LocationRegistry(
        resolver_version=registry.resolver_version,
        roads={
            **registry.roads,
            ("THỦ DẦU MỘT", "phu loi", "dx 43"): (
                _road(landmark_keys=("tdc phu chanh b",)),
            ),
        },
        landmarks=registry.landmarks,
        wards=registry.wards,
    )
    listing = {
        "id": 11,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        "title": "Mặt tiền DX43, TĐC Phú Chánh D",
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(listing["title"], "")

    result = resolve_listing_location(listing, registry, context)

    assert result.location.precision == "ward"
    assert result.location.resolution_reason == "road_landmark_conflict"
    assert result.issue.resolution_note == "road_landmark_conflict"


def test_unique_road_keeps_unmatched_landmark_in_coverage_queue():
    result = _resolve(text="Mặt tiền DX43, TĐC Khu Mới")

    assert result.location.precision == "road"
    assert result.issue.status == "not_found"
    assert result.issue.landmark_candidate == "tdc khu moi"
    assert result.issue.resolution_note == "landmark_not_found"


def test_ambiguous_landmark_uses_honest_ward_and_enters_coverage():
    registry = _registry()
    first = registry.landmarks[
        ("THỦ DẦU MỘT", "phu loi", "tdc phu chanh b")
    ]
    registry = LocationRegistry(
        resolver_version=registry.resolver_version,
        roads=registry.roads,
        landmarks={
            **registry.landmarks,
            ("THỦ DẦU MỘT", "phu loi", "tdc khu moi"): (
                first,
                {**first, "lat": 10.991, "lng": 106.699},
            ),
        },
        wards=registry.wards,
    )
    listing = {
        "id": 16,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        "title": "TĐC Khu Mới",
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(listing["title"], "")

    result = resolve_listing_location(listing, registry, context)

    assert result.location.precision == "ward"
    assert result.location.resolution_status == "ambiguous"
    assert result.issue.status == "ambiguous"
    assert result.issue.resolution_note == "ambiguous_landmark"


def test_valid_source_coordinate_wins_over_road_and_ward():
    result = _resolve(
        id=77,
        road_name="ĐX 43",
        source_lat=10.991,
        source_lng=106.701,
        source="facebook",
    )

    resolved = result.location
    assert resolved.listing_id == 77
    assert resolved.precision == "exact"
    assert resolved.location_key == "exact:77"
    assert (resolved.lat, resolved.lng) == (10.991, 106.701)
    assert result.issue is None


def test_road_punctuation_variants_resolve_to_one_deterministic_point():
    locations = [
        _resolve(road_name=road_name).location
        for road_name in ("ĐX-43", "ĐX 43", "đx.43", "DX043", "Đường ĐX 43")
    ]

    assert {item.precision for item in locations} == {"road"}
    assert {(item.lat, item.lng) for item in locations} == {(10.981, 106.689)}
    assert {item.location_key for item in locations} == {
        "road:thu-dau-mot:phu-loi:dx-43"
    }
    assert len({item.signature for item in locations}) == 1


def test_phu_tan_all_listings_fixture_moves_road_bearing_rows_out_of_ward_precision():
    registry = load_location_registry()
    fixtures = _load_phu_tan_fixture()
    failures = []

    for listing in fixtures:
        context = extract_map_location_context(
            listing.get("title", ""),
            listing.get("description", ""),
            listing.get("road_name", ""),
        )
        result = resolve_listing_location(listing, registry=registry, context=context)
        if not result.location or result.location.precision == "ward":
            failures.append(
                (
                    listing["id"],
                    getattr(result.issue, "resolution_note", ""),
                    getattr(result.issue, "road_candidate", ""),
                )
            )

    assert len(fixtures) == 65
    assert len(fixtures) - len(failures) >= 60, failures[:10]


def test_phu_tan_false_positive_road_candidates_do_not_become_roads():
    registry = load_location_registry()

    for index, phrase in enumerate(
        ("kinh doanh", "phuong binh", "tay anh em oi", "duong 5m"),
        start=1,
    ):
        listing = {
            "id": 920000 + index,
            "ward": "Phú Tân",
            "title": f"Nhà {phrase}",
            "description": "",
            "road_name": "",
        }
        result = resolve_listing_location(listing, registry=registry)

        assert not result.location or result.location.precision != "road"


def test_map_resolver_treats_phu_chanh_as_phu_tan_without_mutating_listing():
    registry = load_location_registry()
    listing = {
        "id": 910001,
        "ward": "Phú Chánh",
        "title": "Đường số 35 TĐC Phú Chánh",
        "description": "",
        "road_name": "",
    }

    context = extract_map_location_context(
        listing["title"],
        listing["description"],
        listing["road_name"],
    )
    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision in {"road", "landmark"}
    assert "phu-tan" in result.location.location_key
    assert listing["ward"] == "Phú Chánh"


def test_number_letter_roads_normalize_to_numbered_road_when_context_says_road():
    assert normalize_road_token("110B") == "duong so 110 b"
    assert normalize_road_token("110 b") == "duong so 110 b"
    assert normalize_road_token("Đường 11B") == "duong so 11 b"
    assert normalize_road_token("5m") == "5 m"


def test_ambiguous_phu_tan_duong_so_84_uses_aggregate_road():
    registry = load_location_registry()
    listing = {
        "id": 910084,
        "ward": "Phú Tân",
        "title": "Đường số 84 TĐC Phú Chánh D",
        "description": "",
        "road_name": "",
    }

    context = extract_map_location_context(
        listing["title"],
        listing["description"],
        listing["road_name"],
    )
    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == "road"
    assert "duong-so-84" in result.location.location_key


def test_phu_tan_context_road_is_used_when_stored_road_name_is_noise():
    registry = load_location_registry()
    listing = {
        "id": 910104,
        "city": "TH\u1ee6 D\u1ea6U M\u1ed8T",
        "ward": "Ph\u00fa T\u00e2n",
        "title": "Duong 104 TDC Phu Chanh D",
        "description": "",
        "road_name": "Gon Le",
    }
    context = extract_map_location_context(
        listing["title"], listing["description"], listing["road_name"]
    )

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == "road"
    assert "duong-so-104" in result.location.location_key


def test_phu_tan_context_named_road_is_used_when_stored_road_name_is_noise():
    registry = load_location_registry()
    listing = {
        "id": 910105,
        "city": "TH\u1ee6 D\u1ea6U M\u1ed8T",
        "ward": "Ph\u00fa T\u00e2n",
        "title": "Mat tien Dien Bien Phu tao luc 1",
        "description": "",
        "road_name": "Kinh Doanh",
    }
    context = extract_map_location_context(
        listing["title"], listing["description"], listing["road_name"]
    )

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == "road"
    assert "dien-bien-phu" in result.location.location_key


@pytest.mark.parametrize(
    ("ward", "road", "expected_slug"),
    [
        ("T\u00e2n An", "Nguyen Chi Thanh", "nguyen-chi-thanh"),
        ("Ph\u00fa M\u1ef9", "Huynh Van Luy", "huynh-van-luy"),
        ("Hi\u1ec7p Th\u00e0nh", "Pham Ngoc Thach", "pham-ngoc-thach"),
        ("Ph\u00fa H\u00f2a", "Le Hong Phong", "le-hong-phong"),
        ("Ph\u00fa H\u00f2a", "Nguyen Thi Minh Khai", "nguyen-thi-minh-khai"),
        ("Ph\u00fa H\u00f2a", "30/4", "duong-so-30-thang-4"),
        ("Ph\u00fa M\u1ef9", "DX1", "dx-1"),
        ("Ph\u00fa M\u1ef9", "N1", "n-1"),
        ("Ph\u00fa M\u1ef9", "N4", "n-4"),
        ("Ph\u00fa M\u1ef9", "Dien Bien Phu", "dien-bien-phu"),
        ("Ph\u00fa L\u1ee3i", "Le Hong Phong", "le-hong-phong"),
        ("Ph\u00fa L\u1ee3i", "Nguyen Binh", "nguyen-binh"),
        ("Ph\u00fa L\u1ee3i", "Pham Thi Tan", "pham-thi-tan"),
        ("Ph\u00fa L\u1ee3i", "Le Thi Trung", "le-thi-trung"),
        ("Ph\u00fa L\u1ee3i", "Huynh Van Nghe", "huynh-van-nghe"),
        ("Hi\u1ec7p Th\u00e0nh", "Hoang Hoa Tham", "hoang-hoa-tham"),
        ("Hi\u1ec7p Th\u00e0nh", "Pham Ngu Lao", "pham-ngu-lao"),
        ("Hi\u1ec7p Th\u00e0nh", "Dai Lo Binh Duong", "dai-lo-binh-duong"),
        ("Hi\u1ec7p Th\u00e0nh", "Nguyen Binh", "nguyen-binh"),
        ("Hi\u1ec7p Th\u00e0nh", "Nguyen Duc Thuan", "nguyen-duc-thuan"),
        ("Hi\u1ec7p Th\u00e0nh", "Truong Dinh", "truong-dinh"),
        ("Ch\u00e1nh Ngh\u0129a", "Bui Quoc Khanh", "bui-quoc-khanh"),
        ("\u0110\u1ecbnh H\u00f2a", "DX 71", "dx-71"),
        ("\u0110\u1ecbnh H\u00f2a", "Dai Lo Binh Duong", "dai-lo-binh-duong"),
        ("Hi\u1ec7p An", "Dai Lo Binh Duong", "dai-lo-binh-duong"),
        ("Ph\u00fa H\u00f2a", "Dai Lo Binh Duong", "dai-lo-binh-duong"),
        ("\u0110\u1ecbnh H\u00f2a", "Nguyen Van Thanh", "nguyen-van-thanh"),
        ("Ph\u00fa L\u1ee3i", "My Phuoc Tan Van", "my-phuoc-tan-van"),
        ("Ph\u00fa L\u1ee3i", "Hoang Hoa Tham", "hoang-hoa-tham"),
        ("Hi\u1ec7p Th\u00e0nh", "QL13", "dai-lo-binh-duong"),
        ("Hi\u1ec7p Th\u00e0nh", "Qu\u1ed1c l\u1ed9 13", "dai-lo-binh-duong"),
        ("Ph\u00fa Th\u1ecd", "Quoc Lo 13", "dai-lo-binh-duong"),
        ("Ch\u00e1nh Ngh\u0129a", "Nguyen Tri Phuong", "nguyen-tri-phuong"),
        ("T\u00e2n An", "Mac Dinh Chi", "mac-dinh-chi"),
        ("\u0110\u1ecbnh H\u00f2a", "DX 80", "dx-80"),
        ("Hi\u1ec7p An", "DX 90", "dx-90"),
        ("T\u01b0\u01a1ng B\u00ecnh Hi\u1ec7p", "DX 142", "dx-142"),
        ("T\u01b0\u01a1ng B\u00ecnh Hi\u1ec7p", "DX 143", "dx-143"),
        ("T\u01b0\u01a1ng B\u00ecnh Hi\u1ec7p", "DX 145", "dx-145"),
        ("Ph\u00fa T\u00e2n", "Dien Bien Phu", "dien-bien-phu"),
        ("Ph\u00fa T\u00e2n", "Nguyen Van Linh", "nguyen-van-linh"),
        ("Ch\u00e1nh Ngh\u0129a", "30/4", "ba-muoi-thang-tu"),
        ("Ch\u00e1nh Ngh\u0129a", "CMT8", "cach-mang-thang-tam"),
        ("Ch\u00e1nh Ngh\u0129a", "Phan Dinh Giot", "phan-dinh-giot"),
        ("Ch\u00e1nh Ngh\u0129a", "Ngo Gia Tu", "ngo-gia-tu"),
        ("\u0110\u1ecbnh H\u00f2a", "DX64", "dx-64"),
        ("\u0110\u1ecbnh H\u00f2a", "My Phuoc Tan Van", "my-phuoc-tan-van"),
        ("\u0110\u1ecbnh H\u00f2a", "Vo Van Kiet", "vo-van-kiet"),
        ("Ch\u00e1nh M\u1ef9", "Nguyen Van Long", "nguyen-van-long"),
        ("Ch\u00e1nh M\u1ef9", "Huynh Van Cu", "huynh-van-cu"),
        ("T\u00e2n An", "Huynh Thi Hieu", "huynh-thi-hieu"),
        ("T\u00e2n An", "Phan Dang Luu", "phan-dang-luu"),
        ("T\u00e2n An", "Le Chi Dan", "le-chi-dan"),
        ("Ph\u00fa Th\u1ecd", "Nguyen Huu Canh", "nguyen-huu-canh"),
        ("Ph\u00fa Th\u1ecd", "Phan Boi Chau", "phan-boi-chau"),
        ("Ph\u00fa Th\u1ecd", "Tran Binh Trong", "tran-binh-trong"),
        ("Ph\u00fa Th\u1ecd", "CMT8", "cach-mang-thang-tam"),
        ("Ph\u00fa Th\u1ecd", "30/4", "duong-so-30-thang-4"),
        ("Hi\u1ec7p An", "Bui Ngoc Thu", "bui-ngoc-thu"),
        ("Hi\u1ec7p An", "Le Chi Dan", "le-chi-dan"),
        ("Ph\u00fa C\u01b0\u1eddng", "CMT8", "cach-mang-thang-tam"),
        ("Ph\u00fa C\u01b0\u1eddng", "Huynh Van Cu", "huynh-van-cu"),
        ("Ph\u00fa C\u01b0\u1eddng", "Nguyen An Ninh", "nguyen-an-ninh"),
        ("Ph\u00fa C\u01b0\u1eddng", "Yersin", "bac-si-yersin"),
        ("H\u00f2a Ph\u00fa", "D8", "d-8"),
    ],
)
def test_common_thu_dau_mot_multi_segment_roads_use_aggregate_road(
    ward, road, expected_slug
):
    registry = load_location_registry()
    listing = {
        "id": 920000,
        "city": "TH\u1ee6 D\u1ea6U M\u1ed8T",
        "ward": ward,
        "title": f"M\u1eb7t ti\u1ec1n {road}",
        "description": "",
        "road_name": road,
    }
    context = extract_map_location_context(
        listing["title"], listing["description"], listing["road_name"]
    )

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.issue is None
    assert result.location
    assert result.location.precision == "road"
    assert expected_slug in result.location.location_key


@pytest.mark.parametrize(
    ("title", "expected_slug"),
    [
        ("Mat tien DX140 Tan An", "dx-140"),
        ("Mat tien DX120 Tan An", "dx-120"),
        ("Mat tien DX135 Tan An", "dx-135"),
        ("Mat tien DX141 Tan An", "dx-141"),
        ("Mat tien DX108 Tan An", "dx-108"),
        ("Mat tien DX117 Tan An", "dx-117"),
        ("Mat tien DX109 Tan An", "dx-109"),
        ("Mat tien Dai lo Binh Duong Tan An", "dai-lo-binh-duong"),
        ("Duong so 1 Khu tai dinh cu Tan An", "duong-so-1"),
        ("Duong so 2 Khu tai dinh cu Tan An", "duong-so-2"),
        ("Duong so 3 Khu tai dinh cu Tan An", "duong-so-3"),
        ("Duong so 5 Khu tai dinh cu Tan An", "duong-so-5"),
        ("Duong so 18 Khu tai dinh cu Tan An", "duong-so-18"),
        ("Duong so 8 Phuong Phu An", "duong-so-8"),
        ("Mat tien Bui Ngoc Thu Tan An", "bui-ngoc-thu"),
    ],
)
def test_tan_an_evidence_backed_roads_resolve_out_of_ward_center(
    title, expected_slug
):
    registry = load_location_registry()
    listing = {
        "id": 920100,
        "city": "TH\u1ee6 D\u1ea6U M\u1ed8T",
        "ward": "T\u00e2n An",
        "title": title,
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(title, "", "")

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == "road"
    assert expected_slug in result.location.location_key


def test_tan_an_resettlement_landmark_resolves_out_of_ward_center():
    registry = load_location_registry()
    listing = {
        "id": 920101,
        "city": "TH\u1ee6 D\u1ea6U M\u1ed8T",
        "ward": "T\u00e2n An",
        "title": "Khu tai dinh cu Tan An Thu Dau Mot",
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(listing["title"], "", "")

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == "landmark"
    assert "tdc-tan-an" in result.location.location_key


@pytest.mark.parametrize(
    ("title", "expected_slug"),
    [
        ("Mat tien DX98 Hiep An", "dx-98"),
        ("Mat tien DX101 Hiep An", "dx-101"),
        ("Mat tien DX102 Hiep An", "dx-102"),
        ("Mat tien DX103 Hiep An", "dx-103"),
        ("Mat tien DX105 Hiep An", "dx-105"),
        ("Mat tien DX107 Hiep An", "dx-107"),
        ("Mat tien Nguyen Duc Canh Hiep An", "nguyen-duc-canh"),
        ("Cach Duc Canh 80m Hiep An", "nguyen-duc-canh"),
    ],
)
def test_hiep_an_evidence_backed_roads_resolve_out_of_ward_center(
    title, expected_slug
):
    registry = load_location_registry()
    listing = {
        "id": 920102,
        "city": "TH\u1ee6 D\u1ea6U M\u1ed8T",
        "ward": "Hi\u1ec7p An",
        "title": title,
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(title, "", "")

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == "road"
    assert expected_slug in result.location.location_key


@pytest.mark.parametrize(
    ("title", "expected_precision", "expected_slug"),
    [
        ("Dat TDC Tuong Binh Hiep", "landmark", "tdc-tuong-binh-hiep"),
        ("Dat KDC Tuong Binh Hiep", "landmark", "tdc-tuong-binh-hiep"),
        ("Mat tien DX144 Tuong Binh Hiep", "road", "dx-144"),
        ("Mat tien DX146 Tuong Binh Hiep", "road", "dx-146"),
        ("Mat tien DX149 Tuong Binh Hiep", "road", "dx-149"),
        ("Mat tien DX150 Tuong Binh Hiep", "road", "dx-150"),
        ("Mat tien Phan Dang Luu Tuong Binh Hiep", "road", "phan-dang-luu"),
        ("Cach Dai Lo Binh Duong 200m Tuong Binh Hiep", "road", "dai-lo-binh-duong"),
    ],
)
def test_tuong_binh_hiep_evidence_backed_locations_resolve(
    title, expected_precision, expected_slug
):
    registry = load_location_registry()
    listing = {
        "id": 920103,
        "city": "THỦ DẦU MỘT",
        "ward": "Tương Bình Hiệp",
        "title": title,
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(title, "", "")

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == expected_precision
    assert expected_slug in result.location.location_key


@pytest.mark.parametrize(
    ("title", "expected_precision", "expected_slug"),
    [
        ("Mat tien DX74 Dinh Hoa", "road", "dx-74"),
        ("Mat tien DX77 Dinh Hoa", "road", "dx-77"),
        ("Mat tien DX84 Dinh Hoa", "road", "dx-84"),
        ("Duong so 11B TDC Dinh Hoa", "road", "duong-so-11-b"),
        ("Duong so 5B TDC Dinh Hoa", "road", "duong-so-5-b"),
        ("Duong so 36 TDC Dinh Hoa", "road", "duong-so-36"),
        ("Dat TDC Dinh Hoa lien ke khu hanh chinh", "landmark", "tdc-dinh-hoa"),
        ("Dat TDC Thanh Le gan BV 1500", "landmark", "tdc-thanh-le"),
        (
            "Du an Becamex Dinh Hoa tong 11.500 can ho",
            "landmark",
            "noxh-becamex-dinh-hoa",
        ),
    ],
)
def test_dinh_hoa_evidence_backed_locations_resolve(
    title, expected_precision, expected_slug
):
    registry = load_location_registry()
    listing = {
        "id": 920104,
        "city": "TH\u1ee6 D\u1ea6U M\u1ed8T",
        "ward": "\u0110\u1ecbnh H\u00f2a",
        "title": title,
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(title, "", "")

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == expected_precision
    assert expected_slug in result.location.location_key


@pytest.mark.parametrize(
    ("title", "expected_precision", "expected_slug"),
    [
        ("Mặt tiền Đường số 1 Chánh Mỹ", "road", "duong-so-1"),
        ("Mặt tiền Đường số 4 Chánh Mỹ", "road", "duong-so-4"),
        ("Mặt tiền Đường số 5 KĐT Chánh Mỹ", "road", "duong-so-5"),
        ("Đường số 5 gần Chợ Chánh Mỹ", "road", "duong-so-5"),
        ("Đường N3 KĐT sinh thái Chánh Mỹ", "road", "n-3"),
        ("Cách Cách Mạng Tháng Tám 100m", "road", "cach-mang-thang-tam"),
        ("Đất TĐC Chánh Mỹ", "landmark", "tdc-chanh-my"),
        ("Khu đô thị HUD Chánh Mỹ", "landmark", "khu-do-thi-chanh-my"),
        ("Nhà gần Chợ Chánh Mỹ", "landmark", "cho-chanh-my"),
        ("Đất cách Phố đi bộ Bạch Đằng", "landmark", "pho-di-bo-bach-dang"),
    ],
)
def test_chanh_my_evidence_backed_locations_resolve(
    title, expected_precision, expected_slug
):
    registry = load_location_registry()
    listing = {
        "id": 920105,
        "city": "THỦ DẦU MỘT",
        "ward": "Chánh Mỹ",
        "title": title,
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(title, "", "")

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == expected_precision
    assert expected_slug in result.location.location_key


@pytest.mark.parametrize(
    ("title", "expected_precision", "expected_slug"),
    [
        ("Mặt tiền D10 TĐC Phú Mỹ", "road", "d-10"),
        ("Mặt tiền D8 TĐC Phú Mỹ", "road", "d-8"),
        ("Mặt tiền D11 TĐC Phú Mỹ", "road", "d-11"),
        ("Mặt tiền D12 TĐC Phú Mỹ", "road", "d-12"),
        ("Đường N16 TĐC Phú Mỹ", "road", "n-16"),
        ("Đất TĐC Phú Mỹ KP1", "landmark", "tdc-phu-my"),
    ],
)
def test_phu_my_evidence_backed_locations_resolve(
    title, expected_precision, expected_slug
):
    registry = load_location_registry()
    listing = {
        "id": 920106,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Mỹ",
        "title": title,
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(title, "", "")

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == expected_precision
    assert expected_slug in result.location.location_key


@pytest.mark.parametrize(
    ("title", "expected_slug"),
    [
        ("Nhà xẹc phố Bạch Đằng", "bach-dang"),
        ("Mặt tiền Nguyễn Văn Bé, nhà 1 trệt", "nguyen-van-be"),
        ("Mặt tiền Phan Đình Giót", "phan-dinh-giot"),
        ("Đường DX42 Phú Cường", "dx-42"),
        ("1/ đường Ngô Quyền, hẻm xe hơi", "ngo-quyen"),
        ("1/ Thích Quảng Đức, hỗ trợ vay", "thich-quang-duc"),
    ],
)
def test_phu_cuong_evidence_backed_roads_resolve(title, expected_slug):
    registry = load_location_registry()
    listing = {
        "id": 920107,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Cường",
        "title": title,
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(title, "", "")

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == "road"
    assert expected_slug in result.location.location_key


def test_explicit_listing_text_coordinate_resolves_as_exact():
    registry = load_location_registry()
    listing = {
        "id": 920108,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Cường",
        "title": "Nhà đất Phú Cường",
        "description": "Vị trí: 10.982451,106.666357",
        "road_name": "",
    }
    context = extract_map_location_context(
        listing["title"], listing["description"], ""
    )

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == "exact"
    assert result.location.lat == pytest.approx(10.982451)
    assert result.location.lng == pytest.approx(106.666357)


@pytest.mark.parametrize(
    ("title", "expected_precision", "expected_slug"),
    [
        ("Nhà KDC Phú Hòa 1", "landmark", "kdc-phu-hoa-1"),
        ("Nhà KDC Phú Hòa 2", "landmark", "kdc-phu-hoa-2"),
        ("Nhà KDC Hoàng Nam 2", "landmark", "kdc-hoang-nam-2"),
        ("Nhà hẻm 385 Phú Hòa", "road", "duong-so-385"),
        ("Nhà hẻm 453 Phú Hòa", "road", "duong-so-453"),
        ("Mặt tiền Trần Văn Ơn", "road", "tran-van-on"),
        ("Gần Mỹ Phước Tân Vạn", "road", "my-phuoc-tan-van"),
    ],
)
def test_phu_hoa_evidence_backed_locations_resolve(
    title, expected_precision, expected_slug
):
    registry = load_location_registry()
    listing = {
        "id": 920109,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Hòa",
        "title": title,
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(title, "", "")

    result = resolve_listing_location(listing, registry=registry, context=context)

    assert result.location
    assert result.location.precision == expected_precision
    assert expected_slug in result.location.location_key


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mặt tiền Dx120 Tân An", "dx 120"),
        ("Mặt tiền DX096 giá tốt", "dx 96"),
        ("Đường Dx 092 khu dân cư đông", "dx 92"),
        ("Đất Đường 88 khu TĐC Phú Chánh D Phường Phú Tân", "duong so 88"),
    ],
)
def test_map_context_extracts_common_broker_road_phrases(text, expected):
    context = extract_map_location_context(text, "", "")

    assert context.direct_road == expected


def test_unknown_road_uses_ward_and_records_not_found_issue():
    result = _resolve(road_name="Đường chưa có")

    assert result.location.precision == "ward"
    assert result.location.resolution_status == "not_found"
    assert result.issue.status == "not_found"
    assert result.issue.road_candidate == "duong chua co"


def test_unknown_ward_returns_issue_without_location():
    listing = {
        "id": 13,
        "city": "THỦ DẦU MỘT",
        "ward": "Không rõ",
        "title": "Mặt tiền DX43",
        "description": "",
        "road_name": "",
    }
    context = extract_map_location_context(listing["title"], "")
    result = resolve_listing_location(listing, _registry(), context)

    assert result.location is None
    assert result.issue.status == "not_found"


def test_signature_and_coordinates_are_stable_without_randomness():
    listing = {
        "id": 14,
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Lợi",
        "road_name": "ĐX 43",
    }
    context = extract_map_location_context("", "", "ĐX 43")

    first = resolve_listing_location(listing, _registry(), context)
    second = resolve_listing_location(dict(listing), _registry(), context)

    assert first == second
    assert listing_location_signature(
        listing, context, "osm-test-v2"
    ) == listing_location_signature(dict(listing), context, "osm-test-v2")
    assert "import random" not in inspect.getsource(resolve_listing_location)
    assert normalize_location_token(" ĐX.  43 ") == "dx 43"
    assert normalize_road_token("DX0143") == "dx 143"
    assert normalize_road_token("Đường ĐX 143") == "dx 143"
    assert normalize_road_token("Đường 88") == "duong so 88"


def test_location_normalizer_handles_vietnamese_d_variants():
    assert normalize_location_token("Phan \u0110\u0103ng L\u01b0u") == "phan dang luu"
    assert normalize_location_token("Phan \u00d0\u0103ng L\u01b0u") == "phan dang luu"


def test_registry_loader_preserves_road_ambiguity_and_landmark_aliases(tmp_path):
    ward_path = tmp_path / "wards.json"
    road_path = tmp_path / "roads.json"
    landmark_path = tmp_path / "landmarks.json"
    ward_path.write_text(
        json.dumps(
            {
                "resolver_version": "v2",
                "wards": [
                    {
                        "city": "THỦ DẦU MỘT",
                        "normalized_ward": "phu loi",
                        "lat": 10.98,
                        "lng": 106.68,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    road_path.write_text(
        json.dumps(
            {
                "resolver_version": "v2",
                "roads": [
                    {
                        "city": "THỦ DẦU MỘT",
                        "normalized_ward": "phu loi",
                        "normalized_road": "duong so 35",
                        "aliases": ["duong 35"],
                        "lat": 10.98,
                        "lng": 106.68,
                    },
                    {
                        "city": "THỦ DẦU MỘT",
                        "normalized_ward": "phu loi",
                        "normalized_road": "duong so 35",
                        "aliases": ["duong 35"],
                        "lat": 10.99,
                        "lng": 106.69,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    landmark_path.write_text(
        json.dumps(
            {
                "resolver_version": "v2",
                "landmarks": [
                    {
                        "city": "THỦ DẦU MỘT",
                        "normalized_ward": "phu loi",
                        "normalized_landmark": "tdc phu chanh b",
                        "aliases": ["tai dinh cu phu chanh b"],
                        "lat": 10.98,
                        "lng": 106.68,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = load_location_registry(
        ward_path=ward_path,
        road_path=road_path,
        landmark_path=landmark_path,
    )

    assert len(
        registry.roads[("THỦ DẦU MỘT", "phu loi", "duong so 35")]
    ) == 2
    assert (
        "THỦ DẦU MỘT",
        "phu loi",
        "tai dinh cu phu chanh b",
    ) in registry.landmarks


def test_registry_loader_rejects_mismatched_landmark_version(tmp_path):
    for name, content in {
        "wards.json": {"resolver_version": "v2", "wards": []},
        "roads.json": {"resolver_version": "v2", "roads": []},
        "landmarks.json": {"resolver_version": "old", "landmarks": []},
    }.items():
        (tmp_path / name).write_text(json.dumps(content), encoding="utf-8")

    with pytest.raises(ValueError, match="versions do not match"):
        load_location_registry(
            ward_path=tmp_path / "wards.json",
            road_path=tmp_path / "roads.json",
            landmark_path=tmp_path / "landmarks.json",
        )

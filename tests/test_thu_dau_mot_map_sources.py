import copy
import hashlib
import json
from pathlib import Path

import pytest
from shapely.ops import unary_union

from map_products.geometry import build_normalized_layers
from map_products.models import (
    MapPoint,
    MapSource,
    load_neighborhood_points,
    load_product_spec,
    load_source_registry,
)
from map_products.sources import _http_get, fetch_source_snapshots


ROOT = Path(__file__).resolve().parents[1]


def test_thu_dau_mot_product_has_exact_units_and_price():
    spec = load_product_spec(
        ROOT / "config/map_products/thu_dau_mot_product.json"
    )
    assert spec.slug == "thu-dau-mot-map-bundle"
    assert spec.version == "1.0"
    assert spec.price_vnd == 99_000
    assert spec.formats == ("pdf", "svg", "kml")
    assert set(spec.legacy_wards) == {
        "Chánh Mỹ", "Chánh Nghĩa", "Định Hòa", "Hiệp An", "Hiệp Thành",
        "Hòa Phú", "Phú Cường", "Phú Hòa", "Phú Lợi", "Phú Mỹ",
        "Phú Tân", "Phú Thọ", "Tân An", "Tương Bình Hiệp",
    }
    assert set(spec.current_wards) == {
        "Thủ Dầu Một", "Phú Lợi", "Chánh Hiệp", "Bình Dương", "Phú An",
    }


def test_every_source_has_license_and_snapshot_contract():
    sources = load_source_registry(
        ROOT / "config/map_products/thu_dau_mot_sources.json"
    )
    assert {"legacy_boundaries", "current_boundaries", "osm_detail", "font"} <= {
        source.key for source in sources
    }
    assert all(source.license_name and source.license_url for source in sources)
    assert all(
        source.snapshot_strategy
        in {"fixed_url", "dated_query", "repo_snapshot"}
        for source in sources
    )


def test_neighborhoods_are_named_points_not_claimed_boundaries():
    points = load_neighborhood_points(
        ROOT / "config/map_products/thu_dau_mot_neighborhoods.geojson"
    )
    assert points
    assert all(point.geometry_type == "Point" for point in points)
    assert all(
        point.name and point.source and point.confidence in {"high", "medium"}
        for point in points
    )


def _neighborhood_document() -> dict:
    return json.loads(
        (ROOT / "config/map_products/thu_dau_mot_neighborhoods.geojson").read_text(
            encoding="utf-8"
        )
    )


def _write_neighborhood_document(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "neighborhoods.geojson"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_neighborhood_loader_rejects_polygon_geometry(tmp_path: Path):
    document = _neighborhood_document()
    document["features"][0]["geometry"] = {
        "type": "Polygon",
        "coordinates": [[[106.65, 10.97], [106.66, 10.97], [106.65, 10.97]]],
    }

    with pytest.raises(ValueError, match="Point geometry"):
        load_neighborhood_points(_write_neighborhood_document(tmp_path, document))


def test_neighborhood_loader_rejects_boundary_claims(tmp_path: Path):
    document = _neighborhood_document()
    document["features"][0]["properties"]["boundary_claim"] = True

    with pytest.raises(ValueError, match="boundary_claim must be false"):
        load_neighborhood_points(_write_neighborhood_document(tmp_path, document))


@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_neighborhood_loader_rejects_unknown_or_missing_properties(
    tmp_path: Path, mutation: str
):
    document = _neighborhood_document()
    properties = document["features"][0]["properties"]
    if mutation == "unknown":
        properties["unreviewed"] = "value"
    else:
        del properties["source_url"]

    with pytest.raises(ValueError, match="invalid keys"):
        load_neighborhood_points(_write_neighborhood_document(tmp_path, document))


def test_neighborhood_loader_rejects_invalid_coordinates(tmp_path: Path):
    document = _neighborhood_document()
    document["features"][0]["geometry"]["coordinates"][0] = 181

    with pytest.raises(ValueError, match="out of range"):
        load_neighborhood_points(_write_neighborhood_document(tmp_path, document))


def test_neighborhood_loader_rejects_duplicate_names(tmp_path: Path):
    document = _neighborhood_document()
    document["features"].append(copy.deepcopy(document["features"][0]))

    with pytest.raises(ValueError, match="duplicate names"):
        load_neighborhood_points(_write_neighborhood_document(tmp_path, document))


@pytest.fixture
def product_spec():
    return load_product_spec(ROOT / "config/map_products/thu_dau_mot_product.json")


def _square_feature(name: str, lon: float, lat: float, size: float = 0.004) -> dict:
    return {
        "type": "Feature",
        "properties": {"name": name},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [lon, lat],
                [lon + size, lat],
                [lon + size, lat + size],
                [lon, lat + size],
                [lon, lat],
            ]],
        },
    }


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def source_payloads(tmp_path: Path, product_spec):
    legacy_features = [
        _square_feature(
            name,
            106.63 + (index % 5) * 0.006,
            10.96 + (index // 5) * 0.006,
        )
        for index, name in enumerate(product_spec.legacy_wards)
    ]
    current_features = [
        _square_feature(name, 106.62 + index * 0.015, 10.95, 0.012)
        for index, name in enumerate(product_spec.current_wards)
    ]
    details = {
        "version": 0.6,
        "elements": [
            {
                "type": "way",
                "id": 1,
                "tags": {"highway": "primary", "name": "Đại lộ Bình Dương"},
                "geometry": [
                    {"lon": 106.625, "lat": 10.962},
                    {"lon": 106.638, "lat": 10.962},
                ],
            },
            {
                "type": "way",
                "id": 2,
                "tags": {"highway": "residential", "name": "Đường nội bộ"},
                "geometry": [
                    {"lon": 106.631, "lat": 10.9605},
                    {"lon": 106.633, "lat": 10.9635},
                ],
            },
            {
                "type": "way",
                "id": 3,
                "tags": {"highway": "secondary", "name": "Đường ngoài"},
                "geometry": [
                    {"lon": 106.62, "lat": 11.2},
                    {"lon": 106.7, "lat": 11.2},
                ],
            },
            {
                "type": "way",
                "id": 4,
                "tags": {"waterway": "river", "name": "Sông Sài Gòn"},
                "geometry": [
                    {"lon": 106.625, "lat": 10.961},
                    {"lon": 106.638, "lat": 10.961},
                ],
            },
            {
                "type": "node",
                "id": 5,
                "tags": {"amenity": "marketplace", "name": "Chợ Thủ Dầu Một"},
                "lon": 106.632,
                "lat": 10.962,
            },
            {
                "type": "node",
                "id": 6,
                "tags": {"amenity": "marketplace", "name": "chợ thủ dầu một"},
                "lon": 106.63205,
                "lat": 10.96205,
            },
            {
                "type": "node",
                "id": 7,
                "tags": {"tourism": "attraction"},
                "lon": 106.632,
                "lat": 10.962,
            },
        ],
    }
    return {
        "legacy_boundaries": _write_json(
            tmp_path / "legacy.json",
            {"type": "FeatureCollection", "features": legacy_features},
        ),
        "current_boundaries": _write_json(
            tmp_path / "current.json",
            {"type": "FeatureCollection", "features": current_features},
        ),
        "osm_detail": _write_json(tmp_path / "detail.json", details),
    }


def _sample_neighborhoods() -> tuple[MapPoint, ...]:
    return (
        MapPoint(
            name="Chợ Thủ Dầu Một",
            lon=106.632,
            lat=10.962,
            source="test",
            confidence="high",
        ),
    )


def test_normalizer_requires_exact_boundary_sets(product_spec, source_payloads):
    layers = build_normalized_layers(
        product_spec,
        source_payloads,
        neighborhood_points=_sample_neighborhoods(),
    )

    assert len(layers.legacy_boundaries) == 14
    assert len(layers.current_boundaries) == 5
    assert {feature.name for feature in layers.legacy_boundaries} == set(
        product_spec.legacy_wards
    )
    assert {feature.name for feature in layers.current_boundaries} == set(
        product_spec.current_wards
    )
    assert all(
        feature.geometry.geom_type in {"Polygon", "MultiPolygon"}
        for feature in (*layers.legacy_boundaries, *layers.current_boundaries)
    )


def test_normalizer_rejects_incomplete_boundary_snapshot(
    product_spec, source_payloads
):
    legacy_path = source_payloads["legacy_boundaries"]
    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    payload["features"].pop()
    _write_json(legacy_path, payload)

    with pytest.raises(ValueError, match="exactly 14"):
        build_normalized_layers(
            product_spec,
            source_payloads,
            neighborhood_points=_sample_neighborhoods(),
        )


def test_normalizer_ignores_invalid_boundary_outside_expected_set(
    product_spec, source_payloads
):
    legacy_path = source_payloads["legacy_boundaries"]
    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    payload["features"].insert(
        0,
        {
            "type": "Feature",
            "properties": {"name": "Đơn vị ngoài phạm vi"},
            "geometry": {"type": "Polygon", "coordinates": []},
        },
    )
    _write_json(legacy_path, payload)

    layers = build_normalized_layers(
        product_spec,
        source_payloads,
        neighborhood_points=_sample_neighborhoods(),
    )

    assert len(layers.legacy_boundaries) == 14


def test_osm_details_are_clipped_classified_and_deduplicated(
    product_spec, source_payloads
):
    layers = build_normalized_layers(
        product_spec,
        source_payloads,
        neighborhood_points=_sample_neighborhoods(),
    )
    old_city = unary_union(
        [feature.geometry for feature in layers.legacy_boundaries]
    )

    assert {road.road_class for road in layers.streets} == {"primary", "local"}
    assert all(old_city.covers(feature.geometry) for feature in layers.streets)
    assert all(old_city.covers(feature.geometry) for feature in layers.hydro)
    assert [point.name for point in layers.poi] == ["Chợ Thủ Dầu Một"]


def test_invalid_or_polygon_neighborhood_is_rejected(product_spec, source_payloads):
    bad = MapPoint(
        name="Khu phố giả",
        lon=106.7,
        lat=11.0,
        source="test",
        confidence="high",
        geometry_type="Polygon",
    )

    with pytest.raises(ValueError, match="Point"):
        build_normalized_layers(
            product_spec,
            source_payloads,
            neighborhood_points=(bad,),
        )


def test_snapshot_fetch_is_cache_first_and_records_manifest(tmp_path: Path):
    local_source = _write_json(
        tmp_path / "current.geojson",
        {"type": "FeatureCollection", "features": []},
    )
    registry = (
        MapSource(
            key="current_boundaries",
            source_url=str(local_source),
            license_name="ODbL",
            license_url="https://example.test/license",
            snapshot_strategy="repo_snapshot",
            snapshot_at="2026-07-28",
        ),
        MapSource(
            key="osm_detail",
            source_url=(
                "https://example.test/overpass?data="
                "%5Bout%3Ajson%5D%5Bdate%3A%222026-07-29T00%3A00%3A00Z%22%5D%3B"
            ),
            license_name="ODbL",
            license_url="https://example.test/license",
            snapshot_strategy="dated_query",
            snapshot_at="2026-07-29T00:00:00Z",
        ),
    )
    calls = []

    def fake_get(url: str) -> bytes:
        calls.append(url)
        return b'{"elements":[],"version":0.6}'

    cache_dir = tmp_path / "cache"
    first = fetch_source_snapshots(
        registry, cache_dir, refresh=False, http_get=fake_get
    )
    second = fetch_source_snapshots(
        registry,
        cache_dir,
        refresh=False,
        http_get=lambda _url: pytest.fail("cache should prevent HTTP"),
    )
    manifest = json.loads(
        (cache_dir / "source-snapshots.json").read_text(encoding="utf-8")
    )

    assert first == second
    assert len(calls) == 1
    assert set(manifest) == {"current_boundaries", "osm_detail"}
    assert manifest["osm_detail"]["query_timestamp"] == "2026-07-29T00:00:00Z"
    assert manifest["osm_detail"]["byte_length"] == len(
        b'{"elements":[],"version":0.6}'
    )
    assert len(manifest["osm_detail"]["sha256"]) == 64
    assert manifest["osm_detail"]["license"] == "ODbL"


def test_failed_refresh_preserves_valid_snapshot_and_manifest(tmp_path: Path):
    source = MapSource(
        key="osm_detail",
        source_url=(
            "https://example.test/overpass?data="
            "%5Bout%3Ajson%5D%5Bdate%3A%222026-07-29T00%3A00%3A00Z%22%5D%3B"
        ),
        license_name="ODbL",
        license_url="https://example.test/license",
        snapshot_strategy="dated_query",
        snapshot_at="2026-07-29T00:00:00Z",
    )
    cache_dir = tmp_path / "cache"
    snapshots = fetch_source_snapshots(
        (source,),
        cache_dir,
        http_get=lambda _url: b'{"elements":[],"version":0.6}',
    )
    snapshot_path = snapshots["osm_detail"]
    before_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    before_manifest = (cache_dir / "source-snapshots.json").read_bytes()

    with pytest.raises(ValueError, match="JSON"):
        fetch_source_snapshots(
            (source,),
            cache_dir,
            refresh=True,
            http_get=lambda _url: b"not-json",
        )

    assert hashlib.sha256(snapshot_path.read_bytes()).hexdigest() == before_hash
    assert (cache_dir / "source-snapshots.json").read_bytes() == before_manifest


def test_http_get_uses_radar_user_agent_and_sixty_second_timeout(monkeypatch):
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"ok"

    def fake_urlopen(request, timeout):
        observed["user_agent"] = request.headers["User-agent"]
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr("map_products.sources.urlopen", fake_urlopen)

    assert _http_get("https://example.test/data") == b"ok"
    assert observed == {
        "user_agent": "Radar BDS Map Product Builder/1.0 (+https://radarbds.vn)",
        "timeout": 60,
    }

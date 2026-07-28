"""Strict, immutable loaders for downloadable map-product source metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import math
from pathlib import Path
from typing import Any


_PRODUCT_FIELDS = {
    "slug",
    "version",
    "price_vnd",
    "legacy_wards",
    "current_wards",
    "formats",
    "font_family",
}
_SOURCE_FIELDS = {
    "key",
    "source_url",
    "license_name",
    "license_url",
    "snapshot_strategy",
    "snapshot_at",
}
_POINT_PROPERTY_FIELDS = {
    "name",
    "source",
    "source_url",
    "confidence",
    "boundary_claim",
}
_SNAPSHOT_STRATEGIES = {"fixed_url", "dated_query", "repo_snapshot"}
_CONFIDENCE_LEVELS = {"high", "medium"}


@dataclass(frozen=True)
class MapSource:
    key: str
    source_url: str
    license_name: str
    license_url: str
    snapshot_strategy: str
    snapshot_at: str


@dataclass(frozen=True)
class MapProductSpec:
    slug: str
    version: str
    price_vnd: int
    legacy_wards: tuple[str, ...]
    current_wards: tuple[str, ...]
    formats: tuple[str, ...]
    font_family: str


@dataclass(frozen=True)
class MapPoint:
    name: str
    lon: float
    lat: float
    source: str
    confidence: str
    geometry_type: str = "Point"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to load JSON from {path}: {exc}") from exc


def _require_exact_keys(value: Any, expected: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if unknown:
            details.append(f"unknown {sorted(unknown)}")
        raise ValueError(f"{context} has invalid keys: {', '.join(details)}")
    return value


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _unique_strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    values = tuple(_non_empty_string(item, f"{field} item") for item in value)
    if len(set(values)) != len(values):
        raise ValueError(f"{field} cannot contain duplicate names")
    return values


def _validate_snapshot_at(value: str, field: str) -> str:
    normalized = _non_empty_string(value, field)
    try:
        if "T" in normalized:
            datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        else:
            date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 date or timestamp") from exc
    return normalized


def load_product_spec(path: Path) -> MapProductSpec:
    """Load one product specification while rejecting schema drift."""

    data = _require_exact_keys(_load_json(path), _PRODUCT_FIELDS, "product spec")
    price = data["price_vnd"]
    if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
        raise ValueError("price_vnd must be a positive integer")
    return MapProductSpec(
        slug=_non_empty_string(data["slug"], "slug"),
        version=_non_empty_string(data["version"], "version"),
        price_vnd=price,
        legacy_wards=_unique_strings(data["legacy_wards"], "legacy_wards"),
        current_wards=_unique_strings(data["current_wards"], "current_wards"),
        formats=_unique_strings(data["formats"], "formats"),
        font_family=_non_empty_string(data["font_family"], "font_family"),
    )


def load_source_registry(path: Path) -> tuple[MapSource, ...]:
    """Load licensed, reproducible source records for one map product."""

    root = _require_exact_keys(_load_json(path), {"sources"}, "source registry")
    raw_sources = root["sources"]
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("sources must be a non-empty list")

    sources = []
    for index, raw_source in enumerate(raw_sources):
        source = _require_exact_keys(raw_source, _SOURCE_FIELDS, f"sources[{index}]")
        strategy = _non_empty_string(
            source["snapshot_strategy"], f"sources[{index}].snapshot_strategy"
        )
        if strategy not in _SNAPSHOT_STRATEGIES:
            raise ValueError(f"sources[{index}].snapshot_strategy is not supported")
        sources.append(
            MapSource(
                key=_non_empty_string(source["key"], f"sources[{index}].key"),
                source_url=_non_empty_string(
                    source["source_url"], f"sources[{index}].source_url"
                ),
                license_name=_non_empty_string(
                    source["license_name"], f"sources[{index}].license_name"
                ),
                license_url=_non_empty_string(
                    source["license_url"], f"sources[{index}].license_url"
                ),
                snapshot_strategy=strategy,
                snapshot_at=_validate_snapshot_at(
                    source["snapshot_at"], f"sources[{index}].snapshot_at"
                ),
            )
        )
    if len({source.key for source in sources}) != len(sources):
        raise ValueError("sources cannot contain duplicate keys")
    return tuple(sources)


def _coordinate(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    coordinate = float(value)
    if not math.isfinite(coordinate) or not minimum <= coordinate <= maximum:
        raise ValueError(f"{field} is out of range")
    return coordinate


def load_neighborhood_points(path: Path) -> tuple[MapPoint, ...]:
    """Load named reference points without accepting boundary geometry."""

    collection = _require_exact_keys(
        _load_json(path), {"type", "features"}, "neighborhood GeoJSON"
    )
    if collection["type"] != "FeatureCollection":
        raise ValueError("neighborhood GeoJSON must be a FeatureCollection")
    features = collection["features"]
    if not isinstance(features, list) or not features:
        raise ValueError("neighborhood GeoJSON must contain at least one feature")

    points = []
    for index, raw_feature in enumerate(features):
        feature = _require_exact_keys(
            raw_feature, {"type", "properties", "geometry"}, f"features[{index}]"
        )
        if feature["type"] != "Feature":
            raise ValueError(f"features[{index}] must be a GeoJSON Feature")
        properties = _require_exact_keys(
            feature["properties"], _POINT_PROPERTY_FIELDS, f"features[{index}].properties"
        )
        if properties["confidence"] not in _CONFIDENCE_LEVELS:
            raise ValueError(f"features[{index}].properties.confidence is invalid")
        if properties["boundary_claim"] is not False:
            raise ValueError(f"features[{index}].properties.boundary_claim must be false")
        geometry = _require_exact_keys(
            feature["geometry"], {"type", "coordinates"}, f"features[{index}].geometry"
        )
        if geometry["type"] != "Point":
            raise ValueError(f"features[{index}] must use Point geometry")
        coordinates = geometry["coordinates"]
        if not isinstance(coordinates, list) or len(coordinates) != 2:
            raise ValueError(f"features[{index}].geometry.coordinates must be [lon, lat]")
        points.append(
            MapPoint(
                name=_non_empty_string(properties["name"], f"features[{index}].properties.name"),
                lon=_coordinate(coordinates[0], f"features[{index}].geometry.coordinates[0]", -180, 180),
                lat=_coordinate(coordinates[1], f"features[{index}].geometry.coordinates[1]", -90, 90),
                source=_non_empty_string(
                    properties["source"], f"features[{index}].properties.source"
                ),
                confidence=properties["confidence"],
            )
        )
        _non_empty_string(properties["source_url"], f"features[{index}].properties.source_url")
    if len({point.name for point in points}) != len(points):
        raise ValueError("neighborhood points cannot contain duplicate names")
    return tuple(points)

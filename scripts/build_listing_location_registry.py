from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.listing_map import LISTING_MAP_BOUNDS
from services.listing_location_resolver import (
    normalize_location_token,
    normalize_road_token,
)


OUTPUT_NAMES = (
    "ward-centers.json",
    "road-centers.json",
    "manifest.json",
)


def _json_bytes(payload: Mapping) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _payload_sha256(payload: Mapping) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _inside_bounds(lat: float, lng: float) -> bool:
    (south, west), (north, east) = LISTING_MAP_BOUNDS
    return south <= lat <= north and west <= lng <= east


def _element_point(element: Mapping) -> tuple[float, float]:
    if element.get("type") == "node":
        lat, lng = element.get("lat"), element.get("lon")
    else:
        center = element.get("center") or {}
        lat, lng = center.get("lat"), center.get("lon")
        if lat is None or lng is None:
            geometry = element.get("geometry") or []
            if geometry:
                lat = sum(float(point["lat"]) for point in geometry) / len(geometry)
                lng = sum(float(point["lon"]) for point in geometry) / len(geometry)
    try:
        point = float(lat), float(lng)
    except (TypeError, ValueError):
        raise ValueError(
            f"OSM {element.get('type')} {element.get('id')} has no usable point"
        ) from None
    if not _inside_bounds(*point):
        raise ValueError(
            f"OSM {element.get('type')} {element.get('id')} is outside listing map bounds"
        )
    return point


def _segment_length_m(first: Mapping, second: Mapping) -> float:
    lat1 = math.radians(float(first["lat"]))
    lat2 = math.radians(float(second["lat"]))
    d_lat = lat2 - lat1
    d_lng = math.radians(float(second["lon"]) - float(first["lon"]))
    value = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    )
    return 6371008.8 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _road_center(elements: list[Mapping]) -> tuple[float, float]:
    weighted_lat = 0.0
    weighted_lng = 0.0
    total_length = 0.0
    fallback_points = []
    for element in elements:
        if not (element.get("tags") or {}).get("highway"):
            raise ValueError(
                f"OSM way {element.get('id')} is not a highway"
            )
        geometry = element.get("geometry") or []
        if len(geometry) < 2:
            fallback_points.append(_element_point(element))
            continue
        for first, second in zip(geometry, geometry[1:], strict=False):
            lat = (float(first["lat"]) + float(second["lat"])) / 2
            lng = (float(first["lon"]) + float(second["lon"])) / 2
            if not _inside_bounds(lat, lng):
                raise ValueError(
                    f"OSM way {element.get('id')} is outside listing map bounds"
                )
            length = _segment_length_m(first, second)
            weighted_lat += lat * length
            weighted_lng += lng * length
            total_length += length
    if total_length > 0:
        return weighted_lat / total_length, weighted_lng / total_length
    if fallback_points:
        return (
            sum(point[0] for point in fallback_points) / len(fallback_points),
            sum(point[1] for point in fallback_points) / len(fallback_points),
        )
    raise ValueError("road source has no usable highway geometry")


def _element_index(osm_payload: Mapping) -> dict[tuple[str, int], Mapping]:
    index = {}
    for element in osm_payload.get("elements") or []:
        element_type = str(element.get("type") or "")
        try:
            element_id = int(element["id"])
        except (KeyError, TypeError, ValueError):
            continue
        index[(element_type, element_id)] = element
    return index


def _validate_canonical_wards(sources: Mapping, mapped_keys: set[tuple[str, str]]):
    required = {
        (
            str(item.get("city") or "").strip(),
            normalize_location_token(item.get("ward") or ""),
        )
        for item in sources.get("canonical_wards") or []
    }
    missing = sorted(required - mapped_keys)
    if missing:
        labels = ", ".join(f"{city}/{ward}" for city, ward in missing)
        raise ValueError(f"missing canonical ward: {labels}")


def build_location_registries(
    osm_payload: Mapping,
    sources: Mapping,
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    resolver_version = str(sources.get("resolver_version") or "").strip()
    if not resolver_version:
        raise ValueError("resolver_version is required")
    index = _element_index(osm_payload)

    ward_rows = []
    ward_keys: set[tuple[str, str]] = set()
    for source in sources.get("wards") or []:
        city = str(source.get("city") or "").strip()
        ward = str(source.get("ward") or "").strip()
        key = city, normalize_location_token(ward)
        if not city or not key[1]:
            raise ValueError("ward city and name are required")
        if key in ward_keys:
            raise ValueError(f"duplicate normalized ward: {city}/{key[1]}")
        point_source = source.get("point")
        provenance = str(source.get("source") or "").strip()
        source_url = str(source.get("source_url") or "").strip()
        element_key = None
        if point_source is not None:
            try:
                lat = float(point_source["lat"])
                lng = float(point_source["lng"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(
                    f"verified ward point is invalid for {ward}"
                ) from None
            if (
                not _inside_bounds(lat, lng)
                or not provenance
                or not source_url.startswith("https://")
            ):
                raise ValueError(f"verified ward point is invalid for {ward}")
        else:
            element_key = (
                str(source.get("osm_type") or ""),
                int(source.get("osm_id") or 0),
            )
            element = index.get(element_key)
            if not element:
                raise ValueError(
                    f"missing OSM {element_key[0]} {element_key[1]} for ward {ward}"
                )
            lat, lng = _element_point(element)
            provenance = "OpenStreetMap"
            source_url = (
                f"https://www.openstreetmap.org/"
                f"{element_key[0]}/{element_key[1]}"
            )
        ward_keys.add(key)
        fallback_parent = str(source.get("fallback_parent") or "").strip()
        default_label = (
            f"Theo trung tâm {fallback_parent} (xấp xỉ cho {ward})"
            if fallback_parent
            else f"Theo trung tâm {ward}"
        )
        row = {
            "city": city,
            "ward": ward,
            "normalized_ward": key[1],
            "lat": round(lat, 7),
            "lng": round(lng, 7),
            "label": str(source.get("label") or default_label).strip(),
            "source": provenance,
            "source_url": source_url,
        }
        if fallback_parent:
            row["fallback_parent"] = fallback_parent
        if element_key is not None:
            row["osm_type"] = element_key[0]
            row["osm_id"] = element_key[1]
        ward_rows.append(row)
    _validate_canonical_wards(sources, ward_keys)

    road_rows = []
    road_keys: set[tuple[str, str, str]] = set()
    for source in sources.get("roads") or []:
        city = str(source.get("city") or "").strip()
        ward = str(source.get("ward") or "").strip()
        road_name = str(source.get("road_name") or "").strip()
        key = (
            city,
            normalize_location_token(ward),
            normalize_road_token(road_name),
        )
        if not all(key):
            raise ValueError("road city, ward, and name are required")
        if key in road_keys:
            raise ValueError(
                f"duplicate normalized road: {city}/{key[1]}/{key[2]}"
            )
        way_ids = sorted({int(item) for item in source.get("osm_way_ids") or []})
        if not way_ids:
            raise ValueError(f"road {road_name} has no OSM way IDs")
        elements = []
        for way_id in way_ids:
            element = index.get(("way", way_id))
            if not element:
                raise ValueError(f"missing OSM way {way_id} for road {road_name}")
            elements.append(element)
        lat, lng = _road_center(elements)
        road_keys.add(key)
        road_rows.append(
            {
                "city": city,
                "ward": ward,
                "normalized_ward": key[1],
                "road_name": road_name,
                "normalized_road": key[2],
                "lat": round(lat, 7),
                "lng": round(lng, 7),
                "label": f"Theo tên đường {road_name}, {ward}",
                "source": "OpenStreetMap",
                "osm_way_ids": way_ids,
            }
        )

    ward_payload = {
        "resolver_version": resolver_version,
        "wards": sorted(
            ward_rows,
            key=lambda row: (
                normalize_location_token(row["city"]),
                row["normalized_ward"],
            ),
        ),
    }
    road_payload = {
        "resolver_version": resolver_version,
        "roads": sorted(
            road_rows,
            key=lambda row: (
                normalize_location_token(row["city"]),
                row["normalized_ward"],
                row["normalized_road"],
            ),
        ),
    }
    ward_bytes = _json_bytes(ward_payload)
    road_bytes = _json_bytes(road_payload)
    manifest_payload = {
        "resolver_version": resolver_version,
        "osm_sha256": _payload_sha256(osm_payload),
        "sources_sha256": _payload_sha256(sources),
        "ward_registry_sha256": hashlib.sha256(ward_bytes).hexdigest(),
        "road_registry_sha256": hashlib.sha256(road_bytes).hexdigest(),
        "ward_count": len(ward_rows),
        "road_count": len(road_rows),
        "ambiguous_road_count": max(
            int(
                sources.get(
                    "ambiguous_road_count",
                    len(sources.get("ambiguous_roads") or []),
                )
            ),
            0,
        ),
        "rejected_road_count": max(
            int(
                sources.get(
                    "rejected_road_count",
                    len(sources.get("rejected_roads") or []),
                )
            ),
            0,
        ),
    }
    manifest_bytes = _json_bytes(manifest_payload)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payloads = (ward_bytes, road_bytes, manifest_bytes)
    with tempfile.TemporaryDirectory(
        prefix=".listing-locations-",
        dir=output_dir.parent,
    ) as temporary:
        temporary_dir = Path(temporary)
        for name, content in zip(OUTPUT_NAMES, payloads, strict=True):
            (temporary_dir / name).write_bytes(content)
        for name in OUTPUT_NAMES:
            os.replace(temporary_dir / name, output_dir / name)

    return tuple(output_dir / name for name in OUTPUT_NAMES)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build deterministic listing location registries."
    )
    parser.add_argument("--osm-json", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    osm_payload = json.loads(args.osm_json.read_text(encoding="utf-8"))
    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    paths = build_location_registries(osm_payload, sources, args.output_dir)
    for path in paths:
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

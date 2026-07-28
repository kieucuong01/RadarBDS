"""Build deterministic source assets for the Thu Dau Mot map bundle."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from map_products.geometry import NormalizedMapLayers, build_normalized_layers
from map_products.models import (
    load_neighborhood_points,
    load_product_spec,
    load_source_registry,
)
from map_products.sources import fetch_source_snapshots
from map_products.renderers import render_kml, render_pdf, render_svg
from map_products.scene import build_scene


def _feature(name: str, layer: str, geometry, **properties) -> dict:
    from shapely.geometry import mapping

    return {
        "type": "Feature",
        "properties": {"layer": layer, "name": name, **properties},
        "geometry": mapping(geometry),
    }


def _normalized_geojson(layers: NormalizedMapLayers) -> dict:
    features = []
    features.extend(
        _feature(
            item.name,
            "current_boundaries",
            item.geometry,
            source_id=item.source_id,
        )
        for item in layers.current_boundaries
    )
    features.extend(
        {
            "type": "Feature",
            "properties": {
                "layer": "legacy_ward_centers",
                "name": point.name,
                "source": point.source,
                "source_url": point.source_url,
                "confidence": point.confidence,
                "boundary_claim": point.boundary_claim,
            },
            "geometry": {
                "type": "Point",
                "coordinates": [point.lon, point.lat],
            },
        }
        for point in layers.legacy_ward_centers
    )
    features.extend(
        _feature(
            item.name,
            "streets",
            item.geometry,
            road_class=item.road_class,
            source_id=item.source_id,
        )
        for item in layers.streets
    )
    features.extend(
        _feature(item.name, "hydro", item.geometry, source_id=item.source_id)
        for item in layers.hydro
    )
    for layer_name, points in (
        ("poi", layers.poi),
        ("neighborhoods", layers.neighborhoods),
    ):
        features.extend(
            {
                "type": "Feature",
                "properties": {
                    "layer": layer_name,
                    "name": point.name,
                    "source": point.source,
                    "confidence": point.confidence,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [point.lon, point.lat],
                },
            }
            for point in points
        )
    return {"type": "FeatureCollection", "features": features}


def _stage_file(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
        return Path(temporary.name)


def _write_source_outputs(
    work_dir: Path,
    layers: NormalizedMapLayers,
) -> tuple[Path, Path]:
    normalized_path = work_dir / "normalized-layers.geojson"
    manifest_path = work_dir / "source-manifest.json"
    normalized_payload = (
        json.dumps(
            _normalized_geojson(layers),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    manifest_payload = (
        json.dumps(
            layers.source_manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    staged_normalized = _stage_file(normalized_path, normalized_payload)
    staged_manifest = _stage_file(manifest_path, manifest_payload)
    try:
        staged_normalized.replace(normalized_path)
        staged_manifest.replace(manifest_path)
    finally:
        if staged_normalized.exists():
            staged_normalized.unlink()
        if staged_manifest.exists():
            staged_manifest.unlink()
    return normalized_path, manifest_path


def render_product_outputs(
    layers: NormalizedMapLayers,
    work_dir: Path,
    fonts: Mapping[str, str | Path],
) -> tuple[Path, ...]:
    """Render both editions in every commercial vector/geographic format."""

    render_dir = work_dir / "rendered"
    outputs = []
    for edition in ("legacy", "current"):
        scene = build_scene(layers, edition)
        stem = f"thu-dau-mot-{edition}"
        outputs.extend(
            (
                render_svg(scene, render_dir / f"{stem}.svg", fonts),
                render_pdf(scene, render_dir / f"{stem}.pdf", fonts),
                render_kml(layers, edition, render_dir / f"{stem}.kml"),
            )
        )
    return tuple(outputs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-sources", action="store_true")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("artifacts/map-products/thu-dau-mot"),
    )
    parser.add_argument(
        "--stage",
        choices=("sources", "render", "validate", "package", "all"),
        default="all",
    )
    args = parser.parse_args(argv)

    spec = load_product_spec(
        ROOT / "config/map_products/thu_dau_mot_product.json"
    )
    registry = load_source_registry(
        ROOT / "config/map_products/thu_dau_mot_sources.json"
    )
    neighborhoods = load_neighborhood_points(
        ROOT / "config/map_products/thu_dau_mot_neighborhoods.geojson"
    )
    work_dir = args.work_dir.resolve()
    snapshots = fetch_source_snapshots(
        registry,
        work_dir / "source-cache",
        refresh=args.refresh_sources,
    )
    layers = build_normalized_layers(
        spec,
        snapshots,
        neighborhood_points=neighborhoods,
    )
    normalized_path, manifest_path = _write_source_outputs(work_dir, layers)
    print(
        "sources normalized:",
        f"legacy_points={len(layers.legacy_ward_centers)}",
        f"current={len(layers.current_boundaries)}",
        f"streets={len(layers.streets)}",
        f"hydro={len(layers.hydro)}",
        f"poi={len(layers.poi)}",
        f"neighborhoods={len(layers.neighborhoods)}",
    )
    print(f"normalized_geojson={normalized_path}")
    print(f"source_manifest={manifest_path}")
    if args.stage in {"render", "all"}:
        outputs = render_product_outputs(
            layers,
            work_dir,
            {
                "regular": snapshots["font"],
                "semibold": snapshots["font_semibold"],
            },
        )
        for output in outputs:
            print(f"rendered={output}")
    elif args.stage != "sources":
        print(
            f"stage={args.stage} source gate complete; downstream stage is "
            "implemented separately"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

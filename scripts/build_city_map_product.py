"""Build, validate, preview, and package one allowlisted city map product."""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from map_products.geometry import build_normalized_layers
from map_products.models import (
    load_neighborhood_points,
    load_product_spec,
    load_source_registry,
)
from map_products.release import MapReleaseProfile
from map_products.sources import fetch_source_snapshots
from scripts.build_thu_dau_mot_map_product import (
    _load_ofl_text,
    _write_source_outputs,
    render_product_outputs,
    run_release_stage,
)


CITY_CONFIG_NAMES = {
    "thuan-an": "thuan_an",
    "di-an": "di_an",
    "ben-cat": "ben_cat",
}


def build_city_product(
    city_slug: str,
    *,
    stage: str,
    work_dir: Path,
    refresh_sources: bool = False,
) -> Path:
    """Execute a deterministic release stage for one configured city."""

    try:
        config_name = CITY_CONFIG_NAMES[city_slug]
    except KeyError as exc:
        raise ValueError(f"Unsupported city map product: {city_slug}") from exc
    config_dir = ROOT / "config/map_products"
    spec = load_product_spec(config_dir / f"{config_name}_product.json")
    profile = MapReleaseProfile.from_spec(spec)
    registry = load_source_registry(
        config_dir / f"{config_name}_sources.json"
    )
    neighborhoods = load_neighborhood_points(
        config_dir / f"{config_name}_neighborhoods.geojson"
    )
    work_dir = Path(work_dir).resolve()
    snapshots = fetch_source_snapshots(
        registry,
        work_dir / "source-cache",
        refresh=refresh_sources,
    )
    layers = build_normalized_layers(
        spec,
        snapshots,
        neighborhood_points=neighborhoods,
    )
    normalized_path, manifest_path = _write_source_outputs(work_dir, layers)
    print(
        "sources normalized:",
        f"city={city_slug}",
        f"legacy_boundaries={len(layers.legacy_boundaries)}",
        f"legacy_points={len(layers.legacy_ward_centers)}",
        f"current={len(layers.current_boundaries)}",
        f"streets={len(layers.streets)}",
        f"hydro={len(layers.hydro)}",
        f"poi={len(layers.poi)}",
        f"neighborhoods={len(layers.neighborhoods)}",
    )
    print(f"normalized_geojson={normalized_path}")
    print(f"source_manifest={manifest_path}")
    if stage == "sources":
        return normalized_path

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
    if stage == "render":
        return work_dir / "rendered"

    ofl_text = _load_ofl_text(
        work_dir / "source-cache",
        refresh=refresh_sources,
    )
    release_output = run_release_stage(
        work_dir,
        stage=stage,
        approval_path=work_dir / "release-approval.json",
        output_zip=work_dir / "releases" / profile.output_zip_name,
        preview_paths=(
            ROOT / f"static/images/seo/{city_slug}-map-before.webp",
            ROOT / f"static/images/seo/{city_slug}-map-after.webp",
        ),
        ofl_text=ofl_text,
        profile=profile,
    )
    print(f"release_output={release_output}")
    if release_output.suffix == ".zip":
        print(
            "release_sha256="
            f"{sha256(release_output.read_bytes()).hexdigest()}"
        )
    return release_output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", choices=tuple(CITY_CONFIG_NAMES), required=True)
    parser.add_argument("--refresh-sources", action="store_true")
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Override ignored artifacts workspace for this city.",
    )
    parser.add_argument(
        "--stage",
        choices=("sources", "render", "validate", "package", "all"),
        default="all",
    )
    args = parser.parse_args(argv)
    build_city_product(
        args.city,
        stage=args.stage,
        work_dir=(
            args.work_dir
            if args.work_dir is not None
            else Path("artifacts/map-products") / args.city
        ),
        refresh_sources=args.refresh_sources,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

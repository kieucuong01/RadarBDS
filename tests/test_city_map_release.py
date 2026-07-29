from __future__ import annotations

from pathlib import Path

import pytest

from map_products.models import (
    load_neighborhood_points,
    load_product_spec,
    load_source_registry,
)
from map_products.release import MapReleaseProfile
from scripts.build_city_map_product import CITY_CONFIG_NAMES


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATHS = (
    ROOT / "config/map_products/thuan_an_product.json",
    ROOT / "config/map_products/di_an_product.json",
    ROOT / "config/map_products/ben_cat_product.json",
)


@pytest.mark.parametrize("spec_path", SPEC_PATHS)
def test_release_profile_names_files_from_city_spec(spec_path: Path) -> None:
    spec = load_product_spec(spec_path)
    profile = MapReleaseProfile.from_spec(spec)

    assert profile.product_name == f"radarbds-{spec.city_slug}-map"
    assert profile.legacy_pdf == f"{spec.city_slug}-truoc-2025-a0.pdf"
    assert profile.current_kml == f"{spec.city_slug}-sau-2025.kml"
    assert profile.output_zip_name == (
        f"radarbds-{spec.city_slug}-map-v{spec.version}.zip"
    )
    assert profile.legacy_count == len(spec.legacy_wards)
    assert profile.current_count == len(spec.current_wards)
    assert profile.legacy_names == frozenset(spec.legacy_wards)
    assert profile.current_names == frozenset(spec.current_wards)
    assert profile.derived_legacy_names == frozenset(
        spec.derived_legacy_wards
    )


@pytest.mark.parametrize("spec_path", SPEC_PATHS)
def test_release_profile_expected_files_are_city_scoped(
    spec_path: Path,
) -> None:
    spec = load_product_spec(spec_path)
    profile = MapReleaseProfile.from_spec(spec)

    assert len(profile.expected_files) == 11
    assert profile.legacy_pdf in profile.expected_files
    assert profile.current_pdf in profile.expected_files
    assert profile.legacy_svg in profile.expected_files
    assert profile.current_svg in profile.expected_files
    assert profile.legacy_kml in profile.expected_files
    assert profile.current_kml in profile.expected_files
    assert not any(
        "thu-dau-mot" in filename
        for filename in profile.expected_files
        if spec.city_slug != "thu-dau-mot"
    )


@pytest.mark.parametrize("city_slug,config_name", CITY_CONFIG_NAMES.items())
def test_city_source_registry_and_neighborhoods_are_complete(
    city_slug: str,
    config_name: str,
) -> None:
    config_dir = ROOT / "config/map_products"
    sources = load_source_registry(
        config_dir / f"{config_name}_sources.json"
    )
    points = load_neighborhood_points(
        config_dir / f"{config_name}_neighborhoods.geojson"
    )

    assert {source.key for source in sources} == {
        "current_boundaries",
        "legacy_boundaries",
        "legacy_ward_centers",
        "osm_detail",
        "font",
        "font_semibold",
    }
    assert len(points) >= 10
    assert len({point.name for point in points}) == len(points)
    assert all(point.geometry_type == "Point" for point in points)
    assert all(point.boundary_claim is False for point in points)
    assert all(
        point.source.startswith("OpenStreetMap node ")
        and point.source_url.startswith("https://www.openstreetmap.org/node/")
        for point in points
    )

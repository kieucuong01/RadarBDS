from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree

import pytest
from shapely.geometry import box

from map_products.geometry import NamedGeometry, NormalizedMapLayers
from map_products.models import MapPoint, MapProductSpec, load_product_spec
from map_products.renderers import render_kml
from map_products.scene import build_scene


ROOT = Path(__file__).resolve().parents[1]
KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}
CITY_SPEC_PATHS = (
    ROOT / "config" / "map_products" / "thuan_an_product.json",
    ROOT / "config" / "map_products" / "di_an_product.json",
    ROOT / "config" / "map_products" / "ben_cat_product.json",
)


def _layers(spec: MapProductSpec) -> NormalizedMapLayers:
    current = tuple(
        NamedGeometry(
            name=name,
            geometry=box(
                106.60 + index * 0.015,
                10.90,
                106.612 + index * 0.015,
                10.94,
            ),
            source_id=f"current-{index}",
        )
        for index, name in enumerate(spec.current_wards)
    )
    legacy = tuple(
        NamedGeometry(
            name=name,
            geometry=box(
                106.60 + (index % 5) * 0.014,
                10.90 + (index // 5) * 0.014,
                106.611 + (index % 5) * 0.014,
                10.911 + (index // 5) * 0.014,
            ),
            source_id=f"legacy-{index}",
            properties={
                "source": "Radar BDS test snapshot",
                "boundary_claim": "true",
                "boundary_source": (
                    "derived_boundary"
                    if name in spec.derived_legacy_wards
                    else "source_snapshot"
                ),
                "derived_from": (
                    "current boundary residual"
                    if name in spec.derived_legacy_wards
                    else ""
                ),
            },
        )
        for index, name in enumerate(spec.legacy_wards)
    )
    centers = tuple(
        MapPoint(
            name=name,
            lon=106.605 + (index % 5) * 0.014,
            lat=10.905 + (index // 5) * 0.014,
            source="Radar BDS test snapshot",
            confidence="high",
        )
        for index, name in enumerate(spec.legacy_wards)
    )
    return NormalizedMapLayers(
        legacy_boundaries=legacy,
        current_boundaries=current,
        legacy_ward_centers=centers,
        streets=(),
        hydro=(),
        poi=(),
        neighborhoods=(),
        source_manifest={},
        product_spec=spec,
    )


@pytest.mark.parametrize("spec_path", CITY_SPEC_PATHS)
def test_scene_uses_city_product_counts_and_copy(spec_path: Path) -> None:
    spec = load_product_spec(spec_path)
    layers = _layers(spec)

    legacy = build_scene(layers, "legacy")
    current = build_scene(layers, "current")

    assert legacy.title == f"BẢN ĐỒ {spec.city_name.upper()}"
    assert legacy.subtitle.startswith(str(len(spec.legacy_wards)))
    assert current.subtitle.startswith(str(len(spec.current_wards)))
    for name in spec.derived_legacy_wards:
        assert name in legacy.disclaimer
    if not spec.derived_legacy_wards:
        assert "suy luận" not in legacy.disclaimer


@pytest.mark.parametrize("spec_path", CITY_SPEC_PATHS)
def test_scene_rejects_counts_that_do_not_match_product_spec(
    spec_path: Path,
) -> None:
    spec = load_product_spec(spec_path)
    layers = _layers(spec)

    with pytest.raises(
        ValueError,
        match=rf"exactly {len(spec.current_wards)} boundary polygons",
    ):
        build_scene(
            replace(layers, current_boundaries=layers.current_boundaries[:-1]),
            "current",
        )


@pytest.mark.parametrize("spec_path", CITY_SPEC_PATHS)
@pytest.mark.parametrize("edition", ("legacy", "current"))
def test_kml_uses_city_name_and_exact_product_boundary_count(
    tmp_path: Path,
    spec_path: Path,
    edition: str,
) -> None:
    spec = load_product_spec(spec_path)
    layers = _layers(spec)
    output = render_kml(layers, edition, tmp_path / f"{edition}.kml")
    root = ElementTree.parse(output).getroot()

    assert root.findtext(".//kml:Document/kml:name", namespaces=KML_NS) == (
        f"{spec.city_name} — {edition}"
    )
    expected = (
        len(spec.legacy_wards)
        if edition == "legacy"
        else len(spec.current_wards)
    )
    assert len(root.findall(".//kml:Placemark", KML_NS)) == expected

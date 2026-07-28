"""Shared projected scene graph for Thu Dau Mot map products."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import unicodedata

from pyproj import Transformer
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from .geometry import NormalizedMapLayers


A0_LANDSCAPE_WIDTH_PT = 3370.393700787402
A0_LANDSCAPE_HEIGHT_PT = 2383.937007874016
MAP_MARGIN_LEFT_PT = 150.0
MAP_MARGIN_RIGHT_PT = 150.0
MAP_MARGIN_BOTTOM_PT = 180.0
MAP_MARGIN_TOP_PT = 285.0

PAPER_COLOR = "#F7F1E7"
INK_COLOR = "#1D2B2A"
MUTED_INK_COLOR = "#566563"
BOUNDARY_FILL_COLOR = "#DCE8D5"
BOUNDARY_STROKE_COLOR = "#365E4B"
LEGACY_POINT_COLOR = "#B55336"
PRIMARY_ROAD_COLOR = "#C97842"
SECONDARY_ROAD_COLOR = "#DDAA73"
LOCAL_ROAD_COLOR = "#CABFAE"
HYDRO_COLOR = "#4E9BB6"
POI_COLOR = "#8E5A9D"
NEIGHBORHOOD_COLOR = "#8A743A"

MAP_LAYER_IDS = (
    "boundaries",
    "legacy-reference-centers",
    "streets",
    "hydro",
    "poi",
    "neighborhoods",
    "labels",
)

_PROJECT_WGS84_TO_UTM48N = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:32648",
    always_xy=True,
)


@dataclass(frozen=True)
class LayerStyle:
    fill: str = "none"
    stroke: str = "none"
    stroke_width_pt: float = 0.0
    point_radius_pt: float = 0.0
    fill_opacity: float = 1.0
    dash: tuple[float, ...] = ()


@dataclass(frozen=True)
class SceneFeature:
    name: str
    geometry: BaseGeometry
    properties: tuple[tuple[str, str], ...] = ()

    def property(self, name: str, default: str = "") -> str:
        return dict(self.properties).get(name, default)


@dataclass(frozen=True)
class SceneLayer:
    layer_id: str
    features: tuple[SceneFeature, ...]
    style: LayerStyle


@dataclass(frozen=True)
class SceneLabel:
    text: str
    x_m: float
    y_m: float
    priority: int
    font_role: Literal["regular", "semibold"]
    size_pt: float
    source_layer: str
    bbox_pt: tuple[float, float, float, float]

    def overlaps(self, other: "SceneLabel") -> bool:
        left, bottom, right, top = self.bbox_pt
        other_left, other_bottom, other_right, other_top = other.bbox_pt
        return not (
            right <= other_left
            or other_right <= left
            or top <= other_bottom
            or other_top <= bottom
        )


@dataclass(frozen=True)
class LegendItem:
    label: str
    color: str
    symbol: Literal["fill", "line", "point"]


@dataclass(frozen=True)
class MapScene:
    edition: str
    page_width_pt: float
    page_height_pt: float
    bounds_m: tuple[float, float, float, float]
    layers: tuple[SceneLayer, ...]
    labels: tuple[SceneLabel, ...]
    attribution: str
    title: str
    subtitle: str
    disclaimer: str
    legend: tuple[LegendItem, ...]
    scale_bar_m: int


BOUNDARY_STYLE = LayerStyle(
    fill=BOUNDARY_FILL_COLOR,
    stroke=BOUNDARY_STROKE_COLOR,
    stroke_width_pt=2.2,
    fill_opacity=0.72,
)
LEGACY_REFERENCE_STYLE = LayerStyle(
    fill=LEGACY_POINT_COLOR,
    stroke=PAPER_COLOR,
    stroke_width_pt=1.4,
    point_radius_pt=5.0,
)
STREET_STYLE = LayerStyle(stroke=LOCAL_ROAD_COLOR, stroke_width_pt=1.0)
HYDRO_STYLE = LayerStyle(stroke=HYDRO_COLOR, stroke_width_pt=2.0)
POI_STYLE = LayerStyle(
    fill=POI_COLOR,
    stroke=PAPER_COLOR,
    stroke_width_pt=0.8,
    point_radius_pt=3.2,
)
NEIGHBORHOOD_STYLE = LayerStyle(
    fill=NEIGHBORHOOD_COLOR,
    stroke=PAPER_COLOR,
    stroke_width_pt=0.8,
    point_radius_pt=2.6,
)
LABEL_STYLE = LayerStyle(fill=INK_COLOR)


def project_wgs84_geometry(geometry: BaseGeometry) -> BaseGeometry:
    """Project WGS84 geometry to the product CRS, preserving XY order."""

    return transform(_PROJECT_WGS84_TO_UTM48N.transform, geometry)


def scene_point_to_page(
    scene_or_bounds: MapScene | tuple[float, float, float, float],
    x_m: float,
    y_m: float,
) -> tuple[float, float]:
    """Map projected metres into the shared A0 page frame."""

    bounds = (
        scene_or_bounds.bounds_m
        if isinstance(scene_or_bounds, MapScene)
        else scene_or_bounds
    )
    min_x, min_y, max_x, max_y = bounds
    map_width = A0_LANDSCAPE_WIDTH_PT - MAP_MARGIN_LEFT_PT - MAP_MARGIN_RIGHT_PT
    map_height = A0_LANDSCAPE_HEIGHT_PT - MAP_MARGIN_BOTTOM_PT - MAP_MARGIN_TOP_PT
    scale = min(map_width / (max_x - min_x), map_height / (max_y - min_y))
    drawn_width = (max_x - min_x) * scale
    drawn_height = (max_y - min_y) * scale
    offset_x = MAP_MARGIN_LEFT_PT + (map_width - drawn_width) / 2
    offset_y = MAP_MARGIN_BOTTOM_PT + (map_height - drawn_height) / 2
    return (
        offset_x + (x_m - min_x) * scale,
        offset_y + (y_m - min_y) * scale,
    )


def _feature(
    name: str,
    geometry: BaseGeometry,
    **properties: str,
) -> SceneFeature:
    return SceneFeature(
        name=name,
        geometry=project_wgs84_geometry(geometry),
        properties=tuple(sorted((key, str(value)) for key, value in properties.items())),
    )


def _point_feature(point, **properties: str) -> SceneFeature:
    return _feature(
        point.name,
        Point(point.lon, point.lat),
        source=point.source,
        confidence=point.confidence,
        **properties,
    )


def _road_style(road_class: str) -> tuple[str, float]:
    return {
        "primary": (PRIMARY_ROAD_COLOR, 4.4),
        "secondary": (SECONDARY_ROAD_COLOR, 3.0),
        "tertiary": (SECONDARY_ROAD_COLOR, 2.2),
        "local": (LOCAL_ROAD_COLOR, 1.0),
    }.get(road_class, (LOCAL_ROAD_COLOR, 0.8))


def _padded_current_bounds(layers: NormalizedMapLayers) -> tuple[float, float, float, float]:
    current_union = unary_union(
        [
            project_wgs84_geometry(boundary.geometry)
            for boundary in layers.current_boundaries
        ]
    )
    if current_union.is_empty:
        raise ValueError("Current five-ward union cannot be empty")
    min_x, min_y, max_x, max_y = current_union.bounds
    padding = max(max_x - min_x, max_y - min_y) * 0.025
    return (
        min_x - padding,
        min_y - padding,
        max_x + padding,
        max_y + padding,
    )


def _measure_text_width_pt(text: str, size_pt: float, font_role: str) -> float:
    """Measure a stable Poppins-like text box without renderer-specific state."""

    units = 0.0
    for character in unicodedata.normalize("NFC", text):
        if character.isspace():
            units += 0.28
        elif character.isupper():
            units += 0.64
        elif character.isdigit():
            units += 0.57
        elif unicodedata.category(character).startswith("P"):
            units += 0.34
        else:
            units += 0.54
    weight_adjustment = 1.03 if font_role == "semibold" else 1.0
    return max(size_pt, units * size_pt * weight_adjustment)


def _label_candidate(
    bounds: tuple[float, float, float, float],
    text: str,
    geometry: BaseGeometry,
    *,
    priority: int,
    font_role: Literal["regular", "semibold"],
    size_pt: float,
    source_layer: str,
) -> SceneLabel:
    anchor = (
        geometry.representative_point()
        if geometry.geom_type in {"Polygon", "MultiPolygon"}
        else (
            geometry.interpolate(0.5, normalized=True)
            if geometry.geom_type in {"LineString", "MultiLineString"}
            else geometry
        )
    )
    page_x, page_y = scene_point_to_page(bounds, anchor.x, anchor.y)
    width = _measure_text_width_pt(text, size_pt, font_role) + 7.0
    height = size_pt * 1.25 + 5.0
    return SceneLabel(
        text=text,
        x_m=float(anchor.x),
        y_m=float(anchor.y),
        priority=priority,
        font_role=font_role,
        size_pt=size_pt,
        source_layer=source_layer,
        bbox_pt=(
            page_x - width / 2,
            page_y - height / 2,
            page_x + width / 2,
            page_y + height / 2,
        ),
    )


def _accepted_labels(
    bounds: tuple[float, float, float, float],
    edition: str,
    layers_by_id: dict[str, SceneLayer],
) -> tuple[SceneLabel, ...]:
    candidates = []
    primary_layer = (
        layers_by_id["boundaries"]
        if edition == "current"
        else layers_by_id["legacy-reference-centers"]
    )
    for feature in primary_layer.features:
        candidates.append(
            _label_candidate(
                bounds,
                feature.name,
                feature.geometry,
                priority=1,
                font_role="semibold",
                size_pt=20.0 if edition == "current" else 14.0,
                source_layer=primary_layer.layer_id,
            )
        )
    for feature in layers_by_id["streets"].features:
        road_class = feature.property("road_class")
        if road_class not in {"primary", "secondary", "tertiary"}:
            continue
        candidates.append(
            _label_candidate(
                bounds,
                feature.name,
                feature.geometry,
                priority=2,
                font_role="regular",
                size_pt=12.0 if road_class == "primary" else 10.5,
                source_layer="streets",
            )
        )
    for feature in layers_by_id["hydro"].features:
        candidates.append(
            _label_candidate(
                bounds,
                feature.name,
                feature.geometry,
                priority=3,
                font_role="regular",
                size_pt=11.0,
                source_layer="hydro",
            )
        )
    for feature in layers_by_id["neighborhoods"].features:
        candidates.append(
            _label_candidate(
                bounds,
                feature.name,
                feature.geometry,
                priority=4,
                font_role="regular",
                size_pt=9.5,
                source_layer="neighborhoods",
            )
        )
    for feature in layers_by_id["poi"].features:
        candidates.append(
            _label_candidate(
                bounds,
                feature.name,
                feature.geometry,
                priority=5,
                font_role="regular",
                size_pt=9.0,
                source_layer="poi",
            )
        )

    accepted: list[SceneLabel] = []
    for candidate in candidates:
        if any(
            candidate.overlaps(existing)
            for existing in accepted
            if existing.priority < candidate.priority
            or (
                candidate.priority > 1
                and existing.priority == candidate.priority
            )
        ):
            continue
        accepted.append(candidate)
    return tuple(accepted)


def _attribution(layers: NormalizedMapLayers) -> str:
    licenses = []
    for record in layers.source_manifest.values():
        license_name = str(record.get("license", "")).strip()
        if license_name and license_name not in licenses:
            licenses.append(license_name)
    if not licenses:
        return "Nguồn: OpenStreetMap (ODbL); Wikidata (CC0)."
    return "Nguồn dữ liệu: " + "; ".join(licenses) + "."


def _scale_bar_m(bounds: tuple[float, float, float, float]) -> int:
    target = (bounds[2] - bounds[0]) / 5.0
    choices = (100, 200, 500, 1_000, 2_000, 5_000, 10_000)
    return max((value for value in choices if value <= target), default=100)


def _legend(edition: str) -> tuple[LegendItem, ...]:
    edition_item = (
        LegendItem(
            "Địa giới phường hiện hành",
            BOUNDARY_FILL_COLOR,
            "fill",
        )
        if edition == "current"
        else LegendItem(
            "Điểm tham chiếu phường cũ",
            LEGACY_POINT_COLOR,
            "point",
        )
    )
    return (
        edition_item,
        LegendItem("Đường chính", PRIMARY_ROAD_COLOR, "line"),
        LegendItem("Sông, kênh", HYDRO_COLOR, "line"),
        LegendItem("Địa điểm", POI_COLOR, "point"),
    )


def build_scene(
    layers: NormalizedMapLayers,
    edition: Literal["legacy", "current"],
) -> MapScene:
    """Build one immutable scene used by both print-vector renderers."""

    if edition not in {"legacy", "current"}:
        raise ValueError("edition must be 'legacy' or 'current'")
    if len(layers.current_boundaries) != 5:
        raise ValueError("Current edition requires exactly five boundary polygons")
    if len(layers.legacy_ward_centers) != 14:
        raise ValueError("Legacy edition requires exactly 14 reference-center Points")
    if any(point.geometry_type != "Point" for point in layers.legacy_ward_centers):
        raise ValueError("Legacy references must use Point geometry")

    boundaries = (
        tuple(
            _feature(
                item.name,
                item.geometry,
                source_id=item.source_id,
                boundary_claim="true",
            )
            for item in layers.current_boundaries
        )
        if edition == "current"
        else ()
    )
    legacy_centers = (
        tuple(
            _point_feature(
                point,
                source_url=point.source_url,
                boundary_claim="false",
            )
            for point in layers.legacy_ward_centers
        )
        if edition == "legacy"
        else ()
    )
    streets = tuple(
        _feature(
            item.name,
            item.geometry,
            road_class=item.road_class,
            source_id=item.source_id,
            stroke=_road_style(item.road_class)[0],
            stroke_width_pt=str(_road_style(item.road_class)[1]),
        )
        for item in layers.streets
    )
    hydro = tuple(
        _feature(item.name, item.geometry, source_id=item.source_id)
        for item in layers.hydro
    )
    poi = tuple(_point_feature(point) for point in layers.poi)
    neighborhoods = tuple(_point_feature(point) for point in layers.neighborhoods)
    scene_layers = (
        SceneLayer("boundaries", boundaries, BOUNDARY_STYLE),
        SceneLayer(
            "legacy-reference-centers",
            legacy_centers,
            LEGACY_REFERENCE_STYLE,
        ),
        SceneLayer("streets", streets, STREET_STYLE),
        SceneLayer("hydro", hydro, HYDRO_STYLE),
        SceneLayer("poi", poi, POI_STYLE),
        SceneLayer("neighborhoods", neighborhoods, NEIGHBORHOOD_STYLE),
        SceneLayer("labels", (), LABEL_STYLE),
    )
    bounds = _padded_current_bounds(layers)
    layer_index = {layer.layer_id: layer for layer in scene_layers}
    disclaimer = (
        "Bản 14 điểm tham chiếu tên phường cũ; đây là điểm tham chiếu, "
        "không phải ranh giới hành chính cũ."
        if edition == "legacy"
        else ""
    )
    return MapScene(
        edition=edition,
        page_width_pt=A0_LANDSCAPE_WIDTH_PT,
        page_height_pt=A0_LANDSCAPE_HEIGHT_PT,
        bounds_m=bounds,
        layers=scene_layers,
        labels=_accepted_labels(bounds, edition, layer_index),
        attribution=_attribution(layers),
        title="BẢN ĐỒ THỦ DẦU MỘT",
        subtitle=(
            "14 phường cũ — điểm tham chiếu tên gọi"
            if edition == "legacy"
            else "5 phường hiện hành — địa giới hành chính"
        ),
        disclaimer=disclaimer,
        legend=_legend(edition),
        scale_bar_m=_scale_bar_m(bounds),
    )

"""Vector and geographic renderers for Thu Dau Mot map products."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

from fontTools.ttLib import TTFont as FontToolsTTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry

from .geometry import NormalizedMapLayers
from .scene import (
    FONT_FAMILY,
    INK_COLOR,
    MAP_MARGIN_LEFT_PT,
    MUTED_INK_COLOR,
    PAPER_COLOR,
    MapScene,
    SceneFeature,
    SceneLayer,
    scene_point_to_page,
    source_attribution,
)


SVG_NAMESPACE = "http://www.w3.org/2000/svg"
KML_NAMESPACE = "http://www.opengis.net/kml/2.2"
ElementTree.register_namespace("", SVG_NAMESPACE)

_PDF_FONT_REGULAR = "BeVietnamProMapRegular"
_PDF_FONT_SEMIBOLD = "BeVietnamProMapSemiBold"
LEGACY_EDITION_DESCRIPTION = (
    "Bản 14 ranh phường cũ tham khảo; Hòa Phú và Phú Tân là ranh suy luận "
    "biên tập, không thay thế hồ sơ địa chính."
)
CURRENT_EDITION_DESCRIPTION = (
    "Bản 5 địa giới phường hiện hành sau sắp xếp 2025."
)
VIETNAMESE_PRODUCT_GLYPHS = (
    "ÀÁÃÈÉÌÍÒÓÕÙÚÝàáãèéìíòóõùúý"
    "ĂăÂâĐđÊêĨĩÔôƠơŨũƯư"
    + "".join(chr(codepoint) for codepoint in range(0x1EA0, 0x1EFA))
    + "\u0300\u0301\u0303\u0309\u0323"
)


def _svg(tag: str) -> str:
    return f"{{{SVG_NAMESPACE}}}{tag}"


def _kml(tag: str) -> str:
    return f"{{{KML_NAMESPACE}}}{tag}"


def _edition_description(edition: Literal["legacy", "current"]) -> str:
    return (
        LEGACY_EDITION_DESCRIPTION
        if edition == "legacy"
        else CURRENT_EDITION_DESCRIPTION
    )


def _font_paths(fonts: Mapping[str, str | Path]) -> tuple[Path, Path]:
    try:
        regular = Path(fonts["regular"])
        semibold = Path(fonts["semibold"])
    except (KeyError, TypeError) as exc:
        raise ValueError("fonts must provide regular and semibold TTF paths") from exc
    for role, path in (("regular", regular), ("semibold", semibold)):
        if not path.is_file():
            raise ValueError(f"{role} font does not exist: {path}")
    return regular, semibold


def validate_font_coverage(fonts: Mapping[str, str | Path]) -> None:
    """Reject product fonts that cannot preserve Vietnamese text."""

    required = {ord(character) for character in VIETNAMESE_PRODUCT_GLYPHS}
    for role, path in zip(("regular", "semibold"), _font_paths(fonts)):
        font = FontToolsTTFont(path, lazy=True)
        try:
            cmap = font.getBestCmap() or {}
        finally:
            font.close()
        missing = sorted(required - set(cmap))
        if missing:
            preview = ", ".join(f"U+{value:04X}" for value in missing[:8])
            raise ValueError(
                f"{role} font lacks Vietnamese glyph coverage: {preview}"
            )


def _output_path(path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _page_xy(
    scene: MapScene,
    x_m: float,
    y_m: float,
    *,
    svg: bool,
) -> tuple[float, float]:
    x_pt, y_pt = scene_point_to_page(scene, x_m, y_m)
    return (x_pt, scene.page_height_pt - y_pt if svg else y_pt)


def _svg_ring_path(scene: MapScene, coordinates) -> str:
    points = [
        _page_xy(scene, float(x), float(y), svg=True)
        for x, y, *_rest in coordinates
    ]
    if not points:
        return ""
    commands = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    commands.extend(f"L {x:.2f} {y:.2f}" for x, y in points[1:])
    commands.append("Z")
    return " ".join(commands)


def _svg_line_path(scene: MapScene, coordinates) -> str:
    points = [
        _page_xy(scene, float(x), float(y), svg=True)
        for x, y, *_rest in coordinates
    ]
    if not points:
        return ""
    return " ".join(
        [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
        + [f"L {x:.2f} {y:.2f}" for x, y in points[1:]]
    )


def _svg_geometry_path(scene: MapScene, geometry: BaseGeometry) -> str:
    if isinstance(geometry, Polygon):
        parts = [_svg_ring_path(scene, geometry.exterior.coords)]
        parts.extend(_svg_ring_path(scene, ring.coords) for ring in geometry.interiors)
        return " ".join(parts)
    if isinstance(geometry, MultiPolygon):
        return " ".join(
            _svg_geometry_path(scene, polygon) for polygon in geometry.geoms
        )
    if isinstance(geometry, LineString):
        return _svg_line_path(scene, geometry.coords)
    if isinstance(geometry, MultiLineString):
        return " ".join(
            _svg_line_path(scene, line.coords) for line in geometry.geoms
        )
    return ""


def _svg_feature(
    group: ElementTree.Element,
    scene: MapScene,
    layer: SceneLayer,
    feature: SceneFeature,
) -> None:
    geometry = feature.geometry
    if isinstance(geometry, Point):
        x, y = _page_xy(scene, geometry.x, geometry.y, svg=True)
        ElementTree.SubElement(
            group,
            _svg("circle"),
            {
                "cx": f"{x:.2f}",
                "cy": f"{y:.2f}",
                "r": f"{layer.style.point_radius_pt:.2f}",
                "fill": layer.style.fill,
                "stroke": layer.style.stroke,
                "stroke-width": f"{layer.style.stroke_width_pt:.2f}",
                "data-name": feature.name,
            },
        )
        return
    path_data = _svg_geometry_path(scene, geometry)
    if not path_data:
        return
    stroke = feature.property("stroke", layer.style.stroke)
    stroke_width = feature.property(
        "stroke_width_pt",
        str(layer.style.stroke_width_pt),
    )
    attributes = {
        "d": path_data,
        "fill": feature.property("fill", layer.style.fill),
        "fill-opacity": f"{layer.style.fill_opacity:.3f}",
        "stroke": stroke,
        "stroke-width": stroke_width,
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
        "fill-rule": "evenodd",
        "data-name": feature.name,
    }
    if layer.style.dash:
        attributes["stroke-dasharray"] = " ".join(
            f"{value:.2f}" for value in layer.style.dash
        )
    ElementTree.SubElement(group, _svg("path"), attributes)


def _scale_bar_length_pt(scene: MapScene) -> float:
    start_x = scene.bounds_m[0]
    start_y = scene.bounds_m[1]
    page_start = scene_point_to_page(scene, start_x, start_y)[0]
    page_end = scene_point_to_page(
        scene,
        start_x + scene.scale_bar_m,
        start_y,
    )[0]
    return page_end - page_start


def _svg_furniture(root: ElementTree.Element, scene: MapScene) -> None:
    group = ElementTree.SubElement(root, _svg("g"), {"id": "map-furniture"})
    ElementTree.SubElement(
        group,
        _svg("text"),
        {
            "x": f"{MAP_MARGIN_LEFT_PT:.2f}",
            "y": "92",
            "font-size": "38",
            "font-weight": "600",
            "fill": INK_COLOR,
        },
    ).text = scene.title
    ElementTree.SubElement(
        group,
        _svg("text"),
        {
            "x": f"{MAP_MARGIN_LEFT_PT:.2f}",
            "y": "132",
            "font-size": "18",
            "fill": MUTED_INK_COLOR,
        },
    ).text = scene.subtitle

    legend_y = scene.page_height_pt - 105
    legend_x = MAP_MARGIN_LEFT_PT
    for item in scene.legend:
        item_group = ElementTree.SubElement(
            group,
            _svg("g"),
            {"class": "legend-item"},
        )
        if item.symbol == "fill":
            ElementTree.SubElement(
                item_group,
                _svg("rect"),
                {
                    "x": f"{legend_x:.2f}",
                    "y": f"{legend_y - 12:.2f}",
                    "width": "28",
                    "height": "18",
                    "rx": "2",
                    "fill": item.color,
                    "stroke": INK_COLOR,
                    "stroke-width": "1",
                },
            )
        elif item.symbol == "line":
            ElementTree.SubElement(
                item_group,
                _svg("line"),
                {
                    "x1": f"{legend_x:.2f}",
                    "x2": f"{legend_x + 28:.2f}",
                    "y1": f"{legend_y - 3:.2f}",
                    "y2": f"{legend_y - 3:.2f}",
                    "stroke": item.color,
                    "stroke-width": "5",
                    "stroke-linecap": "round",
                },
            )
        else:
            ElementTree.SubElement(
                item_group,
                _svg("circle"),
                {
                    "cx": f"{legend_x + 14:.2f}",
                    "cy": f"{legend_y - 3:.2f}",
                    "r": "6",
                    "fill": item.color,
                },
            )
        ElementTree.SubElement(
            item_group,
            _svg("text"),
            {
                "x": f"{legend_x + 38:.2f}",
                "y": f"{legend_y + 2:.2f}",
                "font-size": "12",
                "fill": INK_COLOR,
            },
        ).text = item.label
        legend_x += 38 + len(item.label) * 7.2

    scale_length = _scale_bar_length_pt(scene)
    scale_x = scene.page_width_pt - MAP_MARGIN_LEFT_PT - scale_length
    scale_y = scene.page_height_pt - 105
    ElementTree.SubElement(
        group,
        _svg("line"),
        {
            "x1": f"{scale_x:.2f}",
            "x2": f"{scale_x + scale_length:.2f}",
            "y1": f"{scale_y:.2f}",
            "y2": f"{scale_y:.2f}",
            "stroke": INK_COLOR,
            "stroke-width": "3",
        },
    )
    for tick_x in (scale_x, scale_x + scale_length):
        ElementTree.SubElement(
            group,
            _svg("line"),
            {
                "x1": f"{tick_x:.2f}",
                "x2": f"{tick_x:.2f}",
                "y1": f"{scale_y - 6:.2f}",
                "y2": f"{scale_y + 6:.2f}",
                "stroke": INK_COLOR,
                "stroke-width": "2",
            },
        )
    ElementTree.SubElement(
        group,
        _svg("text"),
        {
            "x": f"{scale_x + scale_length / 2:.2f}",
            "y": f"{scale_y - 13:.2f}",
            "font-size": "12",
            "text-anchor": "middle",
            "fill": INK_COLOR,
        },
    ).text = (
        f"{scene.scale_bar_m // 1000} km"
        if scene.scale_bar_m >= 1000
        else f"{scene.scale_bar_m} m"
    )
    footer_y = scene.page_height_pt - 44
    if scene.disclaimer:
        ElementTree.SubElement(
            group,
            _svg("text"),
            {
                "x": f"{MAP_MARGIN_LEFT_PT:.2f}",
                "y": f"{footer_y - 22:.2f}",
                "font-size": "12",
                "font-weight": "600",
                "fill": "#8C3F2B",
            },
        ).text = scene.disclaimer
    ElementTree.SubElement(
        group,
        _svg("text"),
        {
            "x": f"{MAP_MARGIN_LEFT_PT:.2f}",
            "y": f"{footer_y:.2f}",
            "font-size": "8",
            "fill": MUTED_INK_COLOR,
        },
    ).text = scene.attribution

    north = scene.north_arrow
    north_y = scene.page_height_pt - north.y_pt
    north_group = ElementTree.SubElement(
        root,
        _svg("g"),
        {
            "id": "north-arrow",
            "transform": f"translate({north.x_pt:.2f} {north_y:.2f})",
        },
    )
    ElementTree.SubElement(
        north_group,
        _svg("text"),
        {
            "x": "0",
            "y": f"{-north.size_pt - 18:.2f}",
            "font-size": "13",
            "font-weight": "600",
            "text-anchor": "middle",
            "fill": INK_COLOR,
        },
    ).text = north.label
    ElementTree.SubElement(
        north_group,
        _svg("line"),
        {
            "x1": "0",
            "y1": f"{north.size_pt:.2f}",
            "x2": "0",
            "y2": f"{-north.size_pt:.2f}",
            "stroke": INK_COLOR,
            "stroke-width": "3",
        },
    )
    ElementTree.SubElement(
        north_group,
        _svg("path"),
        {
            "d": (
                f"M 0 {-north.size_pt - 8:.2f} "
                f"L -10 {-north.size_pt + 12:.2f} "
                f"L 0 {-north.size_pt + 7:.2f} "
                f"L 10 {-north.size_pt + 12:.2f} Z"
            ),
            "fill": INK_COLOR,
        },
    )


def render_svg(
    scene: MapScene,
    path: str | Path,
    fonts: Mapping[str, str | Path],
) -> Path:
    """Render one self-contained, layered SVG with editable text."""

    validate_font_coverage(fonts)
    regular, semibold = _font_paths(fonts)
    output = _output_path(path)
    root = ElementTree.Element(
        _svg("svg"),
        {
            "width": "1189mm",
            "height": "841mm",
            "viewBox": (
                f"0 0 {scene.page_width_pt:.3f} {scene.page_height_pt:.3f}"
            ),
            "version": "1.1",
        },
    )
    ElementTree.SubElement(root, _svg("title")).text = (
        f"{scene.title} — {scene.subtitle}"
    )
    ElementTree.SubElement(
        root,
        _svg("metadata"),
        {"id": "edition-metadata"},
    ).text = _edition_description(scene.edition)
    definitions = ElementTree.SubElement(root, _svg("defs"))
    regular_data = base64.b64encode(regular.read_bytes()).decode("ascii")
    semibold_data = base64.b64encode(semibold.read_bytes()).decode("ascii")
    ElementTree.SubElement(definitions, _svg("style")).text = (
        f"@font-face{{font-family:'{FONT_FAMILY}';"
        "src:url(data:font/ttf;base64,"
        f"{regular_data}) format('truetype');font-weight:400;}}"
        f"@font-face{{font-family:'{FONT_FAMILY}';"
        "src:url(data:font/ttf;base64,"
        f"{semibold_data}) format('truetype');font-weight:600;}}"
        f"text{{font-family:'{FONT_FAMILY}',sans-serif;}}"
    )
    ElementTree.SubElement(
        root,
        _svg("rect"),
        {
            "id": "paper",
            "width": "100%",
            "height": "100%",
            "fill": PAPER_COLOR,
        },
    )
    for layer in scene.layers:
        group = ElementTree.SubElement(root, _svg("g"), {"id": layer.layer_id})
        if layer.layer_id == "labels":
            for label in scene.labels:
                x, y = _page_xy(scene, label.x_m, label.y_m, svg=True)
                color = (
                    "#397C93"
                    if label.source_layer == "hydro"
                    else (
                        "#9B5937"
                        if label.source_layer == "streets"
                        else INK_COLOR
                    )
                )
                ElementTree.SubElement(
                    group,
                    _svg("text"),
                    {
                        "x": f"{x:.2f}",
                        "y": f"{y:.2f}",
                        "font-size": f"{label.size_pt:.2f}",
                        "font-weight": (
                            "600" if label.font_role == "semibold" else "400"
                        ),
                        "text-anchor": "middle",
                        "dominant-baseline": "middle",
                        "fill": color,
                        "data-priority": str(label.priority),
                        "data-source-layer": label.source_layer,
                    },
                ).text = label.text
            continue
        for feature in layer.features:
            _svg_feature(group, scene, layer, feature)
    _svg_furniture(root, scene)
    ElementTree.indent(root, space="  ")
    output.write_bytes(
        ElementTree.tostring(
            root,
            encoding="utf-8",
            xml_declaration=True,
        )
    )
    return output


def _register_pdf_fonts(fonts: Mapping[str, str | Path]) -> None:
    regular, semibold = _font_paths(fonts)
    # ReportLab TTFont instances carry per-document subset state. Replace them
    # for every output so a second edition cannot inherit the first PDF's cmap.
    pdfmetrics.registerFont(TTFont(_PDF_FONT_REGULAR, str(regular)))
    pdfmetrics.registerFont(TTFont(_PDF_FONT_SEMIBOLD, str(semibold)))


def _pdf_font_name(font_role: str) -> str:
    return (
        _PDF_FONT_SEMIBOLD
        if font_role == "semibold"
        else _PDF_FONT_REGULAR
    )


def _pdf_text_width(text: str, font_name: str, size_pt: float) -> float:
    return pdfmetrics.stringWidth(text, font_name, size_pt)


def _pdf_draw_text(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    baseline_y: float,
    *,
    font_role: str,
    size_pt: float,
    color: str,
    align: Literal["left", "center"] = "left",
) -> float:
    """Draw complete Unicode text with the validated product font."""

    font_name = _pdf_font_name(font_role)
    width = _pdf_text_width(text, font_name, size_pt)
    pdf.setFont(font_name, size_pt)
    pdf.setFillColor(HexColor(color))
    if align == "center":
        pdf.drawCentredString(x, baseline_y, text)
    else:
        pdf.drawString(x, baseline_y, text)
    return width


def _pdf_add_ring(pdf_path, scene: MapScene, coordinates) -> None:
    points = [
        _page_xy(scene, float(x), float(y), svg=False)
        for x, y, *_rest in coordinates
    ]
    if not points:
        return
    pdf_path.moveTo(*points[0])
    for point in points[1:]:
        pdf_path.lineTo(*point)
    pdf_path.close()


def _pdf_add_line(pdf_path, scene: MapScene, coordinates) -> None:
    points = [
        _page_xy(scene, float(x), float(y), svg=False)
        for x, y, *_rest in coordinates
    ]
    if not points:
        return
    pdf_path.moveTo(*points[0])
    for point in points[1:]:
        pdf_path.lineTo(*point)


def _pdf_geometry_path(pdf: canvas.Canvas, scene: MapScene, geometry):
    path = pdf.beginPath()
    if isinstance(geometry, Polygon):
        _pdf_add_ring(path, scene, geometry.exterior.coords)
        for ring in geometry.interiors:
            _pdf_add_ring(path, scene, ring.coords)
    elif isinstance(geometry, MultiPolygon):
        for polygon in geometry.geoms:
            _pdf_add_ring(path, scene, polygon.exterior.coords)
            for ring in polygon.interiors:
                _pdf_add_ring(path, scene, ring.coords)
    elif isinstance(geometry, LineString):
        _pdf_add_line(path, scene, geometry.coords)
    elif isinstance(geometry, MultiLineString):
        for line in geometry.geoms:
            _pdf_add_line(path, scene, line.coords)
    return path


def _pdf_layer(pdf: canvas.Canvas, scene: MapScene, layer: SceneLayer) -> None:
    for feature in layer.features:
        geometry = feature.geometry
        if isinstance(geometry, Point):
            x, y = _page_xy(scene, geometry.x, geometry.y, svg=False)
            pdf.setFillColor(HexColor(layer.style.fill))
            pdf.setStrokeColor(HexColor(layer.style.stroke))
            pdf.setLineWidth(layer.style.stroke_width_pt)
            pdf.circle(
                x,
                y,
                layer.style.point_radius_pt,
                stroke=1,
                fill=1,
            )
            continue
        stroke = feature.property("stroke", layer.style.stroke)
        stroke_width = float(
            feature.property(
                "stroke_width_pt",
                str(layer.style.stroke_width_pt),
            )
        )
        pdf.setStrokeColor(HexColor(stroke))
        pdf.setLineWidth(stroke_width)
        pdf.setLineCap(1)
        pdf.setLineJoin(1)
        if layer.style.dash:
            pdf.setDash(*layer.style.dash)
        else:
            pdf.setDash()
        fill_color = feature.property("fill", layer.style.fill)
        fill = fill_color != "none"
        if fill:
            pdf.setFillColor(HexColor(fill_color))
            pdf.setFillAlpha(layer.style.fill_opacity)
        geometry_path = _pdf_geometry_path(pdf, scene, geometry)
        pdf.drawPath(
            geometry_path,
            stroke=stroke != "none",
            fill=fill,
            fillMode=0,
        )
        pdf.setFillAlpha(1)


def _pdf_labels(pdf: canvas.Canvas, scene: MapScene) -> None:
    for label in scene.labels:
        x, y = _page_xy(scene, label.x_m, label.y_m, svg=False)
        color = (
            "#397C93"
            if label.source_layer == "hydro"
            else (
                "#9B5937"
                if label.source_layer == "streets"
                else INK_COLOR
            )
        )
        _pdf_draw_text(
            pdf,
            label.text,
            x,
            y - label.size_pt * 0.34,
            font_role=label.font_role,
            size_pt=label.size_pt,
            color=color,
            align="center",
        )


def _pdf_furniture(pdf: canvas.Canvas, scene: MapScene) -> None:
    _pdf_draw_text(
        pdf,
        scene.title,
        MAP_MARGIN_LEFT_PT,
        scene.page_height_pt - 92,
        font_role="semibold",
        size_pt=38,
        color=INK_COLOR,
    )
    _pdf_draw_text(
        pdf,
        scene.subtitle,
        MAP_MARGIN_LEFT_PT,
        scene.page_height_pt - 132,
        font_role="regular",
        size_pt=18,
        color=MUTED_INK_COLOR,
    )

    legend_x = MAP_MARGIN_LEFT_PT
    legend_y = 100
    for item in scene.legend:
        pdf.setFillColor(HexColor(item.color))
        pdf.setStrokeColor(HexColor(INK_COLOR))
        if item.symbol == "fill":
            pdf.roundRect(legend_x, legend_y - 7, 28, 18, 2, stroke=1, fill=1)
        elif item.symbol == "line":
            pdf.setLineWidth(5)
            pdf.line(legend_x, legend_y + 2, legend_x + 28, legend_y + 2)
        else:
            pdf.circle(legend_x + 14, legend_y + 2, 6, stroke=0, fill=1)
        item_width = _pdf_draw_text(
            pdf,
            item.label,
            legend_x + 38,
            legend_y - 2,
            font_role="regular",
            size_pt=12,
            color=INK_COLOR,
        )
        legend_x += 38 + item_width + 25

    scale_length = _scale_bar_length_pt(scene)
    scale_x = scene.page_width_pt - MAP_MARGIN_LEFT_PT - scale_length
    scale_y = 100
    pdf.setStrokeColor(HexColor(INK_COLOR))
    pdf.setLineWidth(3)
    pdf.line(scale_x, scale_y, scale_x + scale_length, scale_y)
    pdf.setLineWidth(2)
    for tick_x in (scale_x, scale_x + scale_length):
        pdf.line(tick_x, scale_y - 6, tick_x, scale_y + 6)
    scale_label = (
        f"{scene.scale_bar_m // 1000} km"
        if scene.scale_bar_m >= 1000
        else f"{scene.scale_bar_m} m"
    )
    _pdf_draw_text(
        pdf,
        scale_label,
        scale_x + scale_length / 2,
        scale_y + 13,
        font_role="regular",
        size_pt=12,
        color=INK_COLOR,
        align="center",
    )

    if scene.disclaimer:
        _pdf_draw_text(
            pdf,
            scene.disclaimer,
            MAP_MARGIN_LEFT_PT,
            57,
            font_role="semibold",
            size_pt=12,
            color="#8C3F2B",
        )
    _pdf_draw_text(
        pdf,
        scene.attribution,
        MAP_MARGIN_LEFT_PT,
        36,
        font_role="regular",
        size_pt=8,
        color=MUTED_INK_COLOR,
    )

    north = scene.north_arrow
    pdf.setStrokeColor(HexColor(INK_COLOR))
    pdf.setFillColor(HexColor(INK_COLOR))
    pdf.setLineWidth(3)
    pdf.line(
        north.x_pt,
        north.y_pt - north.size_pt,
        north.x_pt,
        north.y_pt + north.size_pt,
    )
    arrow = pdf.beginPath()
    arrow.moveTo(north.x_pt, north.y_pt + north.size_pt + 8)
    arrow.lineTo(north.x_pt - 10, north.y_pt + north.size_pt - 12)
    arrow.lineTo(north.x_pt, north.y_pt + north.size_pt - 7)
    arrow.lineTo(north.x_pt + 10, north.y_pt + north.size_pt - 12)
    arrow.close()
    pdf.drawPath(arrow, stroke=0, fill=1)
    _pdf_draw_text(
        pdf,
        north.label,
        north.x_pt,
        north.y_pt + north.size_pt + 18,
        font_role="semibold",
        size_pt=13,
        color=INK_COLOR,
        align="center",
    )


def render_pdf(
    scene: MapScene,
    path: str | Path,
    fonts: Mapping[str, str | Path],
) -> Path:
    """Render one single-page, all-vector landscape A0 PDF."""

    validate_font_coverage(fonts)
    _register_pdf_fonts(fonts)
    output = _output_path(path)
    pdf = canvas.Canvas(
        str(output),
        pagesize=(scene.page_width_pt, scene.page_height_pt),
        pageCompression=1,
        invariant=1,
    )
    pdf.setTitle(f"{scene.title} — {scene.subtitle}")
    pdf.setAuthor("Radar BDS")
    pdf.setSubject(_edition_description(scene.edition))
    pdf.setFillColor(HexColor(PAPER_COLOR))
    pdf.rect(
        0,
        0,
        scene.page_width_pt,
        scene.page_height_pt,
        stroke=0,
        fill=1,
    )
    for layer in scene.layers:
        if layer.layer_id == "labels":
            _pdf_labels(pdf, scene)
        else:
            _pdf_layer(pdf, scene, layer)
    _pdf_furniture(pdf, scene)
    pdf.showPage()
    pdf.save()
    return output


def _kml_data(parent, name: str, value: str | bool) -> None:
    data = ElementTree.SubElement(
        parent,
        _kml("Data"),
        {"name": name},
    )
    ElementTree.SubElement(data, _kml("value")).text = (
        str(value).lower() if isinstance(value, bool) else str(value)
    )


def _kml_coordinates(coordinates) -> str:
    return " ".join(
        f"{float(x):.8f},{float(y):.8f},0"
        for x, y, *_rest in coordinates
    )


def _kml_polygon(parent, polygon: Polygon) -> None:
    polygon_element = ElementTree.SubElement(parent, _kml("Polygon"))
    ElementTree.SubElement(polygon_element, _kml("tessellate")).text = "1"
    outer = ElementTree.SubElement(
        polygon_element,
        _kml("outerBoundaryIs"),
    )
    ring = ElementTree.SubElement(outer, _kml("LinearRing"))
    ElementTree.SubElement(ring, _kml("coordinates")).text = _kml_coordinates(
        polygon.exterior.coords
    )
    for interior in polygon.interiors:
        inner = ElementTree.SubElement(
            polygon_element,
            _kml("innerBoundaryIs"),
        )
        inner_ring = ElementTree.SubElement(inner, _kml("LinearRing"))
        ElementTree.SubElement(
            inner_ring,
            _kml("coordinates"),
        ).text = _kml_coordinates(interior.coords)


def _kml_geometry(parent, geometry: BaseGeometry) -> None:
    if isinstance(geometry, Point):
        point = ElementTree.SubElement(parent, _kml("Point"))
        ElementTree.SubElement(point, _kml("coordinates")).text = (
            f"{geometry.x:.8f},{geometry.y:.8f},0"
        )
    elif isinstance(geometry, Polygon):
        _kml_polygon(parent, geometry)
    elif isinstance(geometry, MultiPolygon):
        multi = ElementTree.SubElement(parent, _kml("MultiGeometry"))
        for polygon in geometry.geoms:
            _kml_polygon(multi, polygon)
    elif isinstance(geometry, LineString):
        line = ElementTree.SubElement(parent, _kml("LineString"))
        ElementTree.SubElement(line, _kml("tessellate")).text = "1"
        ElementTree.SubElement(line, _kml("coordinates")).text = _kml_coordinates(
            geometry.coords
        )
    elif isinstance(geometry, MultiLineString):
        multi = ElementTree.SubElement(parent, _kml("MultiGeometry"))
        for part in geometry.geoms:
            _kml_geometry(multi, part)


def _kml_placemark(
    folder,
    name: str,
    geometry: BaseGeometry,
    *,
    edition: str,
    source: str,
    boundary_claim: bool | None = None,
    extra_data: Mapping[str, str] | None = None,
) -> None:
    placemark = ElementTree.SubElement(folder, _kml("Placemark"))
    ElementTree.SubElement(placemark, _kml("name")).text = name
    extended = ElementTree.SubElement(placemark, _kml("ExtendedData"))
    _kml_data(extended, "edition", edition)
    _kml_data(extended, "source", source)
    if boundary_claim is not None:
        _kml_data(extended, "boundary_claim", boundary_claim)
    for key, value in sorted((extra_data or {}).items()):
        _kml_data(extended, key, value)
    _kml_geometry(placemark, geometry)


def _kml_folder(document, name: str):
    folder = ElementTree.SubElement(document, _kml("Folder"))
    ElementTree.SubElement(folder, _kml("name")).text = name
    return folder


def render_kml(
    layers: NormalizedMapLayers,
    edition: Literal["legacy", "current"],
    path: str | Path,
) -> Path:
    """Render geographic WGS84 layers without print-only furniture."""

    if edition not in {"legacy", "current"}:
        raise ValueError("edition must be 'legacy' or 'current'")
    if len(layers.current_boundaries) != 5:
        raise ValueError("Current edition requires exactly five boundary polygons")
    if len(layers.legacy_boundaries) != 14:
        raise ValueError("Legacy edition requires exactly 14 boundary polygons")
    if len(layers.legacy_ward_centers) != 14:
        raise ValueError("Legacy edition requires exactly 14 reference-center Points")

    ElementTree.register_namespace("", KML_NAMESPACE)
    root = ElementTree.Element(_kml("kml"))
    document = ElementTree.SubElement(root, _kml("Document"))
    ElementTree.SubElement(document, _kml("name")).text = (
        f"Thủ Dầu Một — {edition}"
    )
    document_data = ElementTree.SubElement(document, _kml("ExtendedData"))
    _kml_data(document_data, "edition", edition)
    _kml_data(
        document_data,
        "source",
        "OpenStreetMap ODbL; Stanford/GADM snapshot; Radar BDS derived geometry",
    )
    _kml_data(
        document_data,
        "attribution",
        source_attribution(layers),
    )
    _kml_data(
        document_data,
        "edition_description",
        _edition_description(edition),
    )
    if edition == "current":
        folder = _kml_folder(document, "boundaries")
        for item in layers.current_boundaries:
            _kml_placemark(
                folder,
                item.name,
                item.geometry,
                edition=edition,
                source=item.source_id or "current boundary snapshot",
                boundary_claim=True,
            )
    else:
        folder = _kml_folder(document, "legacy-boundaries")
        for item in layers.legacy_boundaries:
            _kml_placemark(
                folder,
                item.name,
                item.geometry,
                edition=edition,
                source=item.properties.get("source", item.source_id),
                boundary_claim=True,
                extra_data={
                    "boundary_source": item.properties.get("boundary_source", ""),
                    "derived_from": item.properties.get("derived_from", ""),
                    "source_id": item.source_id,
                    "source_url": item.properties.get("source_url", ""),
                },
            )

    street_folder = _kml_folder(document, "streets")
    for item in layers.streets:
        _kml_placemark(
            street_folder,
            item.name,
            item.geometry,
            edition=edition,
            source=item.source_id or "OpenStreetMap",
            extra_data={"road_class": item.road_class},
        )
    hydro_folder = _kml_folder(document, "hydro")
    for item in layers.hydro:
        _kml_placemark(
            hydro_folder,
            item.name,
            item.geometry,
            edition=edition,
            source=item.source_id or "OpenStreetMap",
        )
    for layer_name, points in (
        ("poi", layers.poi),
        ("neighborhoods", layers.neighborhoods),
    ):
        point_folder = _kml_folder(document, layer_name)
        for point in points:
            _kml_placemark(
                point_folder,
                point.name,
                Point(point.lon, point.lat),
                edition=edition,
                source=point.source,
                extra_data={"confidence": point.confidence},
            )

    output = _output_path(path)
    ElementTree.indent(root, space="  ")
    output.write_bytes(
        ElementTree.tostring(
            root,
            encoding="utf-8",
            xml_declaration=True,
        )
    )
    return output

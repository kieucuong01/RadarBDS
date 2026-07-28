from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
import pdfplumber
import pytest
from pypdf import PdfReader
from reportlab.lib import utils as reportlab_utils
from shapely.geometry import LineString, box

from map_products.geometry import (
    NamedGeometry,
    NormalizedMapLayers,
    StreetGeometry,
)
from map_products.models import MapPoint
from map_products.renderers import render_kml, render_pdf, render_svg
from map_products.scene import (
    MAP_LAYER_IDS,
    build_scene,
)


ROOT = Path(__file__).resolve().parents[1]
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}
KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}
VIETNAMESE_PRODUCT_GLYPHS = (
    "ÀÁÃÈÉÌÍÒÓÕÙÚÝàáãèéìíòóõùúý"
    "ĂăÂâĐđÊêĨĩÔôƠơŨũƯư"
    + "".join(chr(codepoint) for codepoint in range(0x1EA0, 0x1EFA))
    + "\u0300\u0301\u0303\u0309\u0323"
)
TEST_FONT_CHARACTERS = (
    "".join(chr(codepoint) for codepoint in range(32, 127))
    + VIETNAMESE_PRODUCT_GLYPHS
    + "©–—"
)


def _build_test_font(
    path: Path,
    *,
    family: str,
    characters: str = TEST_FONT_CHARACTERS,
) -> Path:
    codepoints = sorted({ord(character) for character in characters})
    names = {codepoint: f"uni{codepoint:04X}" for codepoint in codepoints}
    glyph_order = [".notdef", *(names[codepoint] for codepoint in codepoints)]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(names)
    glyphs = {}
    metrics = {}
    for name in glyph_order:
        pen = TTGlyphPen(None)
        if name != "uni0020":
            pen.moveTo((80, 0))
            pen.lineTo((520, 0))
            pen.lineTo((520, 700))
            pen.lineTo((80, 700))
            pen.closePath()
        glyphs[name] = pen.glyph()
        metrics[name] = (600, 0)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
    )
    builder.setupNameTable(
        {
            "familyName": family,
            "styleName": "Regular",
            "uniqueFontIdentifier": f"{family}-Regular",
            "fullName": f"{family} Regular",
            "psName": f"{family.replace(' ', '')}-Regular",
        }
    )
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)
    return path


@pytest.fixture
def sample_layers() -> NormalizedMapLayers:
    boundary_origins = (
        ("Thủ Dầu Một", 106.62, 10.96),
        ("Phú Lợi", 106.65, 10.96),
        ("Chánh Hiệp", 106.68, 10.96),
        ("Bình Dương", 106.62, 10.99),
        ("Phú An", 106.65, 10.99),
    )
    boundaries = tuple(
        NamedGeometry(
            name,
            box(lon, lat, lon + 0.025, lat + 0.025),
            source_id=f"current-{index}",
        )
        for index, (name, lon, lat) in enumerate(boundary_origins)
    )
    legacy_names = (
        "Chánh Mỹ",
        "Chánh Nghĩa",
        "Định Hòa",
        "Hiệp An",
        "Hiệp Thành",
        "Hòa Phú",
        "Phú Cường",
        "Phú Hòa",
        "Phú Lợi",
        "Phú Mỹ",
        "Phú Tân",
        "Phú Thọ",
        "Tân An",
        "Tương Bình Hiệp",
    )
    legacy_centers = tuple(
        MapPoint(
            name=name,
            lon=106.625 + (index % 5) * 0.014,
            lat=10.965 + (index // 5) * 0.014,
            source=f"Wikidata Q{index + 1}",
            source_url=f"https://www.wikidata.org/wiki/Q{index + 1}",
            confidence="high",
            boundary_claim=False,
        )
        for index, name in enumerate(legacy_names)
    )
    streets = (
        StreetGeometry(
            "Đại lộ Bình Dương",
            LineString(((106.621, 10.975), (106.702, 10.975))),
            "primary",
            "way/100",
        ),
        StreetGeometry(
            "Đường Phú Lợi",
            LineString(((106.655, 10.962), (106.655, 11.012))),
            "secondary",
            "way/101",
        ),
        StreetGeometry(
            "Đường thử nhãn A",
            LineString(((106.687, 11.008), (106.704, 11.008))),
            "secondary",
            "way/102",
        ),
        StreetGeometry(
            "Đường thử nhãn B",
            LineString(((106.687, 11.008), (106.704, 11.008))),
            "secondary",
            "way/103",
        ),
    )
    hydro = (
        NamedGeometry(
            "Sông Sài Gòn",
            LineString(((106.622, 10.958), (106.623, 11.014))),
            "way/200",
        ),
    )
    poi = (
        MapPoint(
            "Chợ Thủ Dầu Một",
            106.641,
            10.971,
            "OpenStreetMap node/300",
            "high",
        ),
    )
    neighborhoods = (
        MapPoint(
            "Khu dân cư Chánh Nghĩa",
            106.647,
            10.982,
            "Radar BDS",
            "high",
        ),
    )
    return NormalizedMapLayers(
        current_boundaries=boundaries,
        legacy_ward_centers=legacy_centers,
        streets=streets,
        hydro=hydro,
        poi=poi,
        neighborhoods=neighborhoods,
        source_manifest={
            "current_boundaries": {
                "license": "Open Database License",
                "license_url": "https://www.openstreetmap.org/copyright",
                "url": "https://www.openstreetmap.org/",
            },
            "legacy_ward_centers": {
                "license": "CC0",
                "license_url": "https://www.wikidata.org/wiki/Wikidata:Licensing",
                "url": "https://www.wikidata.org/",
            },
            "font": {
                "license": "SIL Open Font License, Version 1.1",
                "license_url": (
                    "https://github.com/google/fonts/tree/main/ofl/bevietnampro"
                ),
                "url": (
                    "https://raw.githubusercontent.com/google/fonts/main/ofl/"
                    "bevietnampro/BeVietnamPro-Regular.ttf"
                ),
            },
        },
    )


@pytest.fixture
def test_fonts(tmp_path) -> dict[str, Path]:
    return {
        "regular": _build_test_font(
            tmp_path / "regular.ttf",
            family="Be Vietnam Pro Test",
        ),
        "semibold": _build_test_font(
            tmp_path / "semibold.ttf",
            family="Be Vietnam Pro Test SemiBold",
        ),
    }


@pytest.fixture
def legacy_scene(sample_layers):
    return build_scene(sample_layers, "legacy")


def _layer(scene, layer_id: str):
    return next(layer for layer in scene.layers if layer.layer_id == layer_id)


def test_scene_projects_wgs84_once_and_enforces_edition_geometry(sample_layers):
    legacy = build_scene(sample_layers, "legacy")
    current = build_scene(sample_layers, "current")

    assert legacy.page_width_pt > legacy.page_height_pt
    assert legacy.bounds_m[0] > 100_000
    assert legacy.bounds_m == current.bounds_m
    assert {layer.layer_id for layer in legacy.layers} == set(MAP_LAYER_IDS)
    assert len(_layer(legacy, "boundaries").features) == 0
    assert len(_layer(legacy, "legacy-reference-centers").features) == 14
    assert len(_layer(current, "boundaries").features) == 5
    assert len(_layer(current, "legacy-reference-centers").features) == 0
    assert "điểm tham chiếu" in legacy.disclaimer.casefold()
    assert "không phải ranh giới" in legacy.disclaimer.casefold()
    assert current.disclaimer == ""
    assert legacy.scale_bar_m > 0
    assert "Điểm tham chiếu phường cũ" in {
        item.label for item in legacy.legend
    }
    assert "Địa giới phường hiện hành" in {
        item.label for item in current.legend
    }
    assert len(
        {
            feature.property("fill")
            for feature in _layer(current, "boundaries").features
        }
    ) == 5
    assert current.north_arrow.label == "BẮC"
    assert "© OpenStreetMap contributors" in current.attribution
    assert "https://www.openstreetmap.org/copyright" in current.attribution
    assert "Font: Be Vietnam Pro" in current.attribution
    assert "BeVietnamPro-Regular.ttf" in current.attribution
    assert (
        "https://github.com/google/fonts/tree/main/ofl/bevietnampro"
        in current.attribution
    )


def test_scene_label_policy_keeps_primary_labels_and_blocks_lower_priority_overlap(
    sample_layers,
):
    legacy = build_scene(sample_layers, "legacy")
    primary = [label for label in legacy.labels if label.priority == 1]

    assert len(primary) == 14
    assert all(label.font_role == "semibold" for label in primary)
    assert all(
        not lower.overlaps(higher)
        for lower in legacy.labels
        for higher in legacy.labels
        if higher.priority < lower.priority
    )
    lower_priority = [label for label in legacy.labels if label.priority > 1]
    assert all(
        not first.overlaps(second)
        for index, first in enumerate(lower_priority)
        for second in lower_priority[index + 1 :]
        if first.priority == second.priority
    )


def test_svg_is_vector_layered_and_text_editable(
    tmp_path, legacy_scene, test_fonts
):
    output = render_svg(legacy_scene, tmp_path / "map.svg", test_fonts)
    root = ElementTree.parse(output).getroot()

    assert not root.findall(".//svg:image", SVG_NS)
    assert root.findall(".//svg:text", SVG_NS)
    layer_ids = {
        node.attrib["id"]
        for node in root.findall(".//svg:g", SVG_NS)
        if "id" in node.attrib
    }
    assert set(MAP_LAYER_IDS) <= layer_ids
    assert b"font-family:'Be Vietnam Pro'" in output.read_bytes()
    assert "14 điểm tham chiếu" in "".join(root.itertext())
    assert root.find(".//svg:g[@id='north-arrow']", SVG_NS) is not None
    rendered_text = "".join(root.itertext())
    assert "BẮC" in rendered_text
    assert "© OpenStreetMap contributors" in rendered_text
    assert "https://www.openstreetmap.org/copyright" in rendered_text


def test_legacy_svg_carries_override_in_edition_metadata(
    tmp_path,
    legacy_scene,
    test_fonts,
):
    output = render_svg(legacy_scene, tmp_path / "map.svg", test_fonts)
    root = ElementTree.parse(output).getroot()
    metadata = root.find("./svg:metadata[@id='edition-metadata']", SVG_NS)

    assert metadata is not None
    value = (metadata.text or "").casefold()
    assert "14 điểm" in value
    assert "tham chiếu" in value
    assert "không phải ranh giới hành chính cũ" in value


def test_pdf_is_landscape_a0_vector_with_embedded_vietnamese_font(
    tmp_path, legacy_scene, test_fonts
):
    output = render_pdf(legacy_scene, tmp_path / "map.pdf", test_fonts)

    with pdfplumber.open(output) as pdf:
        assert len(pdf.pages) == 1
        assert pdf.pages[0].images == []
        assert sorted(round(float(value)) for value in pdf.pages[0].mediabox[2:]) == [
            2384,
            3370,
        ]
        assert pdf.pages[0].chars
        extracted = pdf.pages[0].extract_text() or ""
        assert "BẢN ĐỒ THỦ DẦU MỘT" in extracted
        assert "14 điểm tham chiếu" in extracted
        assert "BẮC" in extracted
        assert "© OpenStreetMap contributors" in extracted
        assert "https://www.openstreetmap.org/copyright" in extracted
        assert "\x00" not in extracted
    raw = output.read_bytes()
    assert b"/FontFile2" in raw
    assert b"/Subtype /Image" not in raw


def test_legacy_pdf_carries_override_in_document_metadata(
    tmp_path,
    legacy_scene,
    test_fonts,
):
    output = render_pdf(legacy_scene, tmp_path / "map.pdf", test_fonts)
    subject = (PdfReader(output).metadata.subject or "").casefold()

    assert "14 điểm" in subject
    assert "tham chiếu" in subject
    assert "không phải ranh giới hành chính cũ" in subject


def test_pdf_render_is_byte_deterministic_when_clock_changes(
    tmp_path,
    legacy_scene,
    test_fonts,
    monkeypatch,
):
    monkeypatch.setattr(reportlab_utils.time, "time", lambda: 1_700_000_000)
    first = render_pdf(legacy_scene, tmp_path / "first.pdf", test_fonts)
    monkeypatch.setattr(reportlab_utils.time, "time", lambda: 1_800_000_000)
    second = render_pdf(legacy_scene, tmp_path / "second.pdf", test_fonts)

    assert first.read_bytes() == second.read_bytes()


def test_font_coverage_gate_rejects_missing_vietnamese_glyphs(tmp_path):
    from map_products.renderers import validate_font_coverage

    ascii_font = _build_test_font(
        tmp_path / "ascii-only.ttf",
        family="ASCII Only",
        characters="".join(chr(codepoint) for codepoint in range(32, 127)),
    )

    with pytest.raises(ValueError, match="Vietnamese glyph coverage"):
        validate_font_coverage(
            {"regular": ascii_font, "semibold": ascii_font}
        )


def test_kml_legacy_contains_14_geographic_points_without_boundary_polygons(
    tmp_path, sample_layers
):
    output = render_kml(sample_layers, "legacy", tmp_path / "map.kml")
    root = ElementTree.parse(output).getroot()

    assert root.findall(".//kml:Placemark", KML_NS)
    assert len(root.findall(".//kml:Point", KML_NS)) == 16
    assert not root.findall(".//kml:Polygon", KML_NS)
    assert not root.findall(".//kml:ScreenOverlay", KML_NS)
    assert b"watermark" not in output.read_bytes().lower()
    legacy_folder = next(
        folder
        for folder in root.findall(".//kml:Folder", KML_NS)
        if folder.findtext("kml:name", namespaces=KML_NS)
        == "legacy-reference-centers"
    )
    legacy_points = legacy_folder.findall(".//kml:Point", KML_NS)
    assert len(legacy_points) == 14
    poi_folder = next(
        folder
        for folder in root.findall(".//kml:Folder", KML_NS)
        if folder.findtext("kml:name", namespaces=KML_NS) == "poi"
    )
    neighborhood_folder = next(
        folder
        for folder in root.findall(".//kml:Folder", KML_NS)
        if folder.findtext("kml:name", namespaces=KML_NS) == "neighborhoods"
    )
    assert len(poi_folder.findall(".//kml:Point", KML_NS)) == 1
    assert len(neighborhood_folder.findall(".//kml:Point", KML_NS)) == 1
    values = [
        node.text
        for node in legacy_folder.findall(
            ".//kml:ExtendedData/kml:Data[@name='boundary_claim']/kml:value",
            KML_NS,
        )
    ]
    assert values == ["false"] * 14
    kml_text = "".join(root.itertext())
    assert "© OpenStreetMap contributors" in kml_text
    assert "https://www.openstreetmap.org/copyright" in kml_text
    assert "Font: Be Vietnam Pro" in kml_text


def test_legacy_kml_carries_override_in_document_metadata(
    tmp_path,
    sample_layers,
):
    output = render_kml(sample_layers, "legacy", tmp_path / "map.kml")
    root = ElementTree.parse(output).getroot()
    value = root.findtext(
        "./kml:Document/kml:ExtendedData/"
        "kml:Data[@name='edition_description']/kml:value",
        namespaces=KML_NS,
    )

    assert value is not None
    folded = value.casefold()
    assert "14 điểm" in folded
    assert "tham chiếu" in folded
    assert "không phải ranh giới hành chính cũ" in folded


def test_current_svg_uses_five_distinct_ward_fills(
    tmp_path, sample_layers, test_fonts
):
    scene = build_scene(sample_layers, "current")
    output = render_svg(scene, tmp_path / "current.svg", test_fonts)
    root = ElementTree.parse(output).getroot()
    boundaries = root.find(".//svg:g[@id='boundaries']", SVG_NS)

    assert boundaries is not None
    assert len(
        {path.attrib["fill"] for path in boundaries.findall("svg:path", SVG_NS)}
    ) == 5


def test_kml_current_contains_exactly_five_administrative_boundaries(
    tmp_path, sample_layers
):
    output = render_kml(sample_layers, "current", tmp_path / "map.kml")
    root = ElementTree.parse(output).getroot()
    boundary_folder = next(
        folder
        for folder in root.findall(".//kml:Folder", KML_NS)
        if folder.findtext("kml:name", namespaces=KML_NS) == "boundaries"
    )

    assert len(boundary_folder.findall(".//kml:Polygon", KML_NS)) == 5
    assert not any(
        folder.findtext("kml:name", namespaces=KML_NS)
        == "legacy-reference-centers"
        for folder in root.findall(".//kml:Folder", KML_NS)
    )


def test_product_render_stage_writes_six_edition_format_outputs(
    tmp_path, sample_layers, test_fonts
):
    from scripts.build_thu_dau_mot_map_product import render_product_outputs

    outputs = render_product_outputs(
        sample_layers,
        tmp_path,
        test_fonts,
    )

    assert {path.name for path in outputs} == {
        "thu-dau-mot-current.kml",
        "thu-dau-mot-current.pdf",
        "thu-dau-mot-current.svg",
        "thu-dau-mot-legacy.kml",
        "thu-dau-mot-legacy.pdf",
        "thu-dau-mot-legacy.svg",
    }
    assert all(path.is_file() and path.stat().st_size > 0 for path in outputs)

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PIL import Image
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject
from reportlab.lib.pagesizes import A0, A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from map_products.release import (
    ReleaseBlocked,
    generate_watermarked_previews,
    package_release,
    stage_release_candidate,
    validate_candidate,
)
from scripts.build_thu_dau_mot_map_product import run_release_stage


VIETNAMESE_PRODUCT_GLYPHS = (
    "ÀÁÃÈÉÌÍÒÓÕÙÚÝàáãèéìíòóõùúý"
    "ĂăÂâĐđÊêĨĩÔôƠơŨũƯư"
    + "".join(chr(codepoint) for codepoint in range(0x1EA0, 0x1EFA))
    + "\u0300\u0301\u0303\u0309\u0323"
)
TEST_FONT_CHARACTERS = (
    "".join(chr(codepoint) for codepoint in range(32, 127))
    + VIETNAMESE_PRODUCT_GLYPHS
    + "©–—•"
)
LEGACY_NAMES = (
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
CURRENT_NAMES = (
    "Thủ Dầu Một",
    "Phú Lợi",
    "Chánh Hiệp",
    "Bình Dương",
    "Phú An",
)
LEGACY_EDITION_METADATA = (
    "Bản 14 điểm tham chiếu tên phường cũ; đây là điểm tham chiếu, "
    "không phải ranh giới hành chính cũ."
)
APPROVAL = {
    "reviewer": "Radar BDS release review",
    "reviewed_at": "2026-07-29T03:00:00+07:00",
    "legacy_reference_points_checked": True,
    "current_labels_checked": True,
    "a0_layout_checked": True,
    "vietnamese_text_checked": True,
    "sources_and_license_checked": True,
}


def _build_test_font(path: Path, *, family: str) -> Path:
    codepoints = sorted({ord(character) for character in TEST_FONT_CHARACTERS})
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


def _write_pdf(
    path: Path,
    font_path: Path,
    *,
    page_size,
    text: str,
) -> None:
    font_name = f"ReleaseTest-{path.stem}"
    pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    canvas = Canvas(str(path), pagesize=page_size, pageCompression=0)
    canvas.setSubject(text)
    canvas.setFont(font_name, 28)
    canvas.drawString(72, page_size[1] - 96, text)
    canvas.save()


def _remove_embedded_fonts_and_add_fontfile2_decoy(path: Path) -> None:
    reader = PdfReader(path)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    for page in writer.pages:
        fonts = page["/Resources"].get("/Font", {})
        for font_reference in fonts.values():
            font = font_reference.get_object()
            descendants = font.get("/DescendantFonts", ())
            font_objects = [font, *(item.get_object() for item in descendants)]
            for font_object in font_objects:
                descriptor = font_object.get("/FontDescriptor")
                if descriptor is not None:
                    descriptor.get_object().pop(NameObject("/FontFile2"), None)
    writer.add_metadata({"/Subject": "/FontFile2 decoy only"})
    temporary = path.with_suffix(".without-font.pdf")
    with temporary.open("wb") as stream:
        writer.write(stream)
    temporary.replace(path)
    path.write_bytes(path.read_bytes() + b"\n% /FontFile2 decoy\n")
    assert b"/FontFile2" in path.read_bytes()


def _svg(*, legacy: bool) -> str:
    edition = (
        LEGACY_EDITION_METADATA
        if legacy
        else "5 địa giới phường hiện hành"
    )
    return f"""\
<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000"
 viewBox="0 0 1600 1000">
  <metadata id="edition-metadata">{edition}</metadata>
  <rect width="1600" height="1000" fill="#eef5ef"/>
  <text x="60" y="100">BẢN ĐỒ THỦ DẦU MỘT</text>
  <text x="60" y="160">{edition}</text>
  <text x="60" y="220">© OpenStreetMap contributors</text>
  <text x="60" y="280">https://www.openstreetmap.org/copyright</text>
</svg>
"""


def _placemark(name: str, geometry: str, index: int) -> str:
    return (
        f"<Placemark><name>{name}</name>{geometry.format(index=index)}"
        "</Placemark>"
    )


def _kml(*, legacy: bool) -> str:
    point = "<Point><coordinates>106.{index},10.{index},0</coordinates></Point>"
    polygon = (
        "<Polygon><outerBoundaryIs><LinearRing><coordinates>"
        "106.{index},10.{index},0 106.{index}1,10.{index},0 "
        "106.{index}1,10.{index}1,0 106.{index},10.{index},0"
        "</coordinates></LinearRing></outerBoundaryIs></Polygon>"
    )
    if legacy:
        primary_name = "legacy-reference-centers"
        primary = "".join(
            (
                f"<Placemark><name>{name}</name>"
                "<ExtendedData><Data name=\"boundary_claim\">"
                "<value>false</value></Data></ExtendedData>"
                f"{point.format(index=index)}</Placemark>"
            )
            for index, name in enumerate(LEGACY_NAMES, start=10)
        )
    else:
        primary_name = "boundaries"
        primary = "".join(
            _placemark(name, polygon, index)
            for index, name in enumerate(CURRENT_NAMES, start=10)
        )
    edition_metadata = (
        LEGACY_EDITION_METADATA
        if legacy
        else "5 địa giới phường hiện hành"
    )
    return f"""\
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <description>© OpenStreetMap contributors -
  https://www.openstreetmap.org/copyright - Wikidata CC0</description>
  <ExtendedData><Data name="edition_description">
  <value>{edition_metadata}</value></Data></ExtendedData>
  <Folder><name>{primary_name}</name>{primary}</Folder>
  <Folder><name>poi</name>{_placemark("Chợ Thủ Dầu Một", point, 42)}</Folder>
</Document></kml>
"""


@pytest.fixture
def candidate_dir(tmp_path: Path) -> Path:
    candidate = tmp_path / "candidate"
    fonts = candidate / "fonts"
    fonts.mkdir(parents=True)
    regular = _build_test_font(
        fonts / "BeVietnamPro-Regular.ttf",
        family="Be Vietnam Pro",
    )
    semibold = _build_test_font(
        fonts / "BeVietnamPro-SemiBold.ttf",
        family="Be Vietnam Pro SemiBold",
    )
    (fonts / "OFL.txt").write_text(
        "SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007\n"
        "Permission is hereby granted, free of charge, to any person obtaining "
        "a copy of the Font Software.\n",
        encoding="utf-8",
    )
    (candidate / "thu-dau-mot-truoc-2025.svg").write_text(
        _svg(legacy=True),
        encoding="utf-8",
    )
    (candidate / "thu-dau-mot-sau-2025.svg").write_text(
        _svg(legacy=False),
        encoding="utf-8",
    )
    (candidate / "thu-dau-mot-truoc-2025.kml").write_text(
        _kml(legacy=True),
        encoding="utf-8",
    )
    (candidate / "thu-dau-mot-sau-2025.kml").write_text(
        _kml(legacy=False),
        encoding="utf-8",
    )
    _write_pdf(
        candidate / "thu-dau-mot-truoc-2025-a0.pdf",
        regular,
        page_size=landscape(A0),
        text=(
            "BẢN ĐỒ THỦ DẦU MỘT - 14 điểm tham chiếu - "
            "không phải ranh giới hành chính cũ"
        ),
    )
    _write_pdf(
        candidate / "thu-dau-mot-sau-2025-a0.pdf",
        semibold,
        page_size=landscape(A0),
        text="BẢN ĐỒ THỦ DẦU MỘT - 5 địa giới phường hiện hành",
    )
    _write_pdf(
        candidate / "HUONG-DAN.pdf",
        regular,
        page_size=A4,
        text=(
            "HƯỚNG DẪN - © OpenStreetMap contributors - Wikidata CC0 - "
            "Be Vietnam Pro SIL Open Font License"
        ),
    )
    (candidate / "GIAY-PHEP.txt").write_text(
        "Radar BDS - Giấy phép sử dụng sản phẩm số\n"
        "Được in, chỉnh sửa và dùng cho dự án cá nhân hoặc doanh nghiệp.\n"
        "Không bán lại, chia sẻ công khai hoặc phân phối lại file gốc.\n"
        "Nguồn: © OpenStreetMap contributors\n"
        "https://www.openstreetmap.org/copyright\n"
        "Wikidata CC0: https://www.wikidata.org/wiki/Wikidata:Licensing\n"
        "Font: Be Vietnam Pro - SIL Open Font License, Version 1.1\n",
        encoding="utf-8",
    )
    sources = {
        "current_boundaries": {
            "license": "Open Data Commons Open Database License (ODbL) v1.0",
            "license_url": "https://www.openstreetmap.org/copyright",
            "url": "current.geojson",
            "sha256": "a" * 64,
            "byte_length": 100,
        },
        "legacy_ward_centers": {
            "license": "Creative Commons CC0 1.0 (Wikidata point data)",
            "license_url": "https://www.wikidata.org/wiki/Wikidata:Licensing",
            "url": "legacy.geojson",
            "sha256": "b" * 64,
            "byte_length": 100,
        },
        "osm_detail": {
            "license": "Open Data Commons Open Database License (ODbL) v1.0",
            "license_url": "https://www.openstreetmap.org/copyright",
            "url": "osm.json",
            "sha256": "c" * 64,
            "byte_length": 100,
        },
        "font": {
            "license": "SIL Open Font License, Version 1.1",
            "license_url": (
                "https://github.com/google/fonts/tree/main/ofl/bevietnampro"
            ),
            "url": "BeVietnamPro-Regular.ttf",
            "sha256": sha256(regular.read_bytes()).hexdigest(),
            "byte_length": regular.stat().st_size,
        },
        "font_semibold": {
            "license": "SIL Open Font License, Version 1.1",
            "license_url": (
                "https://github.com/google/fonts/tree/main/ofl/bevietnampro"
            ),
            "url": "BeVietnamPro-SemiBold.ttf",
            "sha256": sha256(semibold.read_bytes()).hexdigest(),
            "byte_length": semibold.stat().st_size,
        },
    }
    (tmp_path / "source-manifest.json").write_text(
        json.dumps(sources, ensure_ascii=False),
        encoding="utf-8",
    )
    return candidate


@pytest.fixture
def approval_file(candidate_dir: Path) -> Path:
    approval_path = candidate_dir.parent / "release-approval.json"
    approval_path.write_text(
        json.dumps(APPROVAL, ensure_ascii=False),
        encoding="utf-8",
    )
    return approval_path


def test_release_requires_all_files_and_manual_approval(candidate_dir: Path):
    validation = validate_candidate(candidate_dir)

    assert validation.ok, validation.errors
    assert set(validation.files) == {
        "GIAY-PHEP.txt",
        "HUONG-DAN.pdf",
        "fonts/BeVietnamPro-Regular.ttf",
        "fonts/BeVietnamPro-SemiBold.ttf",
        "fonts/OFL.txt",
        "thu-dau-mot-sau-2025-a0.pdf",
        "thu-dau-mot-sau-2025.kml",
        "thu-dau-mot-sau-2025.svg",
        "thu-dau-mot-truoc-2025-a0.pdf",
        "thu-dau-mot-truoc-2025.kml",
        "thu-dau-mot-truoc-2025.svg",
    }
    with pytest.raises(ReleaseBlocked, match="approval"):
        package_release(
            candidate_dir,
            candidate_dir / "missing-approval.json",
            candidate_dir / "bundle.zip",
        )


def test_manifest_hashes_every_distributed_file(
    candidate_dir: Path,
    approval_file: Path,
):
    bundle = package_release(
        candidate_dir,
        approval_file,
        candidate_dir / "bundle.zip",
    )

    with ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("MANIFEST.json"))
        names = set(archive.namelist()) - {"MANIFEST.json"}
        assert names == set(manifest["files"])
        assert manifest["product"] == "radarbds-thu-dau-mot-map"
        assert manifest["version"] == "1.0"
        for name, metadata in manifest["files"].items():
            payload = archive.read(name)
            assert sha256(payload).hexdigest() == metadata["sha256"]
            assert len(payload) == metadata["byte_length"]


def test_candidate_with_raster_svg_or_unlicensed_font_is_rejected(
    candidate_dir: Path,
):
    (candidate_dir / "thu-dau-mot-truoc-2025.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="x.png"/></svg>',
        encoding="utf-8",
    )
    _build_test_font(
        candidate_dir / "fonts" / "BeVietnamPro-Regular.ttf",
        family="Unlicensed Test Font",
    )

    validation = validate_candidate(candidate_dir)

    assert not validation.ok
    assert any("SVG" in error and "image" in error for error in validation.errors)
    assert any("font" in error.casefold() for error in validation.errors)


def test_legacy_svg_visible_disclaimer_cannot_replace_required_metadata(
    candidate_dir: Path,
):
    path = candidate_dir / "thu-dau-mot-truoc-2025.svg"
    root = ElementTree.parse(path).getroot()
    metadata = root.find("./{*}metadata[@id='edition-metadata']")
    assert metadata is not None
    root.remove(metadata)
    ElementTree.ElementTree(root).write(
        path,
        encoding="utf-8",
        xml_declaration=True,
    )

    validation = validate_candidate(candidate_dir)

    assert not validation.ok
    assert any(
        "SVG" in error and "edition metadata" in error
        for error in validation.errors
    )


def test_legacy_pdf_visible_disclaimer_cannot_replace_required_metadata(
    candidate_dir: Path,
):
    path = candidate_dir / "thu-dau-mot-truoc-2025-a0.pdf"
    reader = PdfReader(path)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.add_metadata({"/Subject": "Vector map product"})
    temporary = path.with_suffix(".without-edition-metadata.pdf")
    with temporary.open("wb") as stream:
        writer.write(stream)
    temporary.replace(path)

    validation = validate_candidate(candidate_dir)

    assert not validation.ok
    assert any(
        "PDF" in error and "edition metadata" in error
        for error in validation.errors
    )


def test_legacy_kml_visible_disclaimer_cannot_replace_required_metadata(
    candidate_dir: Path,
):
    path = candidate_dir / "thu-dau-mot-truoc-2025.kml"
    root = ElementTree.parse(path).getroot()
    document_data = root.find("./{*}Document/{*}ExtendedData")
    assert document_data is not None
    edition_data = document_data.find(
        "./{*}Data[@name='edition_description']"
    )
    assert edition_data is not None
    document_data.remove(edition_data)
    ElementTree.ElementTree(root).write(
        path,
        encoding="utf-8",
        xml_declaration=True,
    )

    validation = validate_candidate(candidate_dir)

    assert not validation.ok
    assert any(
        "KML" in error and "edition metadata" in error
        for error in validation.errors
    )


def test_pdf_fontfile2_text_decoy_does_not_count_as_embedded_font(
    candidate_dir: Path,
):
    _remove_embedded_fonts_and_add_fontfile2_decoy(
        candidate_dir / "thu-dau-mot-sau-2025-a0.pdf"
    )

    validation = validate_candidate(candidate_dir)

    assert not validation.ok
    assert any(
        "embedded TrueType" in error for error in validation.errors
    )


def test_portrait_a0_pdf_is_rejected_even_when_dimensions_match(
    candidate_dir: Path,
):
    _write_pdf(
        candidate_dir / "thu-dau-mot-sau-2025-a0.pdf",
        candidate_dir / "fonts/BeVietnamPro-SemiBold.ttf",
        page_size=A0,
        text="BẢN ĐỒ THỦ DẦU MỘT - 5 địa giới phường hiện hành",
    )

    validation = validate_candidate(candidate_dir)

    assert not validation.ok
    assert any(
        "landscape A0" in error for error in validation.errors
    )


def test_kml_contract_rejects_missing_poi_and_extra_legacy_boundary(
    candidate_dir: Path,
):
    legacy_path = candidate_dir / "thu-dau-mot-truoc-2025.kml"
    payload = legacy_path.read_text(encoding="utf-8")
    payload = payload.replace(
        "</Document>",
        (
            "<Folder><name>legacy-boundaries</name>"
            "<Placemark><Polygon/></Placemark></Folder></Document>"
        ),
    ).replace("<Folder><name>poi</name>", "<Folder><name>removed-poi</name>")
    legacy_path.write_text(payload, encoding="utf-8")

    validation = validate_candidate(candidate_dir)

    assert not validation.ok
    assert any("legacy" in error.casefold() and "polygon" in error.casefold()
               for error in validation.errors)
    assert any("POI" in error for error in validation.errors)


def test_current_kml_rejects_sixth_polygon_outside_boundary_folder(
    candidate_dir: Path,
):
    current_path = candidate_dir / "thu-dau-mot-sau-2025.kml"
    payload = current_path.read_text(encoding="utf-8")
    payload = payload.replace(
        "</Document>",
        (
            "<Folder><name>unrelated</name><Placemark><name>Extra</name>"
            "<Polygon><outerBoundaryIs><LinearRing><coordinates>"
            "106.1,10.1,0 106.2,10.1,0 106.2,10.2,0 106.1,10.1,0"
            "</coordinates></LinearRing></outerBoundaryIs></Polygon>"
            "</Placemark></Folder></Document>"
        ),
    )
    current_path.write_text(payload, encoding="utf-8")

    validation = validate_candidate(candidate_dir)

    assert not validation.ok
    assert any(
        "exactly 5" in error and "Polygon" in error
        for error in validation.errors
    )


def test_approval_requires_every_check_and_iso_timestamp(
    candidate_dir: Path,
    approval_file: Path,
):
    invalid = {**APPROVAL, "current_labels_checked": False}
    invalid["reviewed_at"] = "not-a-timestamp"
    approval_file.write_text(
        json.dumps(invalid, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ReleaseBlocked, match="approval"):
        package_release(
            candidate_dir,
            approval_file,
            candidate_dir / "bundle.zip",
        )


def test_previews_are_watermarked_webp_and_leave_no_source_intermediates(
    candidate_dir: Path,
    tmp_path: Path,
):
    before = tmp_path / "public" / "before.webp"
    after = tmp_path / "public" / "after.webp"

    outputs = generate_watermarked_previews(candidate_dir, before, after)

    assert outputs == (before, after)
    for output in outputs:
        assert output.read_bytes()[:4] == b"RIFF"
        with Image.open(output) as image:
            assert image.format == "WEBP"
            assert image.width >= 1200
            assert image.height >= 800
    assert not list(before.parent.glob("*.svg"))
    assert not list(before.parent.glob("*.png"))


def test_stage_release_candidate_uses_commercial_names_and_generated_documents(
    candidate_dir: Path,
    tmp_path: Path,
):
    rendered = tmp_path / "rendered"
    source_cache = tmp_path / "source-cache"
    rendered.mkdir()
    source_cache.mkdir()
    source_names = {
        "thu-dau-mot-truoc-2025-a0.pdf": "thu-dau-mot-legacy.pdf",
        "thu-dau-mot-sau-2025-a0.pdf": "thu-dau-mot-current.pdf",
        "thu-dau-mot-truoc-2025.svg": "thu-dau-mot-legacy.svg",
        "thu-dau-mot-sau-2025.svg": "thu-dau-mot-current.svg",
        "thu-dau-mot-truoc-2025.kml": "thu-dau-mot-legacy.kml",
        "thu-dau-mot-sau-2025.kml": "thu-dau-mot-current.kml",
    }
    for commercial_name, source_name in source_names.items():
        (rendered / source_name).write_bytes(
            (candidate_dir / commercial_name).read_bytes()
        )
    (source_cache / "font.ttf").write_bytes(
        (candidate_dir / "fonts/BeVietnamPro-Regular.ttf").read_bytes()
    )
    (source_cache / "font_semibold.ttf").write_bytes(
        (candidate_dir / "fonts/BeVietnamPro-SemiBold.ttf").read_bytes()
    )
    staged_candidate = tmp_path / "release-candidate"

    result = stage_release_candidate(
        rendered,
        source_cache,
        staged_candidate,
        (candidate_dir / "fonts/OFL.txt").read_text(encoding="utf-8"),
    )

    assert result == staged_candidate
    assert _relative_file_names(staged_candidate) == set(
        validate_candidate(candidate_dir).files
    )
    validation = validate_candidate(staged_candidate)
    assert validation.ok, validation.errors
    assert (
        staged_candidate / "GIAY-PHEP.txt"
    ).read_text(encoding="utf-8").startswith("RADAR BDS")


def test_build_release_stage_writes_previews_and_v1_bundle(
    candidate_dir: Path,
    approval_file: Path,
    tmp_path: Path,
):
    _prepare_raw_release_inputs(candidate_dir, tmp_path)
    before = tmp_path / "public" / "before.webp"
    after = tmp_path / "public" / "after.webp"
    output_zip = (
        tmp_path
        / "releases"
        / "radarbds-thu-dau-mot-map-v1.0.zip"
    )

    result = run_release_stage(
        tmp_path,
        stage="all",
        approval_path=approval_file,
        output_zip=output_zip,
        preview_paths=(before, after),
        ofl_text=(
            candidate_dir / "fonts/OFL.txt"
        ).read_text(encoding="utf-8"),
    )

    assert result == output_zip
    assert output_zip.is_file()
    assert before.is_file()
    assert after.is_file()
    assert validate_candidate(tmp_path / "candidate").ok


def test_build_release_stage_is_byte_deterministic_for_same_inputs(
    candidate_dir: Path,
    approval_file: Path,
    tmp_path: Path,
):
    _prepare_raw_release_inputs(candidate_dir, tmp_path)
    preview_paths = (
        tmp_path / "public" / "before.webp",
        tmp_path / "public" / "after.webp",
    )
    ofl_text = (
        candidate_dir / "fonts/OFL.txt"
    ).read_text(encoding="utf-8")

    first = run_release_stage(
        tmp_path,
        stage="all",
        approval_path=approval_file,
        output_zip=tmp_path / "releases" / "first.zip",
        preview_paths=preview_paths,
        ofl_text=ofl_text,
    )
    second = run_release_stage(
        tmp_path,
        stage="all",
        approval_path=approval_file,
        output_zip=tmp_path / "releases" / "second.zip",
        preview_paths=preview_paths,
        ofl_text=ofl_text,
    )

    assert first.read_bytes() == second.read_bytes()
    assert sha256(first.read_bytes()).hexdigest() == sha256(
        second.read_bytes()
    ).hexdigest()


def _prepare_raw_release_inputs(candidate_dir: Path, work_dir: Path) -> None:
    rendered = work_dir / "rendered"
    source_cache = work_dir / "source-cache"
    rendered.mkdir(exist_ok=True)
    source_cache.mkdir(exist_ok=True)
    source_names = {
        "thu-dau-mot-truoc-2025-a0.pdf": "thu-dau-mot-legacy.pdf",
        "thu-dau-mot-sau-2025-a0.pdf": "thu-dau-mot-current.pdf",
        "thu-dau-mot-truoc-2025.svg": "thu-dau-mot-legacy.svg",
        "thu-dau-mot-sau-2025.svg": "thu-dau-mot-current.svg",
        "thu-dau-mot-truoc-2025.kml": "thu-dau-mot-legacy.kml",
        "thu-dau-mot-sau-2025.kml": "thu-dau-mot-current.kml",
    }
    for commercial_name, source_name in source_names.items():
        (rendered / source_name).write_bytes(
            (candidate_dir / commercial_name).read_bytes()
        )
    (source_cache / "font.ttf").write_bytes(
        (candidate_dir / "fonts/BeVietnamPro-Regular.ttf").read_bytes()
    )
    (source_cache / "font_semibold.ttf").write_bytes(
        (candidate_dir / "fonts/BeVietnamPro-SemiBold.ttf").read_bytes()
    )


def _relative_file_names(directory: Path) -> set[str]:
    return {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }

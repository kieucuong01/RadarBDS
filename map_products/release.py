"""Release gates and packaging for the Thu Dau Mot map product."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from fontTools.ttLib import TTFont as OpenTypeFont
from PIL import Image
import pdfplumber
from playwright.sync_api import sync_playwright
from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as ReportLabTTFont
from reportlab.pdfgen.canvas import Canvas


class ReleaseBlocked(RuntimeError):
    """Raised when a map release cannot pass a mandatory gate."""


@dataclass(frozen=True)
class ReleaseValidation:
    """Result of validating a fully staged commercial candidate."""

    ok: bool
    errors: tuple[str, ...] = ()
    files: dict[str, dict[str, int | str]] = field(default_factory=dict)


PRODUCT_NAME = "radarbds-thu-dau-mot-map"
PRODUCT_VERSION = "1.0"
EXPECTED_FILES = (
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
)
MAP_PDFS = (
    "thu-dau-mot-truoc-2025-a0.pdf",
    "thu-dau-mot-sau-2025-a0.pdf",
)
FONT_FILES = {
    "font": "fonts/BeVietnamPro-Regular.ttf",
    "font_semibold": "fonts/BeVietnamPro-SemiBold.ttf",
}
REQUIRED_SOURCE_KEYS = (
    "current_boundaries",
    "legacy_ward_centers",
    "osm_detail",
    "font",
    "font_semibold",
)
APPROVAL_CHECKS = (
    "legacy_reference_points_checked",
    "current_labels_checked",
    "a0_layout_checked",
    "vietnamese_text_checked",
    "sources_and_license_checked",
)
LEGACY_NAMES = {
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
}
CURRENT_NAMES = {
    "Thủ Dầu Một",
    "Phú Lợi",
    "Chánh Hiệp",
    "Bình Dương",
    "Phú An",
}
VIETNAMESE_PRODUCT_GLYPHS = (
    "ÀÁÃÈÉÌÍÒÓÕÙÚÝàáãèéìíòóõùúý"
    "ĂăÂâĐđÊêĨĩÔôƠơŨũƯư"
    + "".join(chr(codepoint) for codepoint in range(0x1EA0, 0x1EFA))
    + "\u0300\u0301\u0303\u0309\u0323"
)
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
RENDERED_TO_COMMERCIAL = {
    "thu-dau-mot-legacy.pdf": "thu-dau-mot-truoc-2025-a0.pdf",
    "thu-dau-mot-current.pdf": "thu-dau-mot-sau-2025-a0.pdf",
    "thu-dau-mot-legacy.svg": "thu-dau-mot-truoc-2025.svg",
    "thu-dau-mot-current.svg": "thu-dau-mot-sau-2025.svg",
    "thu-dau-mot-legacy.kml": "thu-dau-mot-truoc-2025.kml",
    "thu-dau-mot-current.kml": "thu-dau-mot-sau-2025.kml",
}


def _relative_files(candidate_dir: Path) -> set[str]:
    return {
        path.relative_to(candidate_dir).as_posix()
        for path in candidate_dir.rglob("*")
        if path.is_file()
    }


def _metadata(path: Path) -> dict[str, int | str]:
    payload = path.read_bytes()
    return {
        "sha256": sha256(payload).hexdigest(),
        "byte_length": len(payload),
    }


def _wrap_text(
    text: str,
    font_name: str,
    font_size: float,
    max_width: float,
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if (
            current
            and pdfmetrics.stringWidth(candidate, font_name, font_size)
            > max_width
        ):
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _draw_paragraph(
    canvas: Canvas,
    text: str,
    *,
    x: float,
    y: float,
    max_width: float,
    font_name: str,
    font_size: float,
    leading: float,
) -> float:
    for line in _wrap_text(text, font_name, font_size, max_width):
        canvas.setFont(font_name, font_size)
        canvas.drawString(x, y, line)
        y -= leading
    return y


def _write_guide_pdf(
    output_path: Path,
    regular_font: Path,
    semibold_font: Path,
) -> None:
    suffix = sha256(regular_font.read_bytes()).hexdigest()[:10]
    regular_name = f"BeVietnamProGuideRegular-{suffix}"
    semibold_name = f"BeVietnamProGuideSemibold-{suffix}"
    pdfmetrics.registerFont(
        ReportLabTTFont(regular_name, str(regular_font))
    )
    pdfmetrics.registerFont(
        ReportLabTTFont(semibold_name, str(semibold_font))
    )
    page_width, page_height = A4
    margin = 48
    canvas = Canvas(
        str(output_path),
        pagesize=A4,
        pageCompression=1,
        invariant=1,
    )
    canvas.setTitle("Hướng dẫn bộ bản đồ Thủ Dầu Một - Radar BDS")
    canvas.setAuthor("Radar BDS")
    canvas.setFillColor(HexColor("#12372a"))
    canvas.rect(0, page_height - 112, page_width, 112, fill=1, stroke=0)
    canvas.setFillColor(HexColor("#ffffff"))
    canvas.setFont(semibold_name, 20)
    canvas.drawString(margin, page_height - 60, "HƯỚNG DẪN SỬ DỤNG")
    canvas.setFont(regular_name, 11)
    canvas.drawString(
        margin,
        page_height - 84,
        "Bộ bản đồ Thủ Dầu Một trước và sau sắp xếp 2025 - v1.0",
    )
    y = page_height - 146
    sections = (
        (
            "1. TỆP TRONG GÓI",
            (
                "Hai PDF khổ A0 để in; hai SVG vector có text và lớp để chỉnh "
                "sửa; hai KML để mở trong phần mềm GIS hoặc Google Earth; "
                "hai font Be Vietnam Pro và giấy phép OFL đi kèm."
            ),
        ),
        (
            "2. LƯU Ý VỀ HAI PHIÊN BẢN",
            (
                "Bản trước 2025 hiển thị đúng 14 tâm điểm tham chiếu có tên. "
                "Các điểm này không phải ranh giới hành chính cũ. Bản sau "
                "2025 hiển thị đúng 5 ranh phường hiện hành: Thủ Dầu Một, "
                "Phú Lợi, Chánh Hiệp, Bình Dương và Phú An."
            ),
        ),
        (
            "3. IN VÀ CHỈNH SỬA",
            (
                "PDF dùng khổ A0 ngang. Khi in, chọn Actual size hoặc 100% và "
                "không Fit to page nếu cần giữ đúng tỷ lệ. Cài hai font trong "
                "thư mục fonts trước khi mở SVG bằng Illustrator, CorelDRAW "
                "hoặc Inkscape để tránh phần mềm tự thay font."
            ),
        ),
        (
            "4. DỮ LIỆU KML",
            (
                "KML giữ các lớp ranh hoặc điểm tham chiếu, đường, thủy hệ, "
                "POI và khu phố. KML là dữ liệu địa lý, không mô phỏng bố cục "
                "trang in. Tọa độ khu phố và POI mang tính tham khảo."
            ),
        ),
        (
            "5. NGUỒN VÀ GIẤY PHÉP",
            (
                "Dữ liệu đường, thủy hệ và POI: © OpenStreetMap contributors "
                "- https://www.openstreetmap.org/copyright - ODbL 1.0. "
                "Tâm điểm phường cũ: Wikidata CC0 - "
                "https://www.wikidata.org/wiki/Wikidata:Licensing. Font: "
                "Be Vietnam Pro - SIL Open Font License, Version 1.1 - "
                "https://github.com/google/fonts/tree/main/ofl/bevietnampro."
            ),
        ),
        (
            "6. CẢNH BÁO",
            (
                "Sản phẩm không thay thế bản đồ địa chính, hồ sơ thửa đất, "
                "hồ sơ quy hoạch hoặc xác nhận của cơ quan có thẩm quyền. "
                "Vị trí khu phố chỉ mang tính tham khảo và không thể hiện "
                "ranh giới khu phố."
            ),
        ),
    )
    for heading, paragraph in sections:
        canvas.setFillColor(HexColor("#12372a"))
        canvas.setFont(semibold_name, 11)
        canvas.drawString(margin, y, heading)
        y -= 18
        canvas.setFillColor(HexColor("#26332f"))
        y = _draw_paragraph(
            canvas,
            paragraph,
            x=margin,
            y=y,
            max_width=page_width - 2 * margin,
            font_name=regular_name,
            font_size=9.5,
            leading=13.5,
        )
        y -= 12
    canvas.setStrokeColor(HexColor("#c7d6cf"))
    canvas.line(margin, 38, page_width - margin, 38)
    canvas.setFillColor(HexColor("#52635c"))
    canvas.setFont(regular_name, 8)
    canvas.drawString(margin, 24, "Radar BDS - radarbds.vn - Phiên bản 1.0")
    canvas.save()


def _license_text() -> str:
    return """\
RADAR BDS - GIẤY PHÉP SỬ DỤNG SẢN PHẨM SỐ
Phiên bản sản phẩm: radarbds-thu-dau-mot-map-v1.0

QUYỀN SỬ DỤNG
Người mua được in, chỉnh sửa và sử dụng các tệp trong dự án cá nhân hoặc doanh nghiệp.

GIỚI HẠN
Không bán lại, chia sẻ công khai hoặc phân phối lại file gốc, toàn bộ bundle hay phiên bản có thể trích xuất lại dữ liệu gốc.
Không tuyên bố Radar BDS, OpenStreetMap, Wikidata hoặc tác giả font xác nhận hay bảo trợ cho sản phẩm dẫn xuất.

NGUỒN VÀ GIẤY PHÉP DỮ LIỆU
© OpenStreetMap contributors
https://www.openstreetmap.org/copyright
Dữ liệu OpenStreetMap được cung cấp theo Open Data Commons Open Database License (ODbL) v1.0.

Tâm điểm tham chiếu phường cũ: Wikidata CC0
https://www.wikidata.org/wiki/Wikidata:Licensing

FONT
Be Vietnam Pro - SIL Open Font License, Version 1.1
https://github.com/google/fonts/tree/main/ofl/bevietnampro
Xem toàn văn giấy phép font tại fonts/OFL.txt.

CẢNH BÁO
Bản đồ không thay thế bản đồ địa chính, hồ sơ thửa đất, hồ sơ quy hoạch hoặc xác nhận của cơ quan có thẩm quyền.
14 vị trí phường legacy là tâm điểm tham chiếu, không phải ranh giới hành chính cũ.
Vị trí khu phố mang tính tham khảo và không thể hiện ranh giới khu phố.
"""


def stage_release_candidate(
    rendered_dir: Path,
    source_cache_dir: Path,
    candidate_dir: Path,
    ofl_text: str,
) -> Path:
    """Stage exact paid files under commercial names for strict validation."""

    rendered_dir = Path(rendered_dir)
    source_cache_dir = Path(source_cache_dir)
    candidate_dir = Path(candidate_dir)
    required_inputs = {
        **{
            source_name: rendered_dir / source_name
            for source_name in RENDERED_TO_COMMERCIAL
        },
        "font.ttf": source_cache_dir / "font.ttf",
        "font_semibold.ttf": source_cache_dir / "font_semibold.ttf",
    }
    missing = [
        name for name, path in required_inputs.items() if not path.is_file()
    ]
    if missing:
        raise ReleaseBlocked(
            "cannot stage release; missing inputs: " + ", ".join(sorted(missing))
        )
    if (
        "SIL OPEN FONT LICENSE Version 1.1" not in ofl_text
        or "Permission is hereby granted" not in ofl_text
    ):
        raise ReleaseBlocked("cannot stage release; OFL.txt is missing or invalid")
    candidate_dir.mkdir(parents=True, exist_ok=True)
    fonts_dir = candidate_dir / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    for source_name, commercial_name in RENDERED_TO_COMMERCIAL.items():
        shutil.copyfile(
            rendered_dir / source_name,
            candidate_dir / commercial_name,
        )
    regular_font = fonts_dir / "BeVietnamPro-Regular.ttf"
    semibold_font = fonts_dir / "BeVietnamPro-SemiBold.ttf"
    shutil.copyfile(source_cache_dir / "font.ttf", regular_font)
    shutil.copyfile(source_cache_dir / "font_semibold.ttf", semibold_font)
    (fonts_dir / "OFL.txt").write_text(ofl_text, encoding="utf-8")
    (candidate_dir / "GIAY-PHEP.txt").write_text(
        _license_text(),
        encoding="utf-8",
    )
    _write_guide_pdf(
        candidate_dir / "HUONG-DAN.pdf",
        regular_font,
        semibold_font,
    )
    return candidate_dir


def _load_source_manifest(
    candidate_dir: Path,
    errors: list[str],
) -> dict:
    path = candidate_dir.parent / "source-manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"source manifest is missing or invalid: {exc}")
        return {}
    if not isinstance(manifest, dict):
        errors.append("source manifest must be a JSON object")
        return {}
    for source_key in REQUIRED_SOURCE_KEYS:
        source = manifest.get(source_key)
        if not isinstance(source, dict):
            errors.append(f"source manifest is missing {source_key}")
            continue
        for field_name in ("license", "license_url", "url", "sha256"):
            if not isinstance(source.get(field_name), str) or not source[field_name]:
                errors.append(
                    f"source manifest {source_key}.{field_name} is empty"
                )
        if not isinstance(source.get("byte_length"), int) or (
            source["byte_length"] <= 0
        ):
            errors.append(
                f"source manifest {source_key}.byte_length is invalid"
            )
    return manifest


def _validate_fonts(
    candidate_dir: Path,
    source_manifest: dict,
    errors: list[str],
) -> None:
    required_codepoints = {ord(character) for character in VIETNAMESE_PRODUCT_GLYPHS}
    for source_key, relative_name in FONT_FILES.items():
        path = candidate_dir / relative_name
        if not path.is_file():
            continue
        try:
            with OpenTypeFont(path, lazy=False) as font:
                cmap = {
                    codepoint
                    for table in font["cmap"].tables
                    if table.isUnicode()
                    for codepoint in table.cmap
                }
                missing = required_codepoints - cmap
                family_names = {
                    record.toUnicode()
                    for record in font["name"].names
                    if record.nameID in {1, 4, 6}
                }
        except Exception as exc:
            errors.append(f"font {relative_name} cannot be opened: {exc}")
            continue
        if missing:
            errors.append(
                f"font {relative_name} lacks {len(missing)} Vietnamese glyphs"
            )
        if not any(
            "be vietnam pro" in name.casefold() for name in family_names
        ):
            errors.append(
                f"font {relative_name} is not licensed Be Vietnam Pro"
            )
        source = source_manifest.get(source_key)
        if isinstance(source, dict):
            metadata = _metadata(path)
            if source.get("sha256") != metadata["sha256"]:
                errors.append(
                    f"font {relative_name} checksum differs from source manifest"
                )
            if source.get("byte_length") != metadata["byte_length"]:
                errors.append(
                    f"font {relative_name} byte length differs from source manifest"
                )
    license_path = candidate_dir / "fonts/OFL.txt"
    if license_path.is_file():
        license_text = license_path.read_text(encoding="utf-8", errors="replace")
        if "SIL OPEN FONT LICENSE Version 1.1" not in license_text:
            errors.append("fonts/OFL.txt is not the SIL OFL 1.1 license")
        if "Permission is hereby granted" not in license_text:
            errors.append("fonts/OFL.txt is incomplete")


def _validate_svg(path: Path, *, legacy: bool, errors: list[str]) -> None:
    if not path.is_file():
        return
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as exc:
        errors.append(f"SVG {path.name} cannot be parsed: {exc}")
        return
    images = [
        node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "image"
    ]
    if images:
        errors.append(f"SVG {path.name} contains a raster image")
    if not any(
        node.tag.rsplit("}", 1)[-1] == "text" for node in root.iter()
    ):
        errors.append(f"SVG {path.name} has no editable text")
    rendered_text = " ".join(root.itertext())
    for required in (
        "OpenStreetMap contributors",
        "https://www.openstreetmap.org/copyright",
    ):
        if required not in rendered_text:
            errors.append(f"SVG {path.name} lacks attribution: {required}")
    if legacy:
        folded = rendered_text.casefold()
        if "điểm tham chiếu" not in folded or "không phải ranh giới" not in folded:
            errors.append(
                f"SVG {path.name} lacks the legacy reference disclaimer"
            )
        metadata = root.find("./{*}metadata[@id='edition-metadata']")
        metadata_text = metadata.text if metadata is not None else ""
        if not _has_legacy_override(metadata_text):
            errors.append(
                f"SVG {path.name} edition metadata lacks the legacy override"
            )


def _folder(root: ElementTree.Element, name: str):
    for node in root.findall(".//{*}Folder"):
        name_node = node.find("./{*}name")
        if name_node is not None and (name_node.text or "").strip() == name:
            return node
    return None


def _placemark_names(folder) -> set[str]:
    names = set()
    for placemark in folder.findall("./{*}Placemark"):
        name_node = placemark.find("./{*}name")
        if name_node is not None and name_node.text:
            names.add(name_node.text.strip())
    return names


def _has_legacy_override(value: str | None) -> bool:
    folded = (value or "").casefold()
    return (
        "14 điểm" in folded
        and "tham chiếu" in folded
        and "không phải ranh giới hành chính cũ" in folded
    )


def _validate_kml(path: Path, *, legacy: bool, errors: list[str]) -> None:
    if not path.is_file():
        return
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as exc:
        errors.append(f"KML {path.name} cannot be parsed: {exc}")
        return
    rendered_text = " ".join(root.itertext())
    for required in (
        "OpenStreetMap contributors",
        "https://www.openstreetmap.org/copyright",
    ):
        if required not in rendered_text:
            errors.append(f"KML {path.name} lacks attribution: {required}")
    poi = _folder(root, "poi")
    if poi is None or not poi.findall("./{*}Placemark/{*}Point"):
        errors.append(f"KML {path.name} does not retain POI points")
    if legacy:
        references = _folder(root, "legacy-reference-centers")
        if references is None:
            errors.append(f"KML {path.name} lacks legacy reference folder")
            return
        placemarks = references.findall("./{*}Placemark")
        points = references.findall("./{*}Placemark/{*}Point")
        polygons = root.findall(".//{*}Polygon")
        if len(placemarks) != 14 or len(points) != 14:
            errors.append(
                f"KML {path.name} must contain exactly 14 legacy Points"
            )
        if polygons:
            errors.append(f"KML {path.name} legacy edition contains Polygon")
        if _placemark_names(references) != LEGACY_NAMES:
            errors.append(f"KML {path.name} has incorrect legacy ward names")
        for placemark in placemarks:
            claims = [
                (node.findtext("./{*}value") or "").strip().casefold()
                for node in placemark.findall(
                    ".//{*}Data[@name='boundary_claim']"
                )
            ]
            if claims != ["false"]:
                errors.append(
                    f"KML {path.name} legacy Point lacks boundary_claim=false"
                )
                break
        if "Wikidata" not in rendered_text or "CC0" not in rendered_text:
            errors.append(f"KML {path.name} lacks Wikidata CC0 attribution")
        metadata = root.find(
            "./{*}Document/{*}ExtendedData/"
            "{*}Data[@name='edition_description']/{*}value"
        )
        if not _has_legacy_override(
            metadata.text if metadata is not None else ""
        ):
            errors.append(
                f"KML {path.name} edition metadata lacks the legacy override"
            )
    else:
        boundaries = _folder(root, "boundaries")
        if boundaries is None:
            errors.append(f"KML {path.name} lacks current boundary folder")
            return
        placemarks = boundaries.findall("./{*}Placemark")
        boundary_polygons = [
            polygon
            for placemark in placemarks
            for polygon in placemark.findall(".//{*}Polygon")
        ]
        all_polygons = root.findall(".//{*}Polygon")
        if (
            len(placemarks) != 5
            or len(boundary_polygons) != 5
            or len(all_polygons) != 5
            or {id(polygon) for polygon in boundary_polygons}
            != {id(polygon) for polygon in all_polygons}
        ):
            errors.append(
                f"KML {path.name} must contain exactly 5 Polygon elements "
                "inside the five current boundary placemarks"
            )
        if _placemark_names(boundaries) != CURRENT_NAMES:
            errors.append(f"KML {path.name} has incorrect current ward names")


def _validate_pdfs(candidate_dir: Path, errors: list[str]) -> None:
    for relative_name in (*MAP_PDFS, "HUONG-DAN.pdf"):
        path = candidate_dir / relative_name
        if not path.is_file():
            continue
        try:
            reader = PdfReader(path)
            pdf_subject = (
                reader.metadata.subject if reader.metadata is not None else ""
            )
            font_streams = []
            for page in reader.pages:
                fonts = page["/Resources"].get("/Font", {})
                for font_reference in fonts.values():
                    font = font_reference.get_object()
                    descendants = font.get("/DescendantFonts", ())
                    for font_object in (
                        font,
                        *(item.get_object() for item in descendants),
                    ):
                        descriptor = font_object.get("/FontDescriptor")
                        if descriptor is None:
                            continue
                        font_file = descriptor.get_object().get("/FontFile2")
                        if font_file is None:
                            continue
                        stream = font_file.get_object()
                        if hasattr(stream, "get_data") and stream.get_data():
                            font_streams.append(stream)
        except Exception as exc:
            errors.append(
                f"PDF {relative_name} object tree cannot be inspected: {exc}"
            )
            font_streams = []
            pdf_subject = ""
        if not font_streams:
            errors.append(f"PDF {relative_name} lacks embedded TrueType font")
        if (
            relative_name.startswith("thu-dau-mot-truoc")
            and not _has_legacy_override(pdf_subject)
        ):
            errors.append(
                f"PDF {relative_name} edition metadata lacks the legacy override"
            )
        try:
            with pdfplumber.open(path) as pdf:
                if not pdf.pages:
                    errors.append(f"PDF {relative_name} has no pages")
                    continue
                if any(page.images for page in pdf.pages):
                    errors.append(f"PDF {relative_name} contains raster images")
                extracted = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
                if not extracted.strip():
                    errors.append(f"PDF {relative_name} has no extractable text")
                if relative_name in MAP_PDFS:
                    if len(pdf.pages) != 1:
                        errors.append(
                            f"PDF {relative_name} must be a one-page A0 map"
                        )
                    page = pdf.pages[0]
                    width = float(page.width)
                    height = float(page.height)
                    if (
                        width <= height
                        or abs(width - 3370) > 3
                        or abs(height - 2384) > 3
                    ):
                        errors.append(
                            f"PDF {relative_name} is not landscape A0"
                        )
                    folded = extracted.casefold()
                    if "thủ dầu một" not in folded:
                        errors.append(
                            f"PDF {relative_name} lacks Vietnamese map title"
                        )
                    if relative_name.startswith("thu-dau-mot-truoc"):
                        if (
                            "điểm tham chiếu" not in folded
                            or "không phải ranh giới" not in folded
                        ):
                            errors.append(
                                f"PDF {relative_name} lacks legacy disclaimer"
                            )
        except Exception as exc:
            errors.append(f"PDF {relative_name} cannot be inspected: {exc}")


def _validate_license(candidate_dir: Path, errors: list[str]) -> None:
    path = candidate_dir / "GIAY-PHEP.txt"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    for required in (
        "Radar BDS",
        "Không bán lại",
        "chia sẻ công khai",
        "OpenStreetMap contributors",
        "https://www.openstreetmap.org/copyright",
        "Wikidata",
        "CC0",
        "Be Vietnam Pro",
        "SIL Open Font License, Version 1.1",
    ):
        if required not in text:
            errors.append(f"GIAY-PHEP.txt lacks required text: {required}")


def validate_candidate(candidate_dir: Path) -> ReleaseValidation:
    """Validate the exact distributable candidate without modifying it."""

    candidate_dir = Path(candidate_dir)
    errors: list[str] = []
    actual_files = _relative_files(candidate_dir) if candidate_dir.is_dir() else set()
    expected_files = set(EXPECTED_FILES)
    for missing in sorted(expected_files - actual_files):
        errors.append(f"candidate is missing required file: {missing}")
    for extra in sorted(actual_files - expected_files):
        errors.append(f"candidate contains unexpected file: {extra}")

    source_manifest = _load_source_manifest(candidate_dir, errors)
    _validate_fonts(candidate_dir, source_manifest, errors)
    _validate_svg(
        candidate_dir / "thu-dau-mot-truoc-2025.svg",
        legacy=True,
        errors=errors,
    )
    _validate_svg(
        candidate_dir / "thu-dau-mot-sau-2025.svg",
        legacy=False,
        errors=errors,
    )
    _validate_kml(
        candidate_dir / "thu-dau-mot-truoc-2025.kml",
        legacy=True,
        errors=errors,
    )
    _validate_kml(
        candidate_dir / "thu-dau-mot-sau-2025.kml",
        legacy=False,
        errors=errors,
    )
    _validate_pdfs(candidate_dir, errors)
    _validate_license(candidate_dir, errors)

    file_metadata = {
        relative_name: _metadata(candidate_dir / relative_name)
        for relative_name in EXPECTED_FILES
        if (candidate_dir / relative_name).is_file()
    }
    return ReleaseValidation(
        ok=not errors,
        errors=tuple(errors),
        files=file_metadata,
    )


def _load_approval(approval_path: Path) -> dict:
    try:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseBlocked(f"manual approval is missing or invalid: {exc}") from exc
    if not isinstance(approval, dict):
        raise ReleaseBlocked("manual approval must be a JSON object")
    reviewer = approval.get("reviewer")
    reviewed_at = approval.get("reviewed_at")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ReleaseBlocked("manual approval reviewer is required")
    if not isinstance(reviewed_at, str) or not reviewed_at.strip():
        raise ReleaseBlocked("manual approval timestamp is required")
    try:
        parsed_timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseBlocked("manual approval timestamp is not ISO-8601") from exc
    if parsed_timestamp.tzinfo is None:
        raise ReleaseBlocked("manual approval timestamp must include a timezone")
    failed_checks = [
        check_name
        for check_name in APPROVAL_CHECKS
        if approval.get(check_name) is not True
    ]
    if failed_checks:
        raise ReleaseBlocked(
            "manual approval checks are incomplete: " + ", ".join(failed_checks)
        )
    return approval


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def package_release(
    candidate_dir: Path,
    approval_path: Path,
    output_zip: Path,
) -> Path:
    """Create a deterministic ZIP only after candidate and approval gates."""

    candidate_dir = Path(candidate_dir)
    approval = _load_approval(Path(approval_path))
    validation = validate_candidate(candidate_dir)
    if not validation.ok:
        raise ReleaseBlocked(
            "candidate validation failed: " + "; ".join(validation.errors)
        )
    source_manifest_path = candidate_dir.parent / "source-manifest.json"
    manifest = {
        "product": PRODUCT_NAME,
        "version": PRODUCT_VERSION,
        "reviewer": approval["reviewer"].strip(),
        "reviewed_at": approval["reviewed_at"],
        "source_manifest_sha256": sha256(
            source_manifest_path.read_bytes()
        ).hexdigest(),
        "files": validation.files,
    }
    manifest_payload = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    output_zip = Path(output_zip)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output_zip.parent,
        prefix=f".{output_zip.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with ZipFile(
            temporary_path,
            mode="w",
            compression=ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for relative_name in EXPECTED_FILES:
                archive.writestr(
                    _zip_info(relative_name),
                    (candidate_dir / relative_name).read_bytes(),
                )
            archive.writestr(_zip_info("MANIFEST.json"), manifest_payload)
        temporary_path.replace(output_zip)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return output_zip


def _watermarked_svg(source: Path, destination: Path, font_path: Path) -> tuple[int, int]:
    tree = ElementTree.parse(source)
    root = tree.getroot()
    view_box = root.attrib.get("viewBox", "0 0 1600 1000").split()
    if len(view_box) != 4:
        raise ReleaseBlocked(f"SVG {source.name} has an invalid viewBox")
    min_x, min_y, view_width, view_height = (float(value) for value in view_box)
    if view_width <= 0 or view_height <= 0:
        raise ReleaseBlocked(f"SVG {source.name} has an invalid viewBox")
    preview_width = 1600
    preview_height = round(preview_width * view_height / view_width)
    root.set("width", str(preview_width))
    root.set("height", str(preview_height))
    root.set("preserveAspectRatio", "xMidYMid meet")
    encoded_font = base64.b64encode(font_path.read_bytes()).decode("ascii")
    style = ElementTree.Element(f"{{{SVG_NAMESPACE}}}style")
    style.text = (
        "@font-face{font-family:'Preview Be Vietnam Pro';"
        "src:url(data:font/ttf;base64,"
        f"{encoded_font}) format('truetype');font-weight:700;}}"
    )
    root.insert(0, style)
    watermark = ElementTree.SubElement(
        root,
        f"{{{SVG_NAMESPACE}}}g",
        {
            "id": "preview-watermark",
            "aria-label": "RADAR BDS • BẢN XEM TRƯỚC",
            "pointer-events": "none",
        },
    )
    font_size = max(44.0, view_width / 34.0)
    for row in range(1, 7):
        for column in range(1, 5):
            x = min_x + view_width * column / 5
            y = min_y + view_height * row / 7
            text = ElementTree.SubElement(
                watermark,
                f"{{{SVG_NAMESPACE}}}text",
                {
                    "x": f"{x:.2f}",
                    "y": f"{y:.2f}",
                    "transform": f"rotate(-18 {x:.2f} {y:.2f})",
                    "text-anchor": "middle",
                    "font-family": "Preview Be Vietnam Pro",
                    "font-size": f"{font_size:.2f}",
                    "font-weight": "700",
                    "fill": "#8b1e2d",
                    "stroke": "#ffffff",
                    "stroke-width": f"{font_size / 28:.2f}",
                    "paint-order": "stroke",
                    "opacity": "0.42",
                },
            )
            text.text = "RADAR BDS • BẢN XEM TRƯỚC"
    ElementTree.register_namespace("", SVG_NAMESPACE)
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return preview_width, preview_height


def _write_preview_webp(
    page,
    source_svg: Path,
    font_path: Path,
    output_path: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="radarbds-map-preview-") as temp_name:
        temporary_dir = Path(temp_name)
        preview_svg = temporary_dir / "preview-only.svg"
        preview_png = temporary_dir / "preview-only.png"
        width, height = _watermarked_svg(source_svg, preview_svg, font_path)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(preview_svg.as_uri(), wait_until="load")
        page.evaluate("() => document.fonts.ready")
        page.locator("svg").screenshot(
            path=str(preview_png),
            animations="disabled",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(preview_png) as image:
            image.convert("RGB").save(
                output_path,
                format="WEBP",
                quality=84,
                method=6,
            )
        with Image.open(output_path) as preview:
            if preview.width < 1200 or preview.height < 800:
                raise ReleaseBlocked(
                    f"preview {output_path.name} is too small: "
                    f"{preview.width}x{preview.height}"
                )
        if output_path.stat().st_size < 5_000:
            raise ReleaseBlocked(
                f"preview {output_path.name} failed byte-size validation"
            )


def generate_watermarked_previews(
    candidate_dir: Path,
    before_path: Path,
    after_path: Path,
) -> tuple[Path, Path]:
    """Rasterize temporary watermarked SVG copies to public WebP previews."""

    candidate_dir = Path(candidate_dir)
    font_path = candidate_dir / "fonts/BeVietnamPro-SemiBold.ttf"
    if not font_path.is_file():
        raise ReleaseBlocked("preview font is missing")
    before_path = Path(before_path)
    after_path = Path(after_path)
    with sync_playwright() as playwright:
        executable_candidates: list[Path] = []
        configured_executable = os.environ.get(
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE"
        )
        if configured_executable:
            executable_candidates.append(Path(configured_executable))
        default_executable = Path(playwright.chromium.executable_path)
        executable_candidates.append(default_executable)
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            playwright_cache = Path(local_app_data) / "ms-playwright"
            executable_candidates.extend(
                sorted(
                    playwright_cache.glob(
                        "chromium-*/chrome-win64/chrome.exe"
                    ),
                    reverse=True,
                )
            )
            executable_candidates.extend(
                sorted(
                    playwright_cache.glob(
                        "chromium_headless_shell-*/"
                        "chrome-headless-shell-win64/"
                        "chrome-headless-shell.exe"
                    ),
                    reverse=True,
                )
            )
        executable_path = next(
            (
                candidate
                for candidate in executable_candidates
                if candidate.is_file()
            ),
            None,
        )
        launch_options = {
            "headless": True,
            "args": ["--allow-file-access-from-files"],
        }
        if executable_path is not None:
            launch_options["executable_path"] = str(executable_path)
        browser = playwright.chromium.launch(
            **launch_options,
        )
        try:
            page = browser.new_page()
            _write_preview_webp(
                page,
                candidate_dir / "thu-dau-mot-truoc-2025.svg",
                font_path,
                before_path,
            )
            _write_preview_webp(
                page,
                candidate_dir / "thu-dau-mot-sau-2025.svg",
                font_path,
                after_path,
            )
        finally:
            browser.close()
    return before_path, after_path

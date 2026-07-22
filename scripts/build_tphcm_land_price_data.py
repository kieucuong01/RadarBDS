from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

import pdfplumber


PRICE_RE = re.compile(r"^\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^\d+$")
HEADING_RE = re.compile(r"^BẢNG GIÁ ĐẤT\s+(.+)$")


def clean(value) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def slug_text(value: str) -> str:
    text = unicodedata.normalize("NFD", value.lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def is_price(value: str) -> bool:
    return bool(PRICE_RE.match(clean(value)))


def number_value(value: str):
    text = clean(value).replace(".", "").replace(",", ".")
    try:
        return int(float(text))
    except ValueError:
        return None


def groups_for_width(width: int) -> list[tuple[int, ...]] | None:
    if width == 7:
        return [(0,), (1,), (2,), (3,), (4,), (5,), (6,)]
    if width == 6:
        return [(0,), (1,), (2,), (3,), (4,), (5,)]
    if width >= 21:
        return [(0, 1, 2), (3, 4, 5), (6, 7, 8), (9, 10, 11), (12, 13, 14), (15, 16, 17), (18, 19, 20)]
    return None


def logical_row(row: list[str | None], groups: list[tuple[int, ...]]) -> list[str]:
    return [clean(" ".join(clean(row[i]) for i in group if i < len(row))) for group in groups]


def append_col(base: str, extra: str) -> str:
    if not extra:
        return base
    return f"{base} {extra}".strip()


def current_context(text: str, context: dict) -> dict:
    for line in (clean(line) for line in text.splitlines()):
        if line.startswith("Phụ lục"):
            context["appendix"] = line
        match = HEADING_RE.match(line)
        if match:
            context["area"] = match.group(1)
    return context


def extract_rows(pdf_path: Path) -> list[dict]:
    rows: list[dict] = []
    context = {"appendix": "", "area": ""}
    last_name_by_area: dict[str, str] = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            context = current_context(unicodedata.normalize("NFC", page.extract_text() or ""), context)
            for table in page.extract_tables() or []:
                groups = groups_for_width(max((len(row) for row in table), default=0))
                if not groups:
                    continue
                for raw in table:
                    cells = logical_row(raw, groups)
                    if not cells or not any(cells):
                        continue
                    if cells[0] in {"STT", "(1)"} or cells[1] == "TÊN ĐƯỜNG":
                        continue

                    prices = [c for c in cells[4:] if is_price(c)]
                    if not prices:
                        if rows and not cells[0] and context.get("area") == rows[-1]["area"]:
                            for key, value in zip(("street", "from", "to"), cells[1:4]):
                                rows[-1][key] = append_col(rows[-1][key], value)
                        continue

                    street = cells[1] or last_name_by_area.get(context.get("area", ""), "")
                    if not street:
                        continue
                    if cells[1]:
                        last_name_by_area[context.get("area", "")] = street

                    row = {
                        "area": context.get("area", ""),
                        "appendix": context.get("appendix", ""),
                        "stt": cells[0],
                        "street": street,
                        "from": cells[2],
                        "to": cells[3],
                        "residential": number_value(cells[4]) if len(cells) > 6 else None,
                        "commerce_service": number_value(cells[5] if len(cells) > 6 else cells[4]),
                        "production_business": number_value(cells[6] if len(cells) > 6 else cells[5]),
                        "page": page_index,
                    }
                    row["search"] = slug_text(" ".join(str(row[k] or "") for k in ("area", "street", "from", "to")))
                    rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out", type=Path, default=Path("static/data/tphcm_land_prices_2026.json"))
    args = parser.parse_args()

    rows = extract_rows(args.pdf)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "Nghị quyết 87/2025/NQ-HĐND TP.HCM, áp dụng từ 01/01/2026",
        "source_url": "https://static1.cafeland.vn/cafelandnew/hinh-anh/2026/05/14/191/87-2025-nq-bang-gia-dat-nam-2026-tphcm.pdf",
        "unit": "1.000 đồng/m²",
        "rows": rows,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()

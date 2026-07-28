import sys
from types import SimpleNamespace


sys.modules.setdefault("pdfplumber", SimpleNamespace())

from scripts import build_tphcm_land_price_data


def clean_rows(rows):
    cleaner = getattr(build_tphcm_land_price_data, "clean_rows", None)
    assert cleaner is not None, "land-price extraction needs a clean_rows quality gate"
    return cleaner(rows)


def _row(**overrides):
    row = {
        "area": "PHƯỜNG SÀI GÒN",
        "appendix": "Phụ lục II",
        "stt": "1",
        "street": "PHAN VĂN ĐẠT",
        "from": "TRỌN ĐƯỜNG",
        "to": "",
        "residential": 266400,
        "commerce_service": 186500,
        "production_business": 159800,
        "page": 20,
    }
    row.update(overrides)
    return row


def test_clean_rows_removes_repeated_from_to_header_at_page_break():
    rows = clean_rows([_row(**{"from": "TRỌN ĐƯỜNG TỪ", "to": "ĐẾN"})])

    assert rows[0]["from"] == "TRỌN ĐƯỜNG"
    assert rows[0]["to"] == ""


def test_clean_rows_deduplicates_identical_user_visible_records():
    rows = clean_rows(
        [
            _row(page=20, stt="1"),
            _row(page=21, stt="2"),
        ]
    )

    assert len(rows) == 1
    assert rows[0]["page"] == 20


def test_clean_rows_keeps_legitimate_endpoint_text_containing_tu_den():
    rows = clean_rows(
        [
            _row(
                **{
                    "from": "ĐƯỜNG VÕ NGUYÊN GIÁP (ĐOẠN TỪ ẸO ÔNG TỪ)",
                    "to": "CƠ SỞ DOANH TRẠI ĐẾN CHI ĐỘI KIỂM NGƯ",
                }
            )
        ]
    )

    assert rows[0]["from"] == "ĐƯỜNG VÕ NGUYÊN GIÁP (ĐOẠN TỪ ẸO ÔNG TỪ)"
    assert rows[0]["to"] == "CƠ SỞ DOANH TRẠI ĐẾN CHI ĐỘI KIỂM NGƯ"

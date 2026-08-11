"""Truthful public editorial context shared by Radar BDS marketing pages."""
from __future__ import annotations

from collections.abc import Mapping


EDITORIAL_OWNER_NAME = "Nhóm dữ liệu Radar BDS"
EDITORIAL_OWNER_URL = "/san-deal-bds"
DEFAULT_CAVEAT = (
    "Dữ liệu dùng để sàng lọc ban đầu, không thay thế kiểm tra thực địa, "
    "quy hoạch, pháp lý hoặc định giá chính thức."
)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def build_trust_context(page: Mapping[str, object], *, page_type: str) -> dict[str, str]:
    """Build visible claims only from page-owned timestamps and source fields."""
    article = _mapping(page.get("article"))
    report = _mapping(page.get("report"))
    snapshot = _mapping(page.get("live_snapshot"))
    values = {
        "owner_name": EDITORIAL_OWNER_NAME,
        "owner_url": EDITORIAL_OWNER_URL,
        "published_at": str(article.get("published_at") or report.get("published_at") or ""),
        "modified_at": str(
            article.get("modified_at")
            or report.get("data_as_of")
            or page.get("latest_modified_at")
            or page.get("updated_at")
            or ""
        ),
        "method_label": "Cách Radar BDS lọc và đối chiếu dữ liệu",
        "method_url": "/san-deal-bds",
        "caveat": DEFAULT_CAVEAT,
    }
    if page_type == "location":
        values["modified_at"] = str(snapshot.get("updated_iso") or "") if snapshot.get("available") else ""
        values["source_label"] = (
            "Tin rao công khai Radar BDS đang theo dõi."
            if snapshot.get("available")
            else "Dữ liệu trực tiếp tạm thời chưa khả dụng; trang giữ nội dung phương pháp thường trực."
        )
    elif page_type == "report":
        values["source_label"] = str(report.get("source_note") or "Dữ liệu Radar BDS đã sàng lọc.")
    else:
        values["source_label"] = str(page.get("source_note") or "Nội dung và dữ liệu biên tập bởi Radar BDS.")
    return {key: value for key, value in values.items() if value}

"""Truthful proof and bounded internal links for priority traffic pages."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from urllib.parse import urlsplit

from config.seo_locations import TDM_LIVE_WARDS
from config.traffic_priority import (
    TrafficPriorityPage,
    active_traffic_priority_pages,
    traffic_priority_by_path,
)


DEFAULT_LIMITATION = (
    "Dữ liệu dùng để sàng lọc ban đầu; cần kiểm tra thực địa, quy hoạch, "
    "pháp lý và giá giao dịch trước khi quyết định."
)

_SOURCE_LABELS = {
    "product_method": "Phương pháp sàng lọc và đối chiếu dữ liệu Radar BDS.",
    "location_registry": "Phạm vi khu vực công khai của Radar BDS.",
    "published_report_registry": "Các báo cáo Radar BDS đã chốt kỳ dữ liệu.",
    "valuation_method": "Phương pháp so sánh tin rao cùng khu vực và loại tài sản.",
    "live_ward_snapshot": "Tin rao công khai Radar BDS đang theo dõi tại đúng phường.",
    "planning_source_registry": "Nguồn bản đồ và văn bản công khai được dẫn trên trang.",
    "article_dataset": "Bộ dữ liệu và kỳ truy vấn được ghi trong bài Radar BDS.",
}

_PATH_LABELS = {
    "/": "Mở Radar BDS",
    "/binh-duong": "Xem thị trường Bình Dương",
    "/bao-cao": "Đọc báo cáo thị trường",
    "/dinh-gia-bds": "Mở công cụ định giá",
    "/quy-hoach-binh-duong/dia-gioi-36-phuong-xa-binh-duong-cu": (
        "Đối chiếu địa giới Bình Dương cũ"
    ),
    "/tin-tuc/nha-dat-thu-dau-mot-duoi-3-ty-phuong-nao-nhieu-lua-chon": (
        "So sánh lựa chọn dưới 3 tỷ"
    ),
    "/tin-tuc/cach-dinh-gia-nha-dat-binh-duong-bang-gia-rao-theo-phuong": (
        "Đọc cách định giá theo phường"
    ),
}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _ward_name(path: str) -> str:
    slug = path.removeprefix("/binh-duong/phuong-")
    return str(TDM_LIVE_WARDS.get(slug) or "")


def _path_label(path: str) -> str:
    if path in _PATH_LABELS:
        return _PATH_LABELS[path]
    ward = _ward_name(path)
    return f"Xem dữ liệu phường {ward}" if ward else path


def _actual_updated_at(page: Mapping[str, object]) -> str:
    snapshot = _mapping(page.get("live_snapshot"))
    article = _mapping(page.get("article"))
    report = _mapping(page.get("report"))
    return str(
        snapshot.get("updated_iso")
        or article.get("modified_at")
        or article.get("published_at")
        or report.get("data_as_of")
        or report.get("published_at")
        or page.get("updated_at")
        or page.get("latest_modified_at")
        or ""
    )


def _build_proof(
    entry: TrafficPriorityPage,
    page: Mapping[str, object],
) -> dict[str, str]:
    mode = entry.proof_mode
    snapshot = _mapping(page.get("live_snapshot"))
    if mode == "live_snapshot" and not snapshot.get("available"):
        mode = "method_only"

    proof = {
        "mode": mode,
        "scope_label": (
            f"{_ward_name(entry.path)}, Thủ Dầu Một"
            if entry.cluster == "ward"
            else "Bình Dương"
        ),
        "source_label": _SOURCE_LABELS[entry.proof_source],
        "method_label": "Đối chiếu đúng khu vực, loại tài sản và chất lượng nguồn.",
        "limitation": DEFAULT_LIMITATION,
    }
    updated_at = _actual_updated_at(page)
    if updated_at and not (
        entry.proof_mode == "live_snapshot" and mode == "method_only"
    ):
        proof["updated_at"] = updated_at
    return proof


def _related_links(
    entry: TrafficPriorityPage,
    *,
    limit: int,
) -> tuple[dict[str, str], ...]:
    candidates: list[tuple[str, str]] = []
    same_cluster = next(
        (
            page
            for page in active_traffic_priority_pages()
            if page.cluster == entry.cluster and page.path != entry.path
        ),
        None,
    )
    if same_cluster:
        candidates.append((same_cluster.path, _path_label(same_cluster.path)))
    candidates.extend(
        (
            ("/binh-duong", _path_label("/binh-duong")),
            ("/bao-cao", _path_label("/bao-cao")),
            ("/dinh-gia-bds", _path_label("/dinh-gia-bds")),
            (entry.dashboard_href, "Mở signal feed đã lọc"),
        )
    )

    selected: list[dict[str, str]] = []
    seen_paths = {entry.path}
    for href, label in candidates:
        canonical_path = urlsplit(href).path or "/"
        if canonical_path in seen_paths:
            continue
        seen_paths.add(canonical_path)
        selected.append({"href": href, "label": label})
        if len(selected) >= max(1, min(int(limit), 4)):
            break
    return tuple(selected)


def build_traffic_priority_context(
    path: str,
    *,
    page: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return render-safe priority context, or an empty mapping when inactive."""
    entry = traffic_priority_by_path(path)
    if not entry or not entry.active:
        return {}
    return {
        "entry": asdict(entry),
        "proof": _build_proof(entry, page or {}),
        "related_links": _related_links(entry, limit=4),
    }

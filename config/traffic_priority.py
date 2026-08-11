"""The bounded public-page registry used by Radar BDS traffic work.

Canonical page registries remain authoritative for page content.  This module
only declares which public pages receive P1-P3 visibility, proof, linking, and
distribution attention first.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from config.seo_locations import TDM_LIVE_WARDS


@dataclass(frozen=True, slots=True)
class TrafficPriorityPage:
    path: str
    cluster: str
    buyer_stage: str
    dashboard_href: str
    proof_mode: str
    proof_source: str
    distribution_angle: str
    active: bool = True


def _signals_href(**params: str) -> str:
    query = {"tab": "signals", **params}
    return "/?" + urlencode(query)


def _ward_pages() -> tuple[TrafficPriorityPage, ...]:
    return tuple(
        TrafficPriorityPage(
            path=f"/binh-duong/phuong-{slug}",
            cluster="ward",
            buyer_stage="compare",
            dashboard_href=_signals_href(ward=name),
            proof_mode="live_snapshot",
            proof_source="live_ward_snapshot",
            distribution_angle=(
                f"Đối chiếu mặt bằng tin rao {name}, Thủ Dầu Một trước khi mở signal feed."
            ),
        )
        for slug, name in TDM_LIVE_WARDS.items()
    )


TRAFFIC_PRIORITY_PAGES: tuple[TrafficPriorityPage, ...] = (
    TrafficPriorityPage(
        path="/",
        cluster="product",
        buyer_stage="decide",
        dashboard_href=_signals_href(),
        proof_mode="method_only",
        proof_source="product_method",
        distribution_angle="Lọc signal nhà đất Bình Dương từ dữ liệu tin rao đã chuẩn hóa.",
    ),
    TrafficPriorityPage(
        path="/binh-duong",
        cluster="market",
        buyer_stage="discover",
        dashboard_href=_signals_href(city="THỦ DẦU MỘT"),
        proof_mode="method_only",
        proof_source="location_registry",
        distribution_angle="Bắt đầu từ bản đồ khu vực rồi đi vào dữ liệu từng phường.",
    ),
    TrafficPriorityPage(
        path="/bao-cao",
        cluster="reports",
        buyer_stage="compare",
        dashboard_href=_signals_href(city="THỦ DẦU MỘT"),
        proof_mode="published_dataset",
        proof_source="published_report_registry",
        distribution_angle="Đọc báo cáo đã chốt kỳ dữ liệu trước khi kiểm tra signal hiện tại.",
    ),
    TrafficPriorityPage(
        path="/dinh-gia-bds",
        cluster="valuation",
        buyer_stage="decide",
        dashboard_href="/dinh-gia-bds",
        proof_mode="method_only",
        proof_source="valuation_method",
        distribution_angle="Ước tính khoảng giá tham khảo trước khi gọi môi giới hoặc đi xem.",
    ),
    *_ward_pages(),
    TrafficPriorityPage(
        path="/quy-hoach-binh-duong/dia-gioi-36-phuong-xa-binh-duong-cu",
        cluster="transition",
        buyer_stage="discover",
        dashboard_href=_signals_href(city="THỦ DẦU MỘT"),
        proof_mode="published_dataset",
        proof_source="planning_source_registry",
        distribution_angle="Đối chiếu tên địa bàn Bình Dương cũ với đơn vị hành chính hiện hành.",
    ),
    TrafficPriorityPage(
        path="/tin-tuc/nha-dat-thu-dau-mot-duoi-3-ty-phuong-nao-nhieu-lua-chon",
        cluster="budget",
        buyer_stage="decide",
        dashboard_href=(
            "/?tab=signals&price_max=3&utm_source=seo&utm_medium=article"
            "&utm_campaign=under3_tdm"
        ),
        proof_mode="published_dataset",
        proof_source="article_dataset",
        distribution_angle="So sánh lựa chọn nhà đất dưới 3 tỷ theo đúng phường và loại tài sản.",
    ),
    TrafficPriorityPage(
        path="/tin-tuc/cach-dinh-gia-nha-dat-binh-duong-bang-gia-rao-theo-phuong",
        cluster="valuation",
        buyer_stage="decide",
        dashboard_href=(
            "/dinh-gia-bds?utm_source=seo&utm_medium=article"
            "&utm_campaign=pricing_by_ward"
        ),
        proof_mode="published_dataset",
        proof_source="article_dataset",
        distribution_angle="Dùng giá rao cùng phường và cùng loại tài sản để tránh so sai mặt bằng.",
    ),
)


_PRIORITY_BY_PATH = {page.path: page for page in TRAFFIC_PRIORITY_PAGES}


def active_traffic_priority_pages() -> tuple[TrafficPriorityPage, ...]:
    """Return active entries in their deliberate editorial priority order."""
    return tuple(page for page in TRAFFIC_PRIORITY_PAGES if page.active)


def traffic_priority_by_path(path: str) -> TrafficPriorityPage | None:
    """Look up one canonical, query-free priority path."""
    return _PRIORITY_BY_PATH.get(str(path or ""))

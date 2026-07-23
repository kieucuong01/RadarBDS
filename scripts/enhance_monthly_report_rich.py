#!/usr/bin/env python3
"""Enhance generated Radar BDS monthly reports with the rich closed-month pattern.

Token-light workflow: the normal generator creates/updates the report entries, then this
script deterministically enriches the existing master + ward pages from PostgreSQL data:
trend analysis, under-value metrics, scatter charts, signal-style listing cards, and
filtered dashboard CTAs. No LLM drafting is required for the monthly batch.
"""
from __future__ import annotations

import argparse
import os
import pprint
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

PROJECT = Path("/opt/radar-bds/current")
sys.path.insert(0, str(PROJECT))
os.chdir(PROJECT)

# Importing the base generator also loads /etc/radar-bds/radar.env and shared ward constants.
from scripts.generate_monthly_report import (  # noqa: E402
    TDM_WARDS,
    WARDS_SLUG,
    TYPE_LABELS,
    month_label,
    query_ward_stats,
)
from db.connection import get_conn  # noqa: E402
from services.image_assets import resolve_image_url  # noqa: E402

NO_DIACRITICS = {
    "Tân An": "Tan An",
    "Hiệp An": "Hiep An",
    "Tương Bình Hiệp": "Tuong Binh Hiep",
    "Định Hòa": "Dinh Hoa",
    "Chánh Mỹ": "Chanh My",
    "Phú Mỹ": "Phu My",
    "Phú Cường": "Phu Cuong",
    "Phú Hòa": "Phu Hoa",
    "Phú Lợi": "Phu Loi",
    "Hiệp Thành": "Hiep Thanh",
    "Chánh Nghĩa": "Chanh Nghia",
    "Phú Tân": "Phu Tan",
    "Hòa Phú": "Hoa Phu",
}
COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"]


def load_seo_pages(config_path: Path) -> dict:
    ns: dict = {}
    code = compile(config_path.read_text(), str(config_path), "exec")
    exec(code, ns)
    return ns["SEO_PAGES"]


def esc(s: object) -> str:
    return str(s).replace("'", "''")


def fmt_num(n: int | float) -> str:
    return f"{int(n):,}".replace(",", ".")


def fmt_ty(v: object) -> str:
    if v is None:
        return "—"
    return f"{float(v):.2f}".rstrip("0").rstrip(".") + " tỷ"


def fmt_ppm2(v: object, *, missing: str = "Chưa đủ dữ liệu") -> str:
    if v is None:
        return missing
    return f"{float(v):.1f} tr/m²"


def fmt_area(v: object) -> str:
    if v is None:
        return "—"
    fv = float(v)
    return f"{fv:.0f} m²" if abs(fv - round(fv)) < 0.05 else f"{fv:.1f} m²"


def fmt_pct(v: float | None) -> str:
    if v is None:
        return "Chưa đủ mẫu"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f}%"


def parse_metric_number(value: object) -> int:
    text = str(value or "0").replace(".", "").replace(",", "")
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else 0


def parse_metric_float(value: object) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(m.group(0)) if m else None


def month_bounds(month: int, year: int) -> tuple[str, str]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def previous_month(month: int, year: int) -> tuple[int, int]:
    if month == 1:
        return 12, year - 1
    return month - 1, year


def last_six_months(month: int, year: int) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    m, y = month, year
    for _ in range(6):
        months.append((m, y))
        m, y = previous_month(m, y)
    return list(reversed(months))


def dashboard_href(ward: str | None = None, *, mos_min: int | str = 0, prop_type: str | None = None) -> str:
    params = {"tab": "signals", "city": "THỦ DẦU MỘT", "date_range": "all", "mos_min": str(mos_min)}
    if ward:
        params["ward"] = ward
    if prop_type:
        params["prop_type"] = prop_type
    return "/?" + urlencode(params)


def report_internal_links(ward: str, month: int, year: int) -> list[dict]:
    mm = f"{month:02d}"
    return [
        {"label": f"Dashboard {ward} — MOS ≥ 10%", "href": dashboard_href(ward, mos_min=10), "description": "Mở nhóm tin thấp hơn giá cơ sở từ 10% để kiểm tra chi tiết."},
        {"label": f"Dashboard {ward} — MOS ≥ 15%", "href": dashboard_href(ward, mos_min=15), "description": "Nhóm tín hiệu mạnh hơn, cần thẩm định pháp lý/vị trí trước."},
        {"label": f"Lọc đất nền {ward}", "href": dashboard_href(ward, prop_type="dat_nen"), "description": "So riêng đất nền theo giá/m² và MOS, tránh trộn với nhà đất."},
        {"label": f"Lọc nhà đất {ward}", "href": dashboard_href(ward, prop_type="nha_dat"), "description": "Xem riêng nhà đất vì giá/m² chịu ảnh hưởng chất lượng căn nhà."},
        {"label": "Báo cáo tổng Thủ Dầu Một", "href": f"/bao-cao/bds-binh-duong-thang-{mm}-{year}", "description": "So sánh phường này với toàn bộ 13 phường cùng kỳ."},
        {"label": "Công cụ định giá BĐS", "href": "/dinh-gia-bds", "description": "Tự kiểm tra một lô cụ thể bằng dữ liệu định giá Radar BDS."},
    ]


def ward_filter_sql(alias: str, ward: str) -> str:
    col = f"{alias}.ward" if alias else "ward"
    vals = [ward]
    if ward in NO_DIACRITICS:
        vals.append(NO_DIACRITICS[ward])
    return "(" + " OR ".join(f"{col} = '{esc(v)}'" for v in vals) + ")"


def pct_change(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / prev * 100


def short_title(text: object, max_len: int = 92) -> str:
    title = " ".join(str(text or "").split())
    return title if len(title) <= max_len else title[: max_len - 1].rstrip() + "…"


def fair_ranges(area_m2: object, fair_ppm2: object) -> tuple[str, str]:
    if not area_m2 or not fair_ppm2:
        return "—", "—"
    area = float(area_m2)
    low = float(fair_ppm2) * 0.94
    high = float(fair_ppm2) * 1.06
    return f"{fmt_ty(low * area / 1000)} ~ {fmt_ty(high * area / 1000)}", f"{fmt_ppm2(low)} ~ {fmt_ppm2(high)}"


def query_trends(ward: str, month: int, year: int) -> list[dict]:
    rows = []
    for m, y in last_six_months(month, year):
        start, end = month_bounds(m, y)
        stats = query_ward_stats(ward, start, end)
        dn = stats["by_type"].get("dat_nen", {})
        nd = stats["by_type"].get("nha_dat", {})
        rows.append({"month": f"{m:02d}/{y}", "stats": stats, "row": {"month": f"{m:02d}/{y}", "total": str(stats["total"]), "dat_nen_count": str(dn.get("count", 0)), "dat_nen_price": fmt_ppm2(dn.get("median_m2")), "nha_dat_count": str(nd.get("count", 0)), "nha_dat_price": fmt_ppm2(nd.get("median_m2")), "hot": str(stats["hot"]), "dropped": str(stats["dropped"]), "signals": str(stats["signals"])}})
    return rows


def query_valuation_records(ward: str, month: int, year: int) -> list[dict]:
    start, end = month_bounds(month, year)
    wf = ward_filter_sql("l", ward)
    query = f"""
WITH latest_v AS (
  SELECT DISTINCT ON (listing_id)
    listing_id, mos_pct, fair_ppm2, actual_ppm2, signal_score, trust_score, trust_tier, legal_status, computed_at
  FROM valuation_results
  ORDER BY listing_id, computed_at DESC NULLS LAST, id DESC
), img AS (
  SELECT DISTINCT ON (listing_id) listing_id, local_path, img_url
  FROM listing_images
  ORDER BY listing_id, img_order NULLS LAST, id
)
SELECT l.id, l.title, l.property_type, l.price_ty, l.price_per_m2, l.area_m2,
       l.has_so, l.is_hot, l.price_dropped, l.crawled_at, l.duplicate_of_id,
       v.mos_pct, v.fair_ppm2, v.signal_score, img.local_path, img.img_url
FROM listings l
JOIN latest_v v ON v.listing_id = l.id
LEFT JOIN img ON img.listing_id = l.id
WHERE {wf}
  AND l.source = 'facebook'
  AND l.review_hidden = 0
  AND l.is_blacklisted = 0
  AND COALESCE(l.is_outlier, 0) = 0
  AND l.crawled_at IS NOT NULL
  AND l.crawled_at::timestamp >= '{start}'
  AND l.crawled_at::timestamp < '{end}'
  AND l.price_per_m2 IS NOT NULL AND l.price_per_m2 > 0 AND l.price_per_m2 < 500
  AND l.price_ty IS NOT NULL AND l.price_ty > 0 AND l.price_ty < 50
  AND l.area_m2 IS NOT NULL AND l.area_m2 >= 40 AND l.area_m2 <= 1000
  AND v.mos_pct IS NOT NULL
ORDER BY CASE WHEN l.duplicate_of_id IS NULL THEN 0 ELSE 1 END, l.property_type, v.mos_pct DESC, v.signal_score DESC NULLS LAST
"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchall()
    records = []
    for row in rows:
        records.append({"id": int(row[0]), "title": row[1], "property_type": row[2], "price_ty": row[3], "price_per_m2": row[4], "area_m2": row[5], "has_so": row[6], "is_hot": bool(row[7]), "price_dropped": bool(row[8]), "duplicate_of_id": row[10], "mos_pct": float(row[11]), "fair_ppm2": row[12], "signal_score": row[13], "image": resolve_image_url(row[14], row[15], prefer_thumb=True)})
    return records


def featured_listings(ward: str, records: list[dict], period_label: str) -> list[dict]:
    candidates = [r for r in records if r["mos_pct"] >= 5 and r["property_type"] in {"dat_nen", "nha_dat"}]
    selected, seen = [], set()
    for pt in ["dat_nen", "nha_dat"]:
        for rec in [x for x in candidates if x["property_type"] == pt and x.get("duplicate_of_id") is None][:3]:
            selected.append(rec); seen.add(rec["id"])
    for rec in candidates:
        if len(selected) >= 6:
            break
        if rec["id"] not in seen:
            selected.append(rec); seen.add(rec["id"])
    items = []
    for rec in selected[:6]:
        fair_price_range, fair_ppm2_range = fair_ranges(rec.get("area_m2"), rec.get("fair_ppm2"))
        legal = "Có sổ" if int(rec.get("has_so") or 0) == 1 else "Pháp lý cần kiểm tra"
        items.append({"id": rec["id"], "href": f"/listing/{rec['id']}", "image": rec.get("image"), "type": TYPE_LABELS.get(rec["property_type"], rec["property_type"]), "title": short_title(rec.get("title")), "price": fmt_ty(rec.get("price_ty")), "price_per_m2": fmt_ppm2(rec.get("price_per_m2"), missing="—"), "area": fmt_area(rec.get("area_m2")), "mos": f"+{rec['mos_pct']:.1f}%", "fair_price_per_m2": fmt_ppm2(rec.get("fair_ppm2"), missing="—"), "score": str(int(rec.get("signal_score") or 0)), "legal": legal, "note": f"{legal}. MOS dương {rec['mos_pct']:.1f}%, nên xem như tin đáng kiểm tra chứ không phải khuyến nghị mua.", "is_hot": bool(rec.get("is_hot")), "price_dropped": bool(rec.get("price_dropped")), "fair_price_range": fair_price_range, "fair_ppm2_range": fair_ppm2_range, "time_label": period_label, "drop_label": "Chủ hạ giá" if rec.get("price_dropped") else ""})
    return items


def trend_chart(trends: list[dict]) -> dict:
    return {"id": "price-trend-6m-chart", "type": "bar", "title": "Biểu đồ Xu hướng Giá (6 tháng gần nhất)", "legend": True, "labels": [t["row"]["month"] for t in trends], "datasets": [{"label": "Đất nền (tr/m²)", "data": [t["stats"]["by_type"].get("dat_nen", {}).get("median_m2") for t in trends], "backgroundColor": "#3b82f6", "borderRadius": 3}, {"label": "Nhà đất (tr/m²)", "data": [t["stats"]["by_type"].get("nha_dat", {}).get("median_m2") for t in trends], "backgroundColor": "#10b981", "borderRadius": 3}], "options": {"scales": {"y": {"beginAtZero": False, "title": {"display": True, "text": "triệu đồng/m²"}}}}}


def scatter_chart(records: list[dict]) -> dict:
    datasets = []
    for pt, label, border in [("dat_nen", "Đất nền", "#2563eb"), ("nha_dat", "Nhà đất", "#10b981")]:
        points, bg, radius = [], [], []
        for rec in records:
            if rec["property_type"] != pt:
                continue
            mos = rec["mos_pct"]
            points.append({"x": round(float(rec["area_m2"]), 1), "y": round(float(rec["price_per_m2"]), 1)})
            bg.append("rgba(249,115,22,.95)" if mos >= 15 else "rgba(16,185,129,.85)" if mos >= 10 else "rgba(37,99,235,.55)" if pt == "dat_nen" else "rgba(16,185,129,.55)")
            radius.append(6 if mos >= 15 else 5 if mos >= 10 else 3.5)
        if points:
            datasets.append({"label": label, "data": points, "backgroundColor": bg, "borderColor": border, "pointRadius": radius, "pointHoverRadius": 7})
    return {"id": "under-value-scatter-chart", "type": "scatter", "title": "Biểu đồ phân tán diện tích và giá/m²", "wide": True, "legend": True, "datasets": datasets, "options": {"scales": {"x": {"title": {"display": True, "text": "Diện tích (m²)"}, "grid": {"color": "#e2e8f0"}}, "y": {"title": {"display": True, "text": "Giá chào (triệu đồng/m²)"}, "grid": {"color": "#e2e8f0"}, "beginAtZero": False}}, "plugins": {"legend": {"display": True, "position": "bottom"}}}}


def type_charts(stats: dict) -> list[dict]:
    labels = [TYPE_LABELS.get(k, k) for k in stats["by_type"].keys()]
    vals = [d["count"] for d in stats["by_type"].values()]
    prices = [d.get("median_m2") or 0 for d in stats["by_type"].values()]
    return [{"id": "type-dist-chart", "type": "doughnut", "title": "Phân bố loại hình", "legend": True, "labels": labels, "datasets": [{"data": vals, "backgroundColor": COLORS[: len(vals)]}]}, {"id": "type-price-chart", "type": "bar", "title": "Giá/m² theo loại hình (tr/m²)", "labels": labels, "datasets": [{"label": "Giá/m² (tr/m²)", "data": prices, "backgroundColor": "#3b82f6", "borderRadius": 3}], "legend": False}]


def analytical_copy(ward: str, trends: list[dict], records: list[dict]) -> tuple[list[str], list[str], list[str]]:
    cur = trends[-1]["stats"]
    prev = trends[-2]["stats"] if len(trends) >= 2 else {"total": 0, "by_type": {}}
    dn, nd = cur["by_type"].get("dat_nen", {}), cur["by_type"].get("nha_dat", {})
    pdn, pnd = prev.get("by_type", {}).get("dat_nen", {}), prev.get("by_type", {}).get("nha_dat", {})
    dn_pct = pct_change(dn.get("median_m2"), pdn.get("median_m2"))
    nd_pct = pct_change(nd.get("median_m2"), pnd.get("median_m2"))
    supply_pct = pct_change(cur["total"], prev.get("total"))
    trend = [f"Dữ liệu xu hướng tại {ward} dùng 6 tháng gần nhất; tháng nào thiếu dữ liệu sau lọc được giữ là “Chưa đủ dữ liệu”, không nội suy giá.", f"Trong tháng {trends[-1]['row']['month']}, đất nền {ward} đạt giá trung vị {fmt_ppm2(dn.get('median_m2'))}; nhà đất đạt {fmt_ppm2(nd.get('median_m2'))}. So với tháng trước, đất nền {('tăng ' + fmt_pct(dn_pct)) if dn_pct and dn_pct > 0 else ('giảm ' + fmt_pct(abs(dn_pct)) if dn_pct and dn_pct < 0 else 'đi ngang hoặc chưa đủ mẫu so sánh')}, còn nhà đất {('tăng ' + fmt_pct(nd_pct)) if nd_pct and nd_pct > 0 else ('giảm ' + fmt_pct(abs(nd_pct)) if nd_pct and nd_pct < 0 else 'đi ngang hoặc chưa đủ mẫu so sánh')}."]
    if supply_pct is not None and supply_pct >= 35:
        trend.append(f"Nguồn cung tăng {fmt_pct(supply_pct)} so với tháng trước ({prev['total']} → {cur['total']} tin). Khi nguồn cung tăng mà tỷ lệ tin giảm giá chỉ {cur['dropped']}/{cur['total']}, người mua có thêm lựa chọn để so sánh nhưng chưa đủ cơ sở gọi là bán tháo diện rộng.")
    elif supply_pct is not None and supply_pct <= -25:
        trend.append(f"Nguồn cung giảm {abs(supply_pct):.1f}% so với tháng trước ({prev['total']} → {cur['total']} tin). Ít hàng mới hơn làm các tin tốt khó xuất hiện hơn, nên cần theo dõi thêm thay vì kết luận từ một tháng.")
    else:
        trend.append(f"Nguồn cung biến động vừa phải ({prev.get('total', 0)} → {cur['total']} tin). Trong bối cảnh này, giá trung vị là mốc tham chiếu, còn quyết định từng tin vẫn cần lọc theo vị trí, pháp lý và MOS.")
    trend.append("Nhà đất thường dao động giá/m² mạnh hơn đất nền vì giá còn phản ánh chất lượng nhà, hẻm/đường, diện tích công nhận và mức hoàn thiện. Vì vậy nên so trong cùng loại hình thay vì trộn toàn bộ tin rao.")
    q = len(records); u10 = sum(1 for r in records if r["mos_pct"] >= 10); u15 = sum(1 for r in records if r["mos_pct"] >= 15)
    under = [f"Trong {q} tin đủ định giá tại {ward}, có {u10} tin MOS từ 10% trở lên và {u15} tin MOS từ 15% trở lên. Cơ hội dưới giá cơ sở vì vậy nằm trong một nhóm nhỏ cần kiểm tra sâu, không trải đều toàn phường."]
    for pt, label, med in [("dat_nen", "đất nền", dn.get("median_m2")), ("nha_dat", "nhà đất", nd.get("median_m2"))]:
        vals = [float(r["price_per_m2"]) for r in records if r["property_type"] == pt and r["mos_pct"] >= 10]
        if vals:
            under.append(f"Nhóm {label} có MOS cao đang nằm quanh vùng {min(vals):.1f}-{max(vals):.1f} tr/m², so với giá trung vị {label} {fmt_ppm2(med)}. Đây là nhóm đáng mở chi tiết trước nhưng vẫn phải kiểm tra vị trí, pháp lý, quy hoạch và thực địa.")
    under.append("Biểu đồ phân tán đặt diện tích ở trục ngang và giá/m² ở trục dọc. Các điểm nổi bật là danh sách ưu tiên để kiểm tra, không phải khuyến nghị mua ngay.")
    top_type = "nhà đất" if nd.get("signals", 0) >= dn.get("signals", 0) else "đất nền"
    type_body = [f"{ward} tháng này có {nd.get('count', 0)} tin nhà đất và {dn.get('count', 0)} tin đất nền. Nhóm {top_type} đang tạo nhiều tín hiệu hơn, nên nếu muốn săn cơ hội ngắn hạn nên lọc nhóm này trước rồi mới mở rộng sang loại hình còn lại.", f"Giá trung vị nhà đất {fmt_ppm2(nd.get('median_m2'))} so với đất nền {fmt_ppm2(dn.get('median_m2'))} phản ánh khác biệt tài sản trên đất. Cần so trong cùng loại hình để tránh kết luận sai.", "Khi mở dashboard, nên lọc từng loại hình riêng, sau đó mới xét MOS, pháp lý, hình ảnh và tuyến đường."]
    return trend, under, type_body


def price_trend_indicator_note(value: str, ward: str) -> str:
    pct = parse_metric_float(value)
    if pct is None or "chưa" in value.lower():
        return f"So với tháng trước, giá trung vị đất nền {ward} chưa đủ mẫu so sánh rõ."
    if value.strip().startswith("-"):
        return f"So với tháng trước, giá trung vị đất nền {ward} giảm {pct:.1f}%. Cần kiểm tra mức giảm đến từ nguồn cung rẻ hơn hay thay đổi chất lượng tin."
    if pct < 0.05:
        return f"So với tháng trước, giá trung vị đất nền {ward} gần như đi ngang; dùng mức này làm mốc tham chiếu trước khi lọc từng tin."
    return f"So với tháng trước, giá trung vị đất nền {ward} tăng {pct:.1f}%. Mức tăng cần đọc cùng nguồn cung để tránh kết luận chỉ từ một chỉ số giá."


def update_ward_page(page: dict, ward: str, month: int, year: int) -> dict:
    period_label = month_label(month, year); mm = f"{month:02d}"
    trends = query_trends(ward, month, year); cur = trends[-1]["stats"]; prev = trends[-2]["stats"] if len(trends) >= 2 else {"total": 0, "by_type": {}}
    records = query_valuation_records(ward, month, year)
    dn, nd = cur["by_type"].get("dat_nen", {}), cur["by_type"].get("nha_dat", {})
    pdn = prev.get("by_type", {}).get("dat_nen", {})
    dn_pct = pct_change(dn.get("median_m2"), pdn.get("median_m2")); cut = cur["dropped"] * 100 / cur["total"] if cur["total"] else 0; supply_pct = pct_change(cur["total"], prev.get("total"))
    trend_intro, under_body, type_analysis = analytical_copy(ward, trends, records)
    report = dict(page.get("report") or {})
    page.update({"scope_label": ward, "title": f"Giá đất {ward} tháng {mm}/{year}: {cur['total']} tin rao, đất nền {fmt_ppm2(dn.get('median_m2'))} — Radar BDS", "description": f"Báo cáo thị trường BĐS {ward} tháng {mm}/{year}: {cur['total']} tin rao, đất nền {fmt_ppm2(dn.get('median_m2'))}, nhà đất {fmt_ppm2(nd.get('median_m2'))}, {cur['signals']} tín hiệu đáng chú ý.", "hero_title": f"Giá đất {ward} tháng {mm}/{year}: đất nền {fmt_ppm2(dn.get('median_m2'))} từ {cur['total']} tin rao", "hero_text": f"Trong tháng {mm}/{year}, Radar BDS ghi nhận {cur['total']} tin rao Facebook tại {ward}. Giá trung vị đất nền đạt {fmt_ppm2(dn.get('median_m2'))}; nhà đất đạt {fmt_ppm2(nd.get('median_m2'))}. Nguồn cung và tín hiệu được tách theo loại hình để người mua lọc tin cụ thể hơn.", "final_cta": {"title": f"Lọc tin {ward} bằng dashboard Radar BDS", "body": f"Dùng báo cáo này làm bước sàng lọc ban đầu, sau đó mở dashboard để xem từng tin {ward} theo loại hình, giá/m², dấu hiệu nóng và tin giảm giá.", "button": "Mở dashboard", "button_href": dashboard_href(ward)}})
    value_pct = fmt_pct(dn_pct)
    report.update({"period": period_label, "source_note": f"Nguồn: tin rao Facebook tại {ward} trong tháng {mm}/{year}, đã lọc blacklist, hidden, outlier theo dữ liệu Radar BDS.", "metrics": [{"label": "Tin rao trong tháng", "value": fmt_num(cur["total"]), "note": f"tin Facebook tại {ward} sau lọc"}, {"label": "Giá trung vị đất nền", "value": fmt_ppm2(dn.get("median_m2")), "note": f"{dn.get('count', 0)} tin đất nền đủ dữ liệu giá/m²"}, {"label": "Giá trung vị nhà đất", "value": fmt_ppm2(nd.get("median_m2")), "note": f"{nd.get('count', 0)} tin nhà đất đủ dữ liệu giá/m²"}, {"label": "Dấu hiệu đáng chú ý", "value": str(cur["signals"]), "note": f"{cur['hot']} tin nóng + {cur['dropped']} tin giảm giá"}], "indicators": [{"label": "Xu hướng giá đất nền", "value": value_pct, "status": "Tăng" if dn_pct and dn_pct > 3 else "Giảm" if dn_pct and dn_pct < -3 else "Ổn định", "note": price_trend_indicator_note(value_pct, ward)}, {"label": "Tỷ lệ cắt máu", "value": f"{cut:.1f}%", "status": "Rất thấp" if cut < 1 else "Cần chú ý" if cut < 5 else "Cao", "note": f"{cur['dropped']}/{cur['total']} tin có dấu hiệu giảm giá; đọc như tín hiệu sàng lọc, không phải xác nhận bán tháo."}, {"label": "Bất thường nguồn cung", "value": fmt_pct(supply_pct), "status": "Rất cao" if supply_pct and supply_pct > 80 else "Tăng" if supply_pct and supply_pct > 20 else "Giảm" if supply_pct and supply_pct < -20 else "Ổn định", "note": f"Nguồn cung tháng trước → tháng này: {prev.get('total', 0)} → {cur['total']} tin."}], "trend_intro": trend_intro, "trend_rows": [t["row"] for t in trends], "area_rows": [{"area": TYPE_LABELS.get(pt, pt), "new_listings": f"{data['count']} tin", "median_price": fmt_ppm2(data.get("median_m2")), "drop_signal": f"{data.get('dropped', 0)} tin giảm giá", "radar_signal": f"{data.get('signals', 0)} dấu hiệu"} for pt, data in cur["by_type"].items()], "under_value": {"title": "Có bao nhiêu tin rao thấp hơn giá cơ sở?", "metrics": [{"label": "Tin đủ định giá", "value": str(len(records)), "note": f"tin {ward} tháng {mm} có đủ giá, diện tích và MOS để so sánh"}, {"label": "MOS ≥ 10%", "value": f"{sum(1 for r in records if r['mos_pct'] >= 10) * 100 / len(records):.1f}%" if records else "0%", "note": f"{sum(1 for r in records if r['mos_pct'] >= 10)}/{len(records)} tin thấp hơn giá cơ sở từ 10% trở lên"}, {"label": "MOS ≥ 15%", "value": f"{sum(1 for r in records if r['mos_pct'] >= 15) * 100 / len(records):.1f}%" if records else "0%", "note": f"{sum(1 for r in records if r['mos_pct'] >= 15)}/{len(records)} tin thuộc nhóm đáng kiểm tra sâu hơn"}], "body": under_body}, "type_analysis": type_analysis, "featured_listings": featured_listings(ward, records, period_label), "featured_more_href": dashboard_href(ward), "insights": [{"title": f"{ward}: nguồn cung tháng {mm} là {cur['total']} tin", "body": trend_intro[2]}, {"title": f"Nhóm đáng soi nghiêng về {'nhà đất' if nd.get('signals', 0) >= dn.get('signals', 0) else 'đất nền'}", "body": type_analysis[0]}, {"title": "MOS chỉ là bước sàng lọc ban đầu", "body": under_body[0]}]})
    methodology = list(report.get("methodology") or [])
    for item in ["MOS = mức chênh lệch giữa giá cơ sở Radar và giá chào; MOS dương nghĩa là giá chào thấp hơn giá cơ sở ước tính.", "Tin đáng kiểm tra được chọn từ nhóm đủ giá, diện tích, không blacklist/hidden/outlier, có valuation và link chi tiết /listing/id; ưu tiên tin không trùng, riêng phường ít dữ liệu có thể dùng tin đại diện cùng tài sản để đủ bối cảnh."]:
        if item not in methodology: methodology.append(item)
    report["methodology"] = methodology
    if report.get("under_value"):
        report["under_value"]["links"] = [
            {"label": f"Lọc tin {ward} MOS ≥ 10%", "href": dashboard_href(ward, mos_min=10), "description": "Mở dashboard đã lọc phường và ngưỡng MOS mà báo cáo đang nhắc tới."},
            {"label": f"Lọc tin {ward} MOS ≥ 15%", "href": dashboard_href(ward, mos_min=15), "description": "Nhóm tín hiệu mạnh hơn, dùng để ưu tiên thẩm định sâu."},
        ]
        for metric in report["under_value"].get("metrics", []):
            if metric.get("label") == "MOS ≥ 10%":
                metric["href"] = dashboard_href(ward, mos_min=10)
                metric["cta"] = "Xem tin MOS ≥ 10%"
            if metric.get("label") == "MOS ≥ 15%":
                metric["href"] = dashboard_href(ward, mos_min=15)
                metric["cta"] = "Xem tin MOS ≥ 15%"
    report["type_filter_links"] = [
        {"label": f"Lọc đất nền {ward}", "href": dashboard_href(ward, prop_type="dat_nen"), "description": "So riêng đất nền theo giá/m², diện tích và MOS."},
        {"label": f"Lọc nhà đất {ward}", "href": dashboard_href(ward, prop_type="nha_dat"), "description": "Xem riêng nhà đất vì giá/m² phụ thuộc chất lượng căn nhà."},
    ]
    report["internal_links"] = report_internal_links(ward, month, year)
    page["report"] = report
    page["charts"] = [trend_chart(trends), scatter_chart(records)] + type_charts(cur)
    return page


def update_master_page(page: dict, ward_pages: dict[str, dict], month: int, year: int) -> dict:
    rows = []
    for ward, wpage in ward_pages.items():
        report = wpage["report"]; metrics = report.get("metrics") or []
        total = parse_metric_number(metrics[0]["value"]) if metrics else 0; dn_price = parse_metric_float(metrics[1]["value"]) if len(metrics) > 1 else None; signals = parse_metric_number(metrics[3]["value"]) if len(metrics) > 3 else 0
        dropped = 0; note = metrics[3].get("note", "") if len(metrics) > 3 else ""; m = re.search(r"\+\s*(\d+)\s*tin giảm giá", note)
        if m: dropped = int(m.group(1))
        rows.append({"area": ward, "slug": WARDS_SLUG[ward], "new_listings": str(total), "median_price": f"{dn_price:.1f}" if dn_price is not None else "—", "drop_signal": str(dropped), "radar_signal": str(signals)})
    rows.sort(key=lambda r: int(r["new_listings"]), reverse=True)
    total = sum(int(r["new_listings"]) for r in rows); total_signals = sum(int(r["radar_signal"]) for r in rows)
    priced = [r for r in rows if r["median_price"] != "—"]; cheapest = min(priced, key=lambda r: float(r["median_price"])); expensive = max(priced, key=lambda r: float(r["median_price"])); most_signals = max(rows, key=lambda r: int(r["radar_signal"])); most_dropped = max(rows, key=lambda r: int(r["drop_signal"])); weighted = sum(float(r["median_price"]) * int(r["new_listings"]) for r in priced) / sum(int(r["new_listings"]) for r in priced); tdm_ref = round(weighted, 1); mm = f"{month:02d}"
    report = dict(page.get("report") or {})
    report.update({"metrics": [{"label": "Tin đang theo dõi", "value": fmt_num(total), "note": "facebook listings tại TDM"}, {"label": "Giá/m² tham chiếu", "value": f"{tdm_ref} tr/m²", "note": "đất nền — tổng hợp từ 13 phường"}, {"label": "Phường rẻ nhất", "value": cheapest["area"], "note": f"{cheapest['median_price']} tr/m²"}, {"label": "Tổng tín hiệu", "value": str(total_signals), "note": "hot + giảm giá toàn TDM"}], "area_rows": rows, "type_section_eyebrow": "So sánh theo phường", "type_section_title": "Nguồn cung và giá trung vị theo 13 phường Thủ Dầu Một", "type_analysis": [f"Biểu đồ nguồn cung cho thấy {rows[0]['area']} và {rows[1]['area']} là hai phường nhiều tin nhất trong tháng {mm}. Nguồn cung dày giúp dễ so sánh và thương lượng hơn, nhưng không tự động đồng nghĩa giá rẻ.", f"Biểu đồ giá cho thấy biên giữa phường rẻ nhất ({cheapest['area']} {cheapest['median_price']} tr/m²) và phường cao nhất ({expensive['area']} {expensive['median_price']} tr/m²) khá rộng. Vì vậy người mua nên chọn phường theo ngân sách trước, rồi mới lọc MOS từng tin.", f"Tổng {total_signals} tín hiệu toàn TDM là bản đồ ưu tiên để mở dashboard. Phường nhiều tín hiệu giúp có nhiều thứ để soi, còn quyết định từng tài sản vẫn cần kiểm tra pháp lý, quy hoạch, hình ảnh và vị trí thực địa."], "insights": [{"title": f"Phường rẻ nhất: {cheapest['area']} ({cheapest['median_price']} tr/m²)", "body": f"Trong 13 phường Thủ Dầu Một, {cheapest['area']} có giá đất nền thấp nhất theo dữ liệu tháng {mm} ({cheapest['median_price']} tr/m²), còn {expensive['area']} nằm ở vùng cao nhất ({expensive['median_price']} tr/m²). Đây là bước chọn vùng ngân sách, chưa phải kết luận từng tài sản đắt/rẻ."}, {"title": f"Nhiều tín hiệu nhất: {most_signals['area']}", "body": f"{most_signals['area']} dẫn đầu với {most_signals['radar_signal']} tín hiệu đáng chú ý. Phường nhiều tín hiệu nên được mở dashboard để lọc MOS và loại hình, vì không phải tín hiệu nào cũng đủ điều kiện pháp lý/vị trí để xuống tiền."}, {"title": f"Nhiều tin giảm giá: {most_dropped['area']}", "body": f"{most_dropped['area']} có {most_dropped['drop_signal']} tin giảm giá công khai trong tháng. Chỉ số này dùng để ưu tiên kiểm tra, không đồng nghĩa toàn phường đang bán tháo."}]})
    report["internal_links"] = [
        {"label": "Dashboard toàn Thủ Dầu Một", "href": dashboard_href(None), "description": "Mở feed tín hiệu toàn khu để lọc theo từng phường."},
        {"label": "Hub báo cáo BĐS Bình Dương", "href": "/bao-cao", "description": "Xem các báo cáo tháng khác và báo cáo từng phường."},
        {"label": "Nhà đất Bình Dương", "href": "/binh-duong", "description": "Hub SEO chính cho nhu cầu nhà đất Bình Dương."},
        {"label": "Bán đất Bình Dương", "href": "/ban-dat-binh-duong", "description": "Trang lọc riêng đất nền, đất thổ cư và giá/m²."},
        {"label": "Công cụ định giá BĐS", "href": "/dinh-gia-bds", "description": "Tự kiểm tra một lô cụ thể bằng dữ liệu Radar BDS."},
    ]
    page["report"] = report; page["description"] = f"Báo cáo thị trường BĐS Thủ Dầu Một tháng {mm}/{year}: {fmt_num(total)} tin rao, giá đất nền tham chiếu {tdm_ref} tr/m², {total_signals} tín hiệu từ 13 phường."; page["hero_text"] = f"Báo cáo tháng {mm}/{year} tập trung 13 phường Thủ Dầu Một với {fmt_num(total)} tin rao Facebook sau lọc. Dùng báo cáo như bản đồ chọn phường, sau đó mở dashboard để lọc từng tin theo loại hình, giá/m² và tín hiệu dưới giá cơ sở."; page["final_cta"] = {"title": "So sánh tất cả phường TDM bằng dashboard Radar BDS", "body": "Dùng báo cáo tổng quan làm bản đồ chọn phường, sau đó mở dashboard để lọc tin theo từng phường, loại hình, giá/m² và tín hiệu dưới giá cơ sở.", "button": "Mở dashboard", "button_href": dashboard_href(None)}; page["charts"] = [{"id": "ward-supply-chart", "type": "bar", "title": "Số tin rao theo phường", "labels": [r["area"] for r in rows], "datasets": [{"label": "Số tin rao", "data": [int(r["new_listings"]) for r in rows], "backgroundColor": "#3b82f6", "borderRadius": 3}], "legend": False}, {"id": "ward-price-chart", "type": "bar", "title": "Giá/m² trung vị theo phường (tr/m²)", "labels": [r["area"] for r in rows], "datasets": [{"label": "Giá/m² (tr/m²)", "data": [float(r["median_price"]) if r["median_price"] != "—" else 0 for r in rows], "backgroundColor": "#10b981", "borderRadius": 3}], "legend": False}]
    return page


def replace_entry_text(config_text: str, key: str, entry: dict) -> str:
    lines = config_text.splitlines(); start = next((i for i, line in enumerate(lines) if line.strip().startswith(f'"{key}":')), None)
    if start is None: raise KeyError(f"Missing SEO_PAGES entry {key}; run generate_monthly_report.py first")
    depth = 0; end = None
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if i > start and depth <= 0: end = i; break
    if end is None: raise RuntimeError(f"Could not find end of SEO_PAGES entry {key}")
    return "\n".join(lines[:start] + [f'    "{key}": {pprint.pformat(entry, width=140, sort_dicts=False)},'] + lines[end + 1:]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Enhance monthly Radar BDS reports with rich report pattern")
    parser.add_argument("--month", required=True, type=int); parser.add_argument("--year", required=True, type=int); parser.add_argument("--config", default=str(PROJECT / "config/seo_pages.py")); parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(); config_path = Path(args.config); pages = load_seo_pages(config_path); mm = f"{args.month:02d}"
    ward_pages = {}
    for ward in TDM_WARDS:
        key = f"bao-cao/{WARDS_SLUG[ward]}-thang-{mm}-{args.year}"
        if key not in pages: raise KeyError(f"Missing {key}; run scripts/generate_monthly_report.py --month {mm} --year {args.year} --all first")
        ward_pages[ward] = update_ward_page(dict(pages[key]), ward, args.month, args.year)
    master_key = f"bao-cao/bds-binh-duong-thang-{mm}-{args.year}"
    if master_key not in pages: raise KeyError(f"Missing {master_key}; run base generator first")
    master_page = update_master_page(dict(pages[master_key]), ward_pages, args.month, args.year)
    print(f"Rich monthly enhancement {mm}/{args.year}")
    print("- master: 2 charts, filtered dashboard CTA")
    for ward in TDM_WARDS:
        report = ward_pages[ward]["report"]
        print(f"- {ward}: {len(report.get('featured_listings') or [])} cards, {len(ward_pages[ward].get('charts') or [])} charts, {report['under_value']['metrics'][0]['value']} valued listings")
    if args.dry_run:
        print("DRY RUN — no files modified")
        return 0
    text = replace_entry_text(config_path.read_text(), master_key, master_page)
    for ward in TDM_WARDS:
        text = replace_entry_text(text, f"bao-cao/{WARDS_SLUG[ward]}-thang-{mm}-{args.year}", ward_pages[ward])
    compile(text, str(config_path), "exec"); config_path.write_text(text); print("Updated config/seo_pages.py with rich monthly report pattern")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

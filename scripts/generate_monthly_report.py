#!/usr/bin/env python3
"""
Radar BDS — Monthly Report Generator
======================================
Generate monthly market reports for each ward and inject into seo_pages.py.
Two report types:
  1. Master report: all-TDM comparison (/bao-cao/bds-binh-duong-thang-<MM>-<YYYY>)
  2. Ward reports: per-ward deep dive (/bao-cao/<ward_slug>-thang-<MM>-<YYYY>)

Usage:
  sudo -u radar /opt/radar-bds/.venv/bin/python scripts/generate_monthly_report.py \\
      --month 07 --year 2026 --ward "Phú Mỹ" [--dry-run]
  sudo -u radar /opt/radar-bds/.venv/bin/python scripts/generate_monthly_report.py \\
      --all --month 07 --year 2026
"""

import sys, os, re, argparse, ast, pprint
from datetime import date, timedelta

sys.path.insert(0, "/opt/radar-bds/current")
os.chdir("/opt/radar-bds/current")

# Load environment variables
env_file = "/etc/radar-bds/radar.env"
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                os.environ[k.strip()] = v

from db.connection import get_conn
from services.monthly_report_data import query_ward_stats as query_monthly_ward_stats

TDM_WARDS = [
    "Tân An", "Hiệp An", "Tương Bình Hiệp", "Định Hòa", "Chánh Mỹ",
    "Phú Mỹ", "Phú Cường", "Phú Hòa", "Phú Lợi", "Hiệp Thành",
    "Chánh Nghĩa", "Phú Tân", "Hòa Phú"
]

WARDS_SLUG = {
    "Tân An": "tan-an", "Hiệp An": "hiep-an", "Tương Bình Hiệp": "tuong-binh-hiep",
    "Định Hòa": "dinh-hoa", "Chánh Mỹ": "chanh-my", "Phú Mỹ": "phu-my",
    "Phú Cường": "phu-cuong", "Phú Hòa": "phu-hoa", "Phú Lợi": "phu-loi",
    "Hiệp Thành": "hiep-thanh", "Chánh Nghĩa": "chanh-nghia",
    "Phú Tân": "phu-tan", "Hòa Phú": "hoa-phu",
}

TYPE_LABELS = {
    "dat_nen": "Đất nền", "nha_dat": "Nhà đất",
    "nha_tro": "Nhà trọ", "kho_xuong": "Kho xưởng", "chung_cu": "Chung cư"
}


def esc(s):
    return s.replace("'", "''")


def query_ward_stats(ward, month_start, month_end):
    """Query trust-first report stats and close the connection internally."""
    with get_conn() as conn:
        return query_monthly_ward_stats(conn, ward, month_start, month_end)


def month_label(month, year):
    months = ["", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
    return f"Tháng {months[int(month)]}/{year}"


def month_end_date(month, year):
    month = int(month)
    year = int(year)
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def generate_insights(ward, stats, prev_stats, m_label_str):
    """Generate data-driven insights."""
    insights = []
    dn = stats["by_type"].get("dat_nen", {})
    dn_prev = prev_stats["by_type"].get("dat_nen", {}) if prev_stats else {}

    if dn.get("median_m2") and dn_prev.get("median_m2"):
        diff = dn["median_m2"] - dn_prev["median_m2"]
        pct = round(diff / dn_prev["median_m2"] * 100, 1) if dn_prev["median_m2"] else 0
        direction = "tăng" if diff > 0 else "giảm" if diff < 0 else "đi ngang"
        emoji = "🔺" if diff > 0 else "🔻" if diff < 0 else "➡️"
        insights.append({
            "title": f"Giá đất nền {direction} {abs(pct)}% so với tháng trước",
            "body": (
                f"Đất nền {ward} {m_label_str} có giá trung vị {dn['median_m2']} tr/m², "
                f"{direction} {abs(round(diff, 1))} tr/m² ({emoji} {abs(pct)}%) so với tháng trước "
                f"({dn_prev['median_m2']} tr/m²)."
            ),
        })
    else:
        insights.append({
            "title": f"Giá đất nền {ward}: {dn.get('median_m2', 'N/A')} tr/m²",
            "body": f"Đất nền {ward} {m_label_str} có giá trung vị {dn.get('median_m2', 'chưa đủ dữ liệu')} tr/m².",
        })

    if prev_stats:
        prev_total = prev_stats.get("total", 0)
        cur_total = stats.get("total", 0)
        if prev_total > 0:
            sd = cur_total - prev_total
            sp = round(sd / prev_total * 100, 1)
            if sd >= 0:
                insights.append({
                    "title": f"Nguồn cung tăng {sp}%",
                    "body": f"Nguồn cung {ward} tháng này tăng {sd} tin ({sp}%), thị trường đang sôi động.",
                })
            else:
                insights.append({
                    "title": f"Nguồn cung giảm {abs(sp)}%",
                    "body": f"Nguồn cung {ward} tháng này giảm {abs(sd)} tin ({abs(sp)}%), thị trường chậm lại hoặc tin đã bán.",
                })
        else:
            insights.append({
                "title": f"Nguồn cung {ward}: {stats['total']} tin",
                "body": f"Tháng này {ward} có {stats['total']} tin rao từ Facebook đang hoạt động.",
            })
    else:
        insights.append({
            "title": f"Nguồn cung {ward}: {stats['total']} tin",
            "body": f"Tháng này {ward} có {stats['total']} tin rao từ Facebook đang hoạt động.",
        })

    sig = stats.get("signals", 0)
    if sig > 0:
        insights.append({
            "title": f"{sig} tín hiệu đáng chú ý — cơ hội cho người mua",
            "body": (
                f"Có {sig} mẫu tại {ward} vượt quality gate và signal gate hiện hành. "
                "Dùng dashboard để kiểm tra MOS, pháp lý, vị trí và trạng thái còn hoạt động."
            ),
        })
    else:
        insights.append({
            "title": f"Thị trường {ward} tương đối ổn định",
            "body": f"Tháng này {ward} có ít tín hiệu đột biến. Theo dõi các tháng tiếp theo.",
        })

    return insights


def generate_ward_report(ward, month, year):
    """Generate a complete dict entry for a ward report."""
    m_str = str(month).zfill(2)
    prev_m = int(month) - 1
    prev_y = int(year)
    if prev_m == 0:
        prev_m = 12
        prev_y -= 1
    prev_m_str = str(prev_m).zfill(2)

    month_start = f"{year}-{m_str}-01"
    next_m = int(month) + 1
    next_y = int(year)
    if next_m > 12:
        next_m = 1
        next_y += 1
    month_end = f"{next_y}-{str(next_m).zfill(2)}-01"
    prev_start = f"{prev_y}-{prev_m_str}-01"
    next_prev_m = prev_m + 1
    next_prev_y = prev_y
    if next_prev_m > 12:
        next_prev_m = 1
        next_prev_y += 1
    prev_end = f"{next_prev_y}-{str(next_prev_m).zfill(2)}-01"

    stats = query_ward_stats(ward, month_start, month_end)
    prev_stats = query_ward_stats(ward, prev_start, prev_end) if prev_y >= 2026 else None

    slug = WARDS_SLUG.get(ward, ward.lower().replace(" ", "-"))
    m_label = month_label(month, year)

    titles = {"Tân An": "phường giá rẻ nhất Thủ Dầu Một",
              "Hiệp An": "nguồn cung số 1 Thủ Dầu Một",
              "Phú Mỹ": "phường ven sông Sài Gòn"}
    tagline = titles.get(ward, f"phường {ward}")

    area_rows = []
    for pt, pt_data in stats["by_type"].items():
        label = TYPE_LABELS.get(pt, pt)
        count = pt_data["count"]
        med_m2 = pt_data["median_m2"]
        med_m2_str = f"{med_m2} tr/m²" if med_m2 else "—"
        dropped = pt_data["signals"]
        area_rows.append({
            "area": label,
            "new_listings": f"{count} tin",
            "median_price": med_m2_str,
            "drop_signal": f"{dropped} tín hiệu" if dropped > 0 else "0 tín hiệu",
            "radar_signal": f"{dropped} tín hiệu" if dropped > 0 else "0 tín hiệu",
        })

    dn = stats["by_type"].get("dat_nen", {})

    metrics = [
        {"label": "Tin thu thập", "value": f"{stats['raw_total']:,}".replace(",", "."),
         "note": f"tin Facebook tại {ward}, gồm cả repost"},
        {"label": "Mẫu hợp lệ", "value": f"{stats['basis_count']:,}".replace(",", "."),
         "note": "canonical lot sau quality gate"},
        {"label": "Giá/m² trung vị", "value": f"{dn.get('median_m2', '—')} tr/m²" if dn.get('median_m2') else "—",
         "note": "đất nền (phân khúc chính)"},
        {"label": "Tín hiệu đáng chú ý", "value": str(stats['signals']),
         "note": "mẫu vượt quality gate và signal gate"},
    ]

    insights = generate_insights(ward, stats, prev_stats, m_label)

    methodology = [
        f"Dữ liệu từ tin rao Facebook tại {ward} trong {m_label}.",
        "Tin thu thập có thể gồm repost; mẫu hợp lệ chỉ giữ canonical lot và loại hidden, blacklist, duplicate, outlier, sold.",
        "Giá/m² trung vị dùng PERCENTILE_CONT(0.5) trên mẫu hợp lệ.",
        "Tín hiệu đáng chú ý dùng latest valuation cùng quality flags và actionable gate hiện hành.",
        "Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.",
    ]

    ch = []
    for pt_n, pt_d in list(stats["by_type"].items())[:3]:
        lbl = TYPE_LABELS.get(pt_n, pt_n)
        if pt_d.get("median_m2"):
            ch.append(f"{lbl}: {pt_d['median_m2']} tr/m² ({pt_d['count']} tin)")
    if stats["signals"] > 0:
        ch.append(f"{stats['signals']} tín hiệu đáng chú ý")

    entry = {
        "variant": "report",
        "scope_label": f"Thủ Dầu Một · {ward}",
        "path": f"/bao-cao/{slug}-thang-{m_str}-{year}",
        "title": f"Báo cáo thị trường {ward} Thủ Dầu Một tháng {m_str}/{year} — Radar BDS",
        "description": f"Báo cáo thị trường BĐS phường {ward}, Thủ Dầu Một tháng {m_str}/{year}: {dn.get('median_m2', '—')} tr/m² đất nền từ {stats['basis_count']} mẫu hợp lệ, {stats['signals']} tín hiệu.",
        "keywords": f"báo cáo thị trường {ward}, giá đất {ward}, nhà đất {ward}, Thủ Dầu Một, radar bds",
        "hero_badge": f"Báo cáo thị trường — {m_label}",
        "hero_title": f"Báo cáo thị trường phường {ward}, Thủ Dầu Một {m_label}",
        "hero_text": f"Báo cáo chi tiết thị trường BĐS phường {ward}, {tagline}. Radar thu thập {stats['raw_total']} tin và dùng {stats['basis_count']} mẫu canonical hợp lệ.",
        "hero_checks": ch,
        "primary_cta": "Mở dashboard để lọc signal",
        "secondary_cta": "Xem báo cáo tổng quan",
        "secondary_href": f"/bao-cao/bds-binh-duong-thang-{m_str}-{year}",
        "map_label": f"Report / {ward}",
        "hero_metric": {
            "label": "Phạm vi báo cáo",
            "value": "1 phường",
            "delta": f"{ward}",
            "note": f"chi tiết theo loại hình — {dn.get('median_m2', 'N/A')} tr/m² đất nền",
        },
        "property_card": {
            "status": "Market report",
            "title": f"{ward} — snapshot {m_label}",
            "price": f"Nguồn: {stats['raw_total']} tin thu thập, {stats['basis_count']} mẫu hợp lệ",
            "metric_a": "Giá/m² đất nền",
            "metric_a_value": f"{dn.get('median_m2', '—')} tr/m²" if dn.get('median_m2') else "—",
            "metric_b": "Tín hiệu",
            "metric_b_value": str(stats["signals"]),
        },
        "value_cards": [
            {"title": f"Chỉ dùng dữ liệu {ward} — không so chéo phường",
             "body": f"Báo cáo này chỉ tập trung phường {ward}. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một."},
            {"title": "Đọc theo loại hình để không so sai",
             "body": "Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại."},
            {"title": "Dùng số liệu để mở dashboard đúng chỗ",
             "body": "Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình."},
        ],
        "report": {
            "period": m_label,
            "published_at": date.today().isoformat(),
            "data_as_of": month_end_date(month, year).isoformat(),
            "raw_listing_count": stats["raw_total"],
            "basis_count": stats["basis_count"],
            "actionable_signal_count": stats["actionable_signal_count"],
            "data_contract_version": stats["data_contract_version"],
            "updated_label": f"Cập nhật {m_label}",
            "source_note": f"Nguồn: {stats['raw_total']} tin Facebook tại {ward}; thống kê giá dùng {stats['basis_count']} mẫu canonical hợp lệ.",
            "metrics": metrics,
            "area_rows": area_rows,
            "insights": insights,
            "methodology": methodology,
        },
        "charts": [
            {
                "id": "type-dist-chart",
                "type": "doughnut",
                "title": "Phân bố loại hình",
                "legend": True,
                "labels": [TYPE_LABELS.get(k, k) for k in stats["by_type"].keys()],
                "datasets": [{
                    "data": [d["count"] for d in stats["by_type"].values()],
                    "backgroundColor": ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"],
                }],
            },
            {
                "id": "type-price-chart",
                "type": "bar",
                "title": "Giá/m² theo loại hình (tr/m²)",
                "labels": [TYPE_LABELS.get(k, k) for k in stats["by_type"].keys()],
                "datasets": [{
                    "label": "Giá/m² (tr/m²)",
                    "data": [d["median_m2"] if d.get("median_m2") else 0 for d in stats["by_type"].values()],
                    "backgroundColor": "#3b82f6",
                    "borderRadius": 3,
                }],
                "legend": False,
            },
        ],
        "final_cta": {
            "title": f"Xem danh sách tin rao {ward} trên dashboard",
            "body": f"Mở dashboard Radar BDS để lọc tin rao {ward} theo loại hình, ngân sách và khu vực cụ thể.",
            "button": "Mở dashboard",
        },
    }

    return entry, stats, prev_stats


def generate_master_report(month, year):
    """Generate the master TDM comparison report."""
    m_str = str(month).zfill(2)
    month_start = f"{year}-{m_str}-01"
    next_m = int(month) + 1
    next_y = int(year)
    if next_m > 12:
        next_m = 1
        next_y += 1
    month_end = f"{next_y}-{str(next_m).zfill(2)}-01"
    m_label = month_label(month, year)

    ward_labels_vn = {
        "Tân An": "Tân An", "Hiệp An": "Hiệp An", "Tương Bình Hiệp": "TB Hiệp",
        "Định Hòa": "Định Hòa", "Chánh Mỹ": "Chánh Mỹ", "Phú Mỹ": "Phú Mỹ",
        "Phú Cường": "Phú Cường", "Phú Hòa": "Phú Hòa", "Phú Lợi": "Phú Lợi",
        "Hiệp Thành": "Hiệp Thành", "Chánh Nghĩa": "Chánh Nghĩa",
        "Phú Tân": "Phú Tân", "Hòa Phú": "Hòa Phú",
    }

    all_data = {}
    total_listings = 0
    total_raw_listings = 0
    total_signals = 0
    area_rows = []

    for ward in TDM_WARDS:
        stats = query_ward_stats(ward, month_start, month_end)
        all_data[ward] = stats
        total_listings += stats["total"]
        total_raw_listings += stats["raw_total"]
        total_signals += stats["signals"]
        dn = stats["by_type"].get("dat_nen", {})
        slug = WARDS_SLUG[ward]
        area_rows.append({
            "area": ward_labels_vn[ward],
            "slug": slug,
            "new_listings": str(stats["total"]),
            "median_price": f"{dn['median_m2']}" if dn.get("median_m2") else "—",
            "drop_signal": str(stats["dropped"]),
            "radar_signal": str(stats["signals"]),
        })

    area_rows.sort(key=lambda r: int(r["new_listings"]), reverse=True)

    priced = [(r["area"], float(r["median_price"])) for r in area_rows if r["median_price"] != "—"]
    priced.sort(key=lambda x: x[1])
    cheapest = priced[0] if priced else ("—", 0)
    most_expensive = priced[-1] if priced else ("—", 0)
    most_signals = max(area_rows, key=lambda r: int(r["radar_signal"]))
    most_dropped = max(area_rows, key=lambda r: int(r["drop_signal"]))

    tdm_median = 0
    if priced:
        weighted_sum = sum(p[1] * float(next(r["new_listings"] for r in area_rows if r["area"] == p[0])) for p in priced)
        weighted_count = sum(float(r["new_listings"]) for r in area_rows if r["median_price"] != "—")
        tdm_median = round(weighted_sum / weighted_count, 1) if weighted_count else 0

    # Build internal links to each ward child report. The master TDM page is the hub;
    # every ward page is a spoke for SEO crawl depth and user navigation.
    local_links = []
    for r_data in area_rows:
        local_links.append({
            "label": f"Báo cáo {r_data['area']} tháng {m_str}/{year}",
            "href": f'/bao-cao/{r_data["slug"]}-thang-{m_str}-{year}',
            "description": f'{r_data["new_listings"]} tin rao, giá đất nền {r_data["median_price"]} tr/m², {r_data["radar_signal"]} tín hiệu đáng chú ý.'
        })

    entry = {
        "variant": "report",
        "scope_label": "Thủ Dầu Một",
        "path": f"/bao-cao/bds-binh-duong-thang-{m_str}-{year}",
        "title": f"Báo cáo thị trường BĐS Thủ Dầu Một tháng {m_str}/{year} — Radar BDS",
        "description": f"Báo cáo thị trường BĐS Thủ Dầu Một {m_label}: {total_raw_listings} tin thu thập, {total_listings} mẫu hợp lệ, giá đất nền {tdm_median} tr/m².",
        "keywords": f"báo cáo thị trường BĐS Bình Dương, báo cáo Thủ Dầu Một, tháng {m_str} {year}, radar bds",
        "hero_badge": f"Báo cáo thị trường — {m_label}",
        "hero_title": f"Báo cáo thị trường BĐS Thủ Dầu Một {m_label}",
        "hero_text": f"Báo cáo {m_label} tập trung 13 phường Thủ Dầu Một. Radar thu thập {total_raw_listings} tin và dùng {total_listings} mẫu canonical hợp lệ.",
        "hero_checks": [f"13 phường Thủ Dầu Một", f"{total_listings:,}".replace(",", ".") + " mẫu hợp lệ",
                        f"Giá/m² trung vị {tdm_median} tr/m²"],
        "primary_cta": "Mở dashboard Radar BDS",
        "secondary_cta": "Xem hub Bình Dương",
        "secondary_href": "/binh-duong",
        "map_label": "Report / Bình Dương snapshot",
        "hero_metric": {"label": "Phạm vi báo cáo", "value": "13", "delta": "phường TDM",
                        "note": f"{total_listings} tin rao, {total_signals} tín hiệu"},
        "property_card": {"status": "Market report", "title": f"Bình Dương — snapshot {m_label}",
                          "price": f"Nguồn: {total_listings} tin rao + định giá + tín hiệu",
                          "metric_a": "Giá/m² trung vị", "metric_a_value": f"{tdm_median} tr/m²",
                          "metric_b": "Tín hiệu", "metric_b_value": str(total_signals)},
        "value_cards": [
            {"title": "Chỉ dùng phạm vi đủ dày dữ liệu",
             "body": f"Báo cáo tập trung 13 phường Thủ Dầu Một — nhóm có dữ liệu đủ dày để so giá."},
            {"title": "Đọc theo phường thay vì đọc cả thành phố",
             "body": "Chênh lệch giá/m² giữa các phường TDM khá lớn. Lọc theo ward trước khi kết luận."},
            {"title": "Dùng số liệu để mở dashboard đúng chỗ",
             "body": "Mở dashboard để lọc chi tiết theo từng phường và loại hình."},
        ],
        "report": {
            "period": m_label,
            "published_at": date.today().isoformat(),
            "data_as_of": month_end_date(month, year).isoformat(),
            "raw_listing_count": total_raw_listings,
            "basis_count": total_listings,
            "actionable_signal_count": total_signals,
            "data_contract_version": next(iter(all_data.values()))["data_contract_version"],
            "updated_label": f"Cập nhật {m_label}",
            "source_note": f"Nguồn: {total_raw_listings} tin Facebook tại 13 phường TDM; thống kê dùng {total_listings} mẫu canonical hợp lệ.",
            "metrics": [
                {"label": "Tin thu thập", "value": f"{total_raw_listings:,}".replace(",", "."),
                 "note": "gồm cả repost trong kỳ"},
                {"label": "Mẫu hợp lệ", "value": f"{total_listings:,}".replace(",", "."),
                 "note": "canonical lot sau quality gate"},
                {"label": "Giá/m² trung vị", "value": f"{tdm_median} tr/m²",
                 "note": "đất nền (phân khúc chính)"},
                {"label": "Tổng tín hiệu", "value": str(total_signals), "note": "mẫu actionable tại 13 phường"},
            ],
            "area_rows": area_rows,
            "insights": [
                {"title": f"Phường rẻ nhất: {cheapest[0]} ({cheapest[1]} tr/m²)",
                 "body": f"Trong 13 phường TDM, {cheapest[0]} giá thấp nhất {cheapest[1]} tr/m². {most_expensive[0]} đắt nhất {most_expensive[1]} tr/m²."},
                {"title": f"Nhiều tín hiệu nhất: {most_signals['area']}",
                 "body": f"{most_signals['area']} dẫn đầu với {most_signals['radar_signal']} tín hiệu."},
                {"title": f"Nhiều giảm giá: {most_dropped['area']}",
                 "body": f"{most_dropped['area']} có {most_dropped['drop_signal']} tin giảm giá."},
            ],
            "methodology": [
                f"Dữ liệu từ Facebook tại 13 phường TDM trong {m_label}.",
                "Tin thu thập có thể gồm repost; mẫu hợp lệ chỉ giữ canonical lot và loại hidden, blacklist, duplicate, outlier, sold.",
                "Giá/m² trung vị dùng PERCENTILE_CONT(0.5) trên mẫu hợp lệ.",
                "Tín hiệu đáng chú ý dùng latest valuation cùng quality flags và actionable gate hiện hành.",
                "Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.",
            ],
        },
        "local_links_title": "13 phường Thủ Dầu Một",
        "local_links": local_links,
        "charts": [
            {
                "id": "ward-supply-chart",
                "type": "bar",
                "title": "Số tin rao theo phường",
                "labels": [r["area"] for r in area_rows],
                "datasets": [{
                    "label": "Số tin rao",
                    "data": [int(r["new_listings"]) for r in area_rows],
                    "backgroundColor": "#3b82f6",
                    "borderRadius": 3,
                }],
                "legend": False,
            },
            {
                "id": "ward-price-chart",
                "type": "bar",
                "title": "Giá/m² trung vị theo phường (tr/m²)",
                "labels": [r["area"] for r in area_rows],
                "datasets": [{
                    "label": "Giá/m² (tr/m²)",
                    "data": [float(r["median_price"]) if r["median_price"] != "—" else 0 for r in area_rows],
                    "backgroundColor": "#10b981",
                    "borderRadius": 3,
                }],
                "legend": False,
            },
        ],
        "final_cta": {
            "title": "So sánh tất cả phường TDM — mở dashboard",
            "body": "Mở dashboard Radar BDS để lọc tin theo từng phường, loại hình và ngân sách.",
            "button": "Mở dashboard",
        },
    }

    return entry


def inject_report(config_path, entry):
    """Append report as a top-level SEO_PAGES assignment after the real SEO_PAGES dict.

    seo_pages.py has helper dicts/functions after SEO_PAGES. The old implementation
    searched from EOF for a top-level `}` and could accidentally inject reports into
    a later helper dict. AST gives the real SEO_PAGES assignment boundary.
    """
    slug = entry["path"].lstrip("/")

    with open(config_path) as f:
        content = f.read()

    ns = {}
    exec(compile(content, config_path, "exec"), ns)
    if slug in ns.get("SEO_PAGES", {}):
        print(f"  ⚠️  Entry '{slug}' already exists — skipping")
        return False

    tree = ast.parse(content)
    seo_node = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SEO_PAGES" for t in node.targets):
            seo_node = node
            break
    if seo_node is None or seo_node.end_lineno is None:
        print("  ❌ Could not locate SEO_PAGES assignment")
        return False

    entry_text = (
        f"\n# --- Generated monthly report: {slug} ---\n"
        f"SEO_PAGES[{slug!r}] = {pprint.pformat(entry, width=140, sort_dicts=False)}\n"
        f"# --- End generated monthly report: {slug} ---\n"
    )
    lines = content.split("\n")
    lines.insert(seo_node.end_lineno, entry_text)
    new_content = "\n".join(lines)

    try:
        compile(new_content, config_path, "exec")
    except SyntaxError as e:
        print(f"  ❌ Syntax error at line {e.lineno}: {e.msg}")
        return False

    with open(config_path, "w") as f:
        f.write(new_content)

    print(f"  ✅ Injected '{slug}'")
    return True

def main():
    parser = argparse.ArgumentParser(description="Generate monthly Radar BDS reports")
    parser.add_argument("--month", required=True, help="Month (01-12)")
    parser.add_argument("--year", default="2026", help="Year")
    parser.add_argument("--ward", help="Single ward name or slug")
    parser.add_argument("--all", action="store_true", help="All TDM wards")
    parser.add_argument("--master", action="store_true", help="Master TDM report only")
    parser.add_argument("--dry-run", action="store_true", help="Print without injecting")
    parser.add_argument("--allow-in-progress", action="store_true", help="Override safety guard and publish a month that has not fully closed yet")
    parser.add_argument("--config", default="/opt/radar-bds/current/config/seo_pages.py")
    args = parser.parse_args()

    if not args.dry_run and not args.allow_in_progress:
        closed_after = month_end_date(args.month, args.year)
        if date.today() <= closed_after:
            print(
                f"❌ Refusing to publish in-progress monthly reports for {args.month}/{args.year}. "
                f"Run after {closed_after.isoformat()} so the month is fully closed, or pass --allow-in-progress explicitly."
            )
            sys.exit(2)

    targets = []
    if args.ward:
        if args.ward in TDM_WARDS:
            targets = [args.ward]
        else:
            rev = {v: k for k, v in WARDS_SLUG.items()}
            if args.ward in rev:
                targets = [rev[args.ward]]
            else:
                print(f"❌ Unknown ward: {args.ward}")
                sys.exit(1)

    do_master = args.master or args.all or (not args.ward and not args.master)
    do_wards = bool(targets) or args.all

    if do_master:
        print(f"\n📊 MASTER report — month {args.month}/{args.year}")
        master_entry = generate_master_report(args.month, args.year)
        if args.dry_run:
            print(f"  DRY RUN — slug: {master_entry['path']}")
        else:
            inject_report(args.config, master_entry)

    if do_wards:
        ward_list = targets if targets else TDM_WARDS
        for ward in ward_list:
            print(f"\n🏘️  {ward} — month {args.month}/{args.year}")
            entry, stats, prev = generate_ward_report(ward, args.month, args.year)
            if args.dry_run:
                print(f"  DRY RUN — slug: {entry['path']}")
                print(f"  Stats: {stats['total']} listings, {stats['signals']} signals")
            else:
                inject_report(args.config, entry)

    if args.dry_run:
        print("\n✅ Dry run complete. No files modified.")
    else:
        print("\n✅ Done. Restart service to apply.")


if __name__ == "__main__":
    main()

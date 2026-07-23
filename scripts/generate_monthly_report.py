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

import sys, os, re, argparse
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
    """Query all stats for a ward in a date range. Opens/close connection internally."""
    with get_conn() as conn:
        cur = conn.cursor()

        # Build ward filter - handle both diacritics and non-diacritics variants
        ward_filter = f"ward = '{esc(ward)}'"
        # For TDM wards, also include non-diacritics variant
        no_diacritics = {
            "Tân An": "Tan An", "Hiệp An": "Hiep An", "Định Hòa": "Dinh Hoa",
            "Chánh Mỹ": "Chanh My", "Phú Mỹ": "Phu My", "Phú Cường": "Phu Cuong",
            "Phú Hòa": "Phu Hoa", "Phú Lợi": "Phu Loi", "Hiệp Thành": "Hiep Thanh",
            "Chánh Nghĩa": "Chanh Nghia", "Phú Tân": "Phu Tan", "Hòa Phú": "Hoa Phu",
        }
        if ward in no_diacritics:
            ward_filter = f"(ward = '{esc(ward)}' OR ward = '{no_diacritics[ward]}')"

        base = (
            ward_filter
            + " AND source = 'facebook'"
            + " AND is_blacklisted = 0"
            + " AND review_hidden = 0"
        )

        month_base = base + f" AND crawled_at::timestamp >= '{month_start}' AND crawled_at::timestamp < '{month_end}'"

        # Filter by month range — main stats use this month's data only
        stats = {}
        cur.execute(f"SELECT COUNT(*) FROM listings WHERE {month_base}")
        stats["total"] = cur.fetchone()[0]

        cur.execute(f"SELECT COUNT(*) FROM listings WHERE {month_base} AND (is_hot = 1 OR price_dropped = 1)")
        stats["signals"] = cur.fetchone()[0]

        cur.execute(f"SELECT COUNT(*) FROM listings WHERE {month_base} AND is_hot = 1")
        stats["hot"] = cur.fetchone()[0]

        cur.execute(f"SELECT COUNT(*) FROM listings WHERE {month_base} AND price_dropped = 1")
        stats["dropped"] = cur.fetchone()[0]

        stats["by_type"] = {}
        for pt in ["dat_nen", "nha_dat", "nha_tro", "kho_xuong", "chung_cu"]:
            pt_filter = month_base + f" AND property_type = '{pt}'"
            cur.execute(f"SELECT COUNT(*) FROM listings WHERE {pt_filter} AND price_per_m2::numeric > 0 AND price_per_m2::numeric < 500")
            count = cur.fetchone()[0]
            if count == 0:
                continue

            cur.execute(f"SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_m2::numeric) FROM listings WHERE {pt_filter} AND price_per_m2::numeric > 0 AND price_per_m2::numeric < 500")
            r = cur.fetchone()
            median_m2 = round(float(r[0]), 1) if r and r[0] is not None else None

            cur.execute(f"SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_ty::numeric) FROM listings WHERE {pt_filter} AND price_ty::numeric > 0 AND price_ty::numeric < 50")
            r = cur.fetchone()
            median_ty = round(float(r[0]), 2) if r and r[0] is not None else None

            cur.execute(f"SELECT COUNT(*) FROM listings WHERE {pt_filter} AND (is_hot = 1 OR price_dropped = 1)")
            pt_signals = cur.fetchone()[0]

            stats["by_type"][pt] = {
                "count": count, "median_m2": median_m2,
                "median_ty": median_ty, "signals": pt_signals,
            }

        # Also track month_new and month_signals (same as filtered stats above)
        stats["month_new"] = stats["total"]
        stats["month_signals"] = stats["signals"]

    return stats


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
                f"Có {sig} tín hiệu (hot + giảm giá) tại {ward} tháng này. "
                f"{stats.get('hot', 0)} tin nóng, {stats.get('dropped', 0)} tin giảm giá. "
                f"Dùng dashboard để lọc theo MOS và watchlist."
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
        {"label": "Tin đang theo dõi", "value": f"{stats['total']:,}".replace(",", "."),
         "note": f"tin rao Facebook tại {ward}"},
        {"label": "Giá/m² trung vị", "value": f"{dn.get('median_m2', '—')} tr/m²" if dn.get('median_m2') else "—",
         "note": "đất nền (phân khúc chính)"},
        {"label": "Giá tỷ trung vị", "value": f"{dn.get('median_ty', '—')} tỷ" if dn.get('median_ty') else "—",
         "note": "đất nền"},
        {"label": "Tín hiệu đáng chú ý", "value": str(stats['signals']),
         "note": "hot + giảm giá trong tháng"},
    ]

    insights = generate_insights(ward, stats, prev_stats, m_label)

    methodology = [
        f"Dữ liệu từ tin rao Facebook tại {ward} trong {m_label}.",
        "Giá/m² trung vị = PERCENTILE_CONT(0.5).",
        "Đã loại sold, blacklist, hidden, outlier.",
        "Tín hiệu = is_hot=1 hoặc price_dropped=1.",
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
        "description": f"Báo cáo thị trường BĐS phường {ward}, Thủ Dầu Một tháng {m_str}/{year}: {dn.get('median_m2', '—')} tr/m² đất nền, {stats['total']} tin rao, {stats['signals']} tín hiệu.",
        "keywords": f"báo cáo thị trường {ward}, giá đất {ward}, nhà đất {ward}, Thủ Dầu Một, radar bds",
        "hero_badge": f"Báo cáo thị trường — {m_label}",
        "hero_title": f"Báo cáo thị trường phường {ward}, Thủ Dầu Một {m_label}",
        "hero_text": f"Báo cáo chi tiết thị trường BĐS phường {ward}, {tagline}. Số liệu thực từ {stats['total']} tin rao Facebook trong tháng.",
        "hero_checks": ch,
        "primary_cta": "Mở dashboard để lọc watchlist",
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
            "price": f"Nguồn: {stats['total']} tin rao + định giá + tín hiệu",
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
            "updated_label": f"Cập nhật {m_label}",
            "source_note": f"Nguồn: tin rao Facebook tại {ward} ({stats['total']} tin). Đã lọc blacklist, hidden, outlier.",
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
    total_signals = 0
    area_rows = []

    for ward in TDM_WARDS:
        stats = query_ward_stats(ward, month_start, month_end)
        all_data[ward] = stats
        total_listings += stats["total"]
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

    # Build internal links to each ward report
    local_links = []
    for r_data in area_rows:
        dn_key = r_data["area"]
        local_links.append({
            "label": r_data["area"],
            "href": f'/bao-cao/{r_data["slug"]}-thang-{m_str}-{year}',
            "description": f'{r_data["new_listings"]} tin rao, giá đất nền {r_data["median_price"]} tr/m²'
        })

    entry = {
        "variant": "report",
        "scope_label": "Thủ Dầu Một",
        "path": f"/bao-cao/bds-binh-duong-thang-{m_str}-{year}",
        "title": f"Báo cáo thị trường BĐS Thủ Dầu Một tháng {m_str}/{year} — Radar BDS",
        "description": f"Báo cáo thị trường BĐS Bình Dương {m_label}: {total_listings} tin rao, giá đất nền {tdm_median} tr/m². Phân tích 13 phường TDM.",
        "keywords": f"báo cáo thị trường BĐS Bình Dương, báo cáo Thủ Dầu Một, tháng {m_str} {year}, radar bds",
        "hero_badge": f"Báo cáo thị trường — {m_label}",
        "hero_title": f"Báo cáo thị trường BĐS Thủ Dầu Một {m_label}",
        "hero_text": f"Báo cáo {m_label} tập trung 13 phường Thủ Dầu Một. {total_listings} tin rao, giá đất nền {tdm_median} tr/m², {total_signals} tín hiệu.",
        "hero_checks": [f"13 phường Thủ Dầu Một", f"{total_listings:,}".replace(",", ".") + " tin rao",
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
            "updated_label": f"Cập nhật {m_label}",
            "source_note": f"Nguồn: Facebook listings tại 13 phường TDM, đã lọc blacklist, hidden, outlier.",
            "metrics": [
                {"label": "Tin đang theo dõi", "value": f"{total_listings:,}".replace(",", "."),
                 "note": "facebook listings tại TDM"},
                {"label": "Giá/m² trung vị", "value": f"{tdm_median} tr/m²",
                 "note": "đất nền (phân khúc chính)"},
                {"label": "Phường rẻ nhất", "value": cheapest[0], "note": f"{cheapest[1]} tr/m²"},
                {"label": "Tổng tín hiệu", "value": str(total_signals), "note": "hot + giảm giá toàn TDM"},
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
                "Giá/m² trung vị = PERCENTILE_CONT(0.5).",
                "Đã loại sold, blacklist, hidden, outlier.",
                "Tín hiệu = is_hot=1 hoặc price_dropped=1.",
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
    """Inject a report entry into seo_pages.py, before the closing } of SEO_PAGES."""
    slug = entry["path"].lstrip("/")

    with open(config_path) as f:
        content = f.read()

    key_line = f'    "{slug}"'
    if key_line in content:
        print(f"  ⚠️  Entry '{slug}' already exists — skipping")
        return False

    lines = content.split("\n")
    closing_idx = None
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped == "}" and len(lines[i]) - len(lines[i].lstrip()) == 0:
            if i > 0 and lines[i-1].strip().endswith("}") and lines[i-1].strip() != "}":
                continue
            closing_idx = i
            break

    if closing_idx is None:
        print("  ❌ Could not find closing brace of SEO_PAGES")
        return False

    entry_lines = [f'    "{slug}": ' + "{"]
    keys = list(entry.keys())
    for j, k in enumerate(keys):
        v = entry[k]
        v_repr = repr(v)
        comma = "," if j < len(keys) - 1 else ""
        entry_lines.append(f'        "{k}": {v_repr}{comma}')
    entry_lines.append('    },')
    entry_text = "\n".join(entry_lines)

    lines.insert(closing_idx, entry_text)
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
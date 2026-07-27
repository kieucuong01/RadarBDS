#!/usr/bin/env python3
"""Emit token-light context for the Radar BDS daily SEO publisher.

This helper does not publish or modify files. It gives an AI agent/Codex enough
fresh production context to choose one daily SEO/AIO article idea without loading
raw DB dumps into the prompt.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

PROJECT = Path("/opt/radar-bds/current")
sys.path.insert(0, str(PROJECT))
os.chdir(PROJECT)

ENV_FILE = Path("/etc/radar-bds/radar.env")
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")

from config.seo_articles import SEO_ARTICLES  # noqa: E402
from db.connection import get_conn  # noqa: E402

DOMAIN = "https://radarbds.vn"
TDM_WARDS = [
    "Tân An",
    "Hiệp An",
    "Tương Bình Hiệp",
    "Định Hòa",
    "Chánh Mỹ",
    "Phú Mỹ",
    "Phú Cường",
    "Phú Hòa",
    "Phú Lợi",
    "Hiệp Thành",
    "Chánh Nghĩa",
    "Phú Tân",
    "Hòa Phú",
]
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
WARDS_SLUG = {
    "Tân An": "tan-an",
    "Hiệp An": "hiep-an",
    "Tương Bình Hiệp": "tuong-binh-hiep",
    "Định Hòa": "dinh-hoa",
    "Chánh Mỹ": "chanh-my",
    "Phú Mỹ": "phu-my",
    "Phú Cường": "phu-cuong",
    "Phú Hòa": "phu-hoa",
    "Phú Lợi": "phu-loi",
    "Hiệp Thành": "hiep-thanh",
    "Chánh Nghĩa": "chanh-nghia",
    "Phú Tân": "phu-tan",
    "Hòa Phú": "hoa-phu",
}


def esc(value: object) -> str:
    return str(value).replace("'", "''")


def ward_filter(ward: str) -> str:
    names = [ward]
    if ward in NO_DIACRITICS:
        names.append(NO_DIACRITICS[ward])
    return "(" + " OR ".join(f"ward = '{esc(name)}'" for name in names) + ")"


def fmt_num(value: object) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", ".")


def fmt_ppm2(value: object) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1f} tr/m²"


def article_inventory(limit: int) -> dict:
    items = []
    counts = {"tin_tuc": 0, "kien_thuc": 0, "bao_cao_articles": 0, "other": 0}
    for slug, article in SEO_ARTICLES.items():
        path = str(article.get("path") or "")
        if path.startswith("/tin-tuc/"):
            counts["tin_tuc"] += 1
        elif path.startswith("/kien-thuc/"):
            counts["kien_thuc"] += 1
        elif path.startswith("/bao-cao/"):
            counts["bao_cao_articles"] += 1
        else:
            counts["other"] += 1
        meta = article.get("article") or {}
        items.append(
            {
                "slug": slug,
                "path": path,
                "title": article.get("hero_title") or article.get("title"),
                "modified_at": meta.get("modified_at") or meta.get("published_at") or "",
            }
        )
    items.sort(key=lambda item: (item["modified_at"], item["path"]), reverse=True)
    return {"counts": counts, "latest": items[:limit]}


def query_ward_pulse(days: int, limit: int) -> list[dict]:
    start = dt.date.today() - dt.timedelta(days=days)
    rows: list[dict] = []
    with get_conn() as conn:
        cur = conn.cursor()
        for ward in TDM_WARDS:
            base = (
                f"{ward_filter(ward)} AND source = 'facebook' AND is_active = 1 "
                "AND is_blacklisted = 0 AND review_hidden = 0 AND crawled_at IS NOT NULL "
                f"AND crawled_at::timestamp >= '{start.isoformat()}'::timestamp"
            )
            cur.execute(f"SELECT COUNT(*) FROM listings WHERE {base}")
            total = int(cur.fetchone()[0] or 0)
            cur.execute(f"SELECT COUNT(*) FROM listings WHERE {base} AND (is_hot = 1 OR price_dropped = 1)")
            signals = int(cur.fetchone()[0] or 0)
            medians = {}
            for prop_type in ["dat_nen", "nha_dat"]:
                cur.execute(
                    f"""
                    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_m2::numeric)
                    FROM listings
                    WHERE {base}
                      AND property_type = '{prop_type}'
                      AND price_per_m2 IS NOT NULL
                      AND length(trim(price_per_m2::text)) > 0
                      AND price_per_m2::numeric > 0
                      AND price_per_m2::numeric < 500
                    """
                )
                value = cur.fetchone()[0]
                medians[prop_type] = round(float(value), 1) if value is not None else None
            query = urlencode({"tab": "signals", "ward": ward, "date_range": "all"})
            rows.append(
                {
                    "ward": ward,
                    "slug": WARDS_SLUG[ward],
                    "days": days,
                    "active_listings": total,
                    "signals": signals,
                    "dat_nen_median": medians["dat_nen"],
                    "nha_dat_median": medians["nha_dat"],
                    "dashboard_url": f"{DOMAIN}/?{query}",
                    "candidate_angle": f"Giá đất {ward} hiện khoảng bao nhiêu? Đọc riêng đất nền và nhà đất",
                }
            )
    rows.sort(key=lambda row: (row["signals"], row["active_listings"]), reverse=True)
    return rows[:limit]


def render_markdown(payload: dict) -> str:
    inv = payload["article_inventory"]
    lines = [
        f"# Radar BDS daily SEO context — {payload['date']}",
        "",
        "## Existing article inventory",
        f"- /tin-tuc articles: {inv['counts']['tin_tuc']}",
        f"- /kien-thuc legacy articles: {inv['counts']['kien_thuc']}",
        f"- /bao-cao article-style pages: {inv['counts']['bao_cao_articles']}",
        "",
        "### Latest article paths",
    ]
    for item in inv["latest"]:
        lines.append(f"- {item['modified_at'] or '—'} — {item['path']} — {item['title']}")
    lines.extend(["", f"## Top ward data pulse ({payload['pulse_days']} days)", ""])
    lines.append("| Ward | Tin đang theo dõi | Dấu hiệu | Đất nền | Nhà đất | Candidate angle |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for row in payload["ward_pulse"]:
        lines.append(
            "| {ward} | {active} | {signals} | {dn} | {nd} | {angle} |".format(
                ward=row["ward"],
                active=fmt_num(row["active_listings"]),
                signals=fmt_num(row["signals"]),
                dn=fmt_ppm2(row["dat_nen_median"]),
                nd=fmt_ppm2(row["nha_dat_median"]),
                angle=row["candidate_angle"],
            )
        )
    lines.extend(
        [
            "",
            "## Daily publish reminder",
            "- Ship 1 `/tin-tuc/<slug>` SEO/AIO article when no blocker exists.",
            "- Draft 1 social post from the same data atom.",
            "- Pair every price with property type: đất nền vs nhà đất.",
            "- Use answer-first copy, real DB numbers, internal links, FAQ, and safety caveat.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit token-light context for Radar BDS daily SEO publishing")
    parser.add_argument("--days", type=int, default=14, help="Lookback window for active listing pulse")
    parser.add_argument("--limit", type=int, default=8, help="Number of wards/articles to show")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    args = parser.parse_args()

    payload = {
        "date": dt.date.today().isoformat(),
        "pulse_days": args.days,
        "article_inventory": article_inventory(args.limit),
        "ward_pulse": query_ward_pulse(args.days, args.limit),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

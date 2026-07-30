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
import re
import sys
import unicodedata
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

PUBLISH_SCORE_MIN = 75


def normalize_text(value: object) -> str:
    raw = str(value or "").lower()
    raw = unicodedata.normalize("NFD", raw)
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    raw = raw.replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", raw).strip()


def slugify(value: object) -> str:
    return normalize_text(value).replace(" ", "-").strip("-")


def intent_exists(items: list[dict], required_terms: list[str]) -> bool:
    terms = [normalize_text(term) for term in required_terms if normalize_text(term)]
    if not terms:
        return False
    for item in items:
        haystack = normalize_text(f"{item.get('slug','')} {item.get('path','')} {item.get('title','')}")
        if all(term in haystack for term in terms):
            return True
    return False


def data_advantage_score(row: dict) -> int:
    active = int(row.get("active_listings") or 0)
    signals = int(row.get("signals") or 0)
    has_median = bool(row.get("dat_nen_median") or row.get("nha_dat_median"))
    score = 0
    if active >= 30:
        score += 12
    elif active >= 15:
        score += 9
    elif active >= 8:
        score += 6
    elif active >= 3:
        score += 3
    if signals >= 10:
        score += 8
    elif signals >= 5:
        score += 6
    elif signals >= 2:
        score += 4
    if has_median:
        score += 5
    return min(25, score)


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
    return {"counts": counts, "latest": items[:limit], "all": items}


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


def build_publish_candidates(ward_pulse: list[dict], inventory: dict, limit: int) -> list[dict]:
    """Build a compact scored shortlist for the daily SEO publisher.

    The score is intentionally simple/80-20. It is not a paid KD model; it
    forces the daily cron to choose long-tail, data-backed, funnel-linked,
    non-duplicate topics and to publish only when the final article can reach
    the minimum publish score.
    """
    items = inventory.get("all", [])
    candidates: list[dict] = []

    def add(title: str, slug: str, pillar: str, stage: str, components: dict, links: str, notes: str, duplicate: bool = False) -> None:
        score = sum(int(v) for v in components.values())
        can_publish = score >= PUBLISH_SCORE_MIN and not duplicate
        candidates.append({
            "title": title,
            "target": f"/tin-tuc/{slug}",
            "pillar": pillar,
            "stage": stage,
            "score": score,
            "components": components,
            "action": "PUBLISH" if can_publish else "UPGRADE_OR_PICK_NEXT",
            "links": links,
            "notes": notes,
        })

    # 1) Ward price long-tail candidates.
    for row in ward_pulse:
        ward = row["ward"]
        dup = intent_exists(items, ["gia dat", ward])
        data_score = data_advantage_score(row)
        components = {
            "intent": 25,
            "data": data_score,
            "funnel": 20,
            "no_dup": 0 if dup else 15,
            "social": 15 if int(row.get("signals") or 0) >= 2 else 8,
        }
        add(
            f"Giá đất {ward} hiện bao nhiêu? Đọc riêng đất nền và nhà đất",
            f"gia-dat-{row['slug']}-hien-bao-nhieu",
            "Giá đất theo phường",
            "TOFU/MOFU",
            components,
            f"/binh-duong/phuong-{row['slug']} → dashboard ward filter → /dinh-gia-bds",
            "same-intent exists; refresh/internal-link instead" if dup else "long-tail local + Radar data",
            duplicate=dup,
        )

    # 2) Comparison candidates from strongest adjacent data rows.
    strong = [r for r in ward_pulse if int(r.get("active_listings") or 0) >= 10 and data_advantage_score(r) >= 14]
    for a, b in zip(strong, strong[1:]):
        dup = intent_exists(items, [a["ward"], b["ward"]])
        data_score = min(25, data_advantage_score(a) + data_advantage_score(b) // 2)
        components = {"intent": 25, "data": data_score, "funnel": 20, "no_dup": 0 if dup else 15, "social": 15}
        add(
            f"{a['ward']} hay {b['ward']}: nên xem khu nào trước?",
            f"{a['slug']}-hay-{b['slug']}-nen-xem-khu-nao-truoc",
            "So sánh phường",
            "MOFU",
            components,
            f"/binh-duong/phuong-{a['slug']} + /binh-duong/phuong-{b['slug']} → dashboard filters",
            "same comparison intent may exist" if dup else "comparison intent, good social reuse",
            duplicate=dup,
        )

    # 3) Evergreen/tool-led candidates to keep AIO + product funnel alive.
    evergreen = [
        (
            "Cách định giá nhà đất Bình Dương bằng giá rao theo phường",
            "cach-dinh-gia-nha-dat-binh-duong-bang-gia-rao-theo-phuong",
            ["dinh gia", "binh duong", "gia rao"],
            "Free tools",
            "MOFU/BOFU",
            "/dinh-gia-bds → /bang-gia-dat → dashboard",
        ),
        (
            "Bảng giá đất và giá rao khác nhau thế nào khi xem nhà đất Bình Dương?",
            "bang-gia-dat-va-gia-rao-khac-nhau-the-nao",
            ["bang gia dat", "gia rao"],
            "Buyer guides",
            "TOFU",
            "/bang-gia-dat → /dinh-gia-bds → /bao-cao",
        ),
        (
            "Khi nào nên dùng công cụ định giá trước khi gọi môi giới?",
            "khi-nao-nen-dung-cong-cu-dinh-gia-truoc-khi-goi-moi-gioi",
            ["cong cu dinh gia", "moi gioi"],
            "Free tools",
            "MOFU/BOFU",
            "/dinh-gia-bds → dashboard signals",
        ),
    ]
    for title, slug, terms, pillar, stage, links in evergreen:
        dup = intent_exists(items, terms)
        components = {"intent": 23, "data": 18, "funnel": 20, "no_dup": 0 if dup else 15, "social": 10}
        add(title, slug, pillar, stage, components, links, "same-intent exists" if dup else "AIO/tool funnel support", duplicate=dup)

    candidates.sort(key=lambda c: (c["score"], c["components"].get("data", 0)), reverse=True)
    return candidates[:limit]


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
    lines.extend(["", "## Publish score gate", ""] )
    lines.append(f"- Minimum final score to publish: **{PUBLISH_SCORE_MIN}/100**.")
    lines.append("- Anh Cường rule: still publish **1 new `/tin-tuc` article every day** unless there is a real production/data blocker.")
    lines.append("- If the first topic is below threshold, do not publish weak content; upgrade it with stronger Radar data, clearer funnel links, FAQ/source/date, or pick the next candidate until score ≥ threshold.")
    lines.append("- Score formula: intent 25 + Radar data 25 + funnel links 20 + no cannibalization 15 + social reuse 15 = 100.")
    lines.extend(["", "### Scored candidate shortlist", ""])
    lines.append("| Score | Action | Pillar | Stage | Target | Link funnel | Notes |")
    lines.append("|---:|---|---|---|---|---|---|")
    for cand in payload.get("publish_candidates", []):
        lines.append(
            "| {score} | {action} | {pillar} | {stage} | {target} | {links} | {notes} |".format(
                score=cand["score"],
                action=cand["action"],
                pillar=cand["pillar"],
                stage=cand["stage"],
                target=cand["target"],
                links=cand["links"],
                notes=cand["notes"],
            )
        )
    lines.extend(
        [
            "",
            "## Daily publish reminder",
            "- Ship 1 NEW `/tin-tuc/<slug>` SEO/AIO article when no real blocker exists; refresh-only is not success for this cron.",
            "- Before writing, state the selected candidate and its score breakdown; final article must be ≥75/100 plus quality checklist pass.",
            "- Draft 1 social post from the same data atom.",
            "- Pair every price with property type: đất nền vs nhà đất.",
            "- Use `is_active = 1`, answer-first copy, real DB numbers, internal links, FAQ, and safety caveat.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit token-light context for Radar BDS daily SEO publishing")
    parser.add_argument("--days", type=int, default=14, help="Lookback window for active listing pulse")
    parser.add_argument("--limit", type=int, default=8, help="Number of wards/articles to show")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown")
    args = parser.parse_args()

    inventory = article_inventory(args.limit)
    ward_pulse = query_ward_pulse(args.days, args.limit)
    payload = {
        "date": dt.date.today().isoformat(),
        "pulse_days": args.days,
        "article_inventory": inventory,
        "ward_pulse": ward_pulse,
        "publish_candidates": build_publish_candidates(ward_pulse, inventory, args.limit),
        "publish_score_min": PUBLISH_SCORE_MIN,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

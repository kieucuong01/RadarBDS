"""Repair stale Guland decimal-price snapshots.

Older parsing accepted ``X.Y ty`` as the first part of an ``X ty Y`` pattern.
When a Guland detail page placed the area on the next line, e.g. ``2.55 ty``
then ``598.2m2``, the parser produced ``2.55 + 0.598 = 3.148``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
import unicodedata
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class GulandPriceValueUpdate:
    price_ty: float
    price_per_m2: float | None


@dataclass(frozen=True)
class GulandPriceHistoryUpdate(GulandPriceValueUpdate):
    price_history_id: int
    old_price_ty: float | None


@dataclass(frozen=True)
class GulandPriceRepairPlan:
    listing_id: int
    source_id: str
    raw_price_ty: float
    legacy_variants: tuple[float, ...]
    listing_update: GulandPriceValueUpdate | None
    history_updates: tuple[GulandPriceHistoryUpdate, ...]


_DECIMAL_PRICE_AREA_LINE_RE = re.compile(
    r"(?<![\d,.])(\d+[,.]\d+)\s*(?:tỷ|ty|ti)\s*[\r\n]+\s*"
    r"(\d+(?:[,.]\d+)?)\s*m(?:2|²)?\b",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("Đ", "D").replace("đ", "d")
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    ).lower()


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_price(value: float) -> float:
    return round(float(value), 4)


def _same_price(a: Any, b: Any) -> bool:
    left = _to_float(a)
    right = _to_float(b)
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return abs(left - right) < 0.001


def _price_per_m2(price_ty: float, area_m2: Any) -> float | None:
    area = _to_float(area_m2)
    if not area or area <= 0:
        return None
    return round(float(price_ty) * 1000 / area, 3)


def legacy_decimal_area_price_variants(text: str) -> tuple[float, ...]:
    """Return stale prices generated from decimal price followed by area line."""
    folded = _fold(text)
    variants: set[float] = set()
    for match in _DECIMAL_PRICE_AREA_LINE_RE.finditer(folded):
        price = float(match.group(1).replace(",", "."))
        area = match.group(2).replace(",", ".")
        area_integer = area.split(".", 1)[0]
        if not area_integer:
            continue
        variants.add(_round_price(price + int(area_integer) / (10 ** len(area_integer))))
    return tuple(sorted(variants))


def _raw_payload(raw_json: Any) -> dict[str, Any] | None:
    if isinstance(raw_json, Mapping):
        return dict(raw_json)
    if not isinstance(raw_json, str) or not raw_json.strip():
        return None
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _text_from_raw(raw: Mapping[str, Any]) -> str:
    return "\n".join(str(raw.get(key) or "") for key in ("title", "description"))


def build_guland_price_repair_plan(
    listing: Mapping[str, Any],
    price_history: Iterable[Mapping[str, Any]],
) -> GulandPriceRepairPlan | None:
    """Build a repair plan for one stale Guland decimal-price row."""
    raw = _raw_payload(listing.get("raw_json"))
    if not raw:
        return None

    raw_price = _to_float(raw.get("price_ty"))
    raw_area = _to_float(raw.get("area_m2") or listing.get("area_m2"))
    if raw_price is None or raw_price <= 0:
        return None

    variants = legacy_decimal_area_price_variants(_text_from_raw(raw))
    if not variants:
        return None

    target_price = _round_price(raw_price)
    target_ppm2 = _price_per_m2(target_price, raw_area)
    listing_update = None
    if (
        not _same_price(listing.get("price_ty"), target_price)
        and any(_same_price(listing.get("price_ty"), variant) for variant in variants)
    ):
        listing_update = GulandPriceValueUpdate(target_price, target_ppm2)

    history_updates: list[GulandPriceHistoryUpdate] = []
    for row in price_history:
        old_price = _to_float(row.get("price_ty"))
        if _same_price(old_price, target_price):
            continue
        if not any(_same_price(old_price, variant) for variant in variants):
            continue
        history_updates.append(
            GulandPriceHistoryUpdate(
                price_history_id=int(row["id"]),
                old_price_ty=old_price,
                price_ty=target_price,
                price_per_m2=target_ppm2,
            )
        )

    if listing_update is None and not history_updates:
        return None
    return GulandPriceRepairPlan(
        listing_id=int(listing["id"]),
        source_id=str(listing.get("source_id") or raw.get("post_id") or ""),
        raw_price_ty=target_price,
        legacy_variants=variants,
        listing_update=listing_update,
        history_updates=tuple(history_updates),
    )


def _history_rows(conn: Any, listing_id: int) -> list[Mapping[str, Any]]:
    return conn.execute(
        """
        SELECT id, price_ty, price_per_m2
        FROM price_history
        WHERE listing_id=?
        ORDER BY recorded_at ASC, id ASC
        """,
        (listing_id,),
    ).fetchall()


def _candidate_rows(
    conn: Any,
    *,
    listing_ids: Iterable[int] | None = None,
    limit: int | None = None,
) -> list[Mapping[str, Any]]:
    params: list[Any] = []
    where = ["l.source='guland'", "r.raw_json IS NOT NULL"]
    ids = [int(item) for item in (listing_ids or [])]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        where.append(f"l.id IN ({placeholders})")
        params.extend(ids)
    sql = f"""
        SELECT l.id, l.source_id, l.price_ty, l.price_per_m2, l.area_m2,
               r.raw_json
        FROM listings l
        JOIN raw_listings r ON r.id=l.raw_id
        WHERE {' AND '.join(where)}
        ORDER BY l.id ASC
    """
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(sql, params).fetchall()


def _reconcile_listing_price_flags(conn: Any, listing_id: int) -> None:
    first_row = conn.execute(
        """
        SELECT price_ty
        FROM price_history
        WHERE listing_id=? AND price_ty IS NOT NULL AND price_ty > 0
        ORDER BY recorded_at ASC, id ASC
        LIMIT 1
        """,
        (listing_id,),
    ).fetchone()
    listing = conn.execute(
        "SELECT price_ty FROM listings WHERE id=?",
        (listing_id,),
    ).fetchone()
    if not listing:
        return

    current = _to_float(listing["price_ty"])
    first = _to_float(first_row["price_ty"] if first_row else current)
    price_dropped = 0
    price_drop_pct = None
    suspicious_bait = 0
    if current and first and current < first * 0.99:
        drop_pct = round((first - current) / first * 100, 2)
        if drop_pct > 40.0:
            suspicious_bait = 1
        else:
            price_dropped = 1
            price_drop_pct = drop_pct

    conn.execute(
        """
        UPDATE listings
        SET price_first_ty=?,
            price_dropped=?,
            price_drop_pct=?,
            suspicious_bait=?
        WHERE id=?
        """,
        (first, price_dropped, price_drop_pct, suspicious_bait, listing_id),
    )


def repair_guland_decimal_prices(
    conn: Any,
    *,
    apply: bool = False,
    listing_ids: Iterable[int] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Audit or apply the Guland decimal-price repair against a DB connection."""
    plans: list[GulandPriceRepairPlan] = []
    for listing in _candidate_rows(conn, listing_ids=listing_ids, limit=limit):
        plan = build_guland_price_repair_plan(
            listing,
            _history_rows(conn, int(listing["id"])),
        )
        if plan:
            plans.append(plan)

    summary: dict[str, Any] = {
        "mode": "apply" if apply else "dry_run",
        "candidate_repairs": len(plans),
        "listing_updates": sum(1 for plan in plans if plan.listing_update),
        "price_history_updates": sum(len(plan.history_updates) for plan in plans),
        "listing_ids": [plan.listing_id for plan in plans],
        "plans": [
            {
                "listing_id": plan.listing_id,
                "source_id": plan.source_id,
                "raw_price_ty": plan.raw_price_ty,
                "legacy_variants": list(plan.legacy_variants),
                "listing_update": (
                    {
                        "price_ty": plan.listing_update.price_ty,
                        "price_per_m2": plan.listing_update.price_per_m2,
                    }
                    if plan.listing_update
                    else None
                ),
                "history_updates": [
                    {
                        "price_history_id": update.price_history_id,
                        "old_price_ty": update.old_price_ty,
                        "price_ty": update.price_ty,
                        "price_per_m2": update.price_per_m2,
                    }
                    for update in plan.history_updates
                ],
            }
            for plan in plans[:200]
        ],
    }
    if not apply:
        return summary

    now = datetime.now().isoformat(timespec="seconds")
    touched_ids: set[int] = set()
    for plan in plans:
        if plan.listing_update:
            conn.execute(
                """
                UPDATE listings
                SET price_ty=?,
                    price_per_m2=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    plan.listing_update.price_ty,
                    plan.listing_update.price_per_m2,
                    now,
                    plan.listing_id,
                ),
            )
            touched_ids.add(plan.listing_id)
        for update in plan.history_updates:
            conn.execute(
                """
                UPDATE price_history
                SET price_ty=?,
                    price_per_m2=?
                WHERE id=?
                """,
                (update.price_ty, update.price_per_m2, update.price_history_id),
            )
            touched_ids.add(plan.listing_id)

    for listing_id in sorted(touched_ids):
        _reconcile_listing_price_flags(conn, listing_id)
    summary["applied_listing_ids"] = sorted(touched_ids)
    return summary

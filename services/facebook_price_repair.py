"""Repair stale Facebook compact-price extraction snapshots.

Older parser revisions misread broker shorthand such as ``2ty050`` as
``2.5`` and sometimes dropped the fractional part of ``1ty550`` entirely.
This module keeps the repair narrow: it only changes rows whose current text
contains an explicit compact price and whose stored value matches a known
legacy misparse.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import unicodedata
from typing import Any, Iterable, Mapping

from cleansing.feature_extractor import extract_price


@dataclass(frozen=True)
class PriceValueUpdate:
    price_ty: float
    price_per_m2: float | None


@dataclass(frozen=True)
class PriceHistoryUpdate(PriceValueUpdate):
    price_history_id: int
    old_price_ty: float | None


@dataclass(frozen=True)
class PriceRepairPlan:
    listing_id: int
    parsed_price_ty: float
    legacy_variants: tuple[float, ...]
    listing_update: PriceValueUpdate | None
    history_updates: tuple[PriceHistoryUpdate, ...]


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


def _same_price(a: Any, b: Any) -> bool:
    left = _to_float(a)
    right = _to_float(b)
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return abs(left - right) < 0.001


def _round_price(value: float) -> float:
    return round(float(value), 4)


def _price_per_m2(price_ty: float, area_m2: Any) -> float | None:
    area = _to_float(area_m2)
    if not area or area <= 0:
        return None
    return round(float(price_ty) * 1000 / area, 3)


def _add_legacy_variants(
    out: set[float],
    ty: str,
    rest: str,
    *,
    parsed_price_ty: float | None,
) -> None:
    base = int(ty)
    rest_digits = re.sub(r"\D", "", rest or "")
    if not rest_digits:
        return
    correct = _round_price(base + int(rest_digits) / 1000)
    if parsed_price_ty is not None and not _same_price(correct, parsed_price_ty):
        return

    out.add(_round_price(base))
    if len(rest_digits) == 3 and rest_digits.startswith("0"):
        # Legacy bug: 2ty050 -> 2.5, 1ty099 -> 1.99.
        out.add(_round_price(base + int(rest_digits) / 100))


def legacy_compact_price_variants(text: str) -> tuple[float, ...]:
    """Return known stale prices that old parsers produced for compact text."""
    folded = _fold(text)
    parsed = extract_price(text)
    parsed_price_ty = _round_price(parsed) if parsed is not None else None
    variants: set[float] = set()

    compact_boundary = r"(?=\s*(?:tr|trieu|tl|bot|lh|lien|alo|zalo)\b|[^a-z0-9]|$)"
    for match in re.finditer(
        rf"(?<![a-z0-9])(\d{{1,2}})\s*(?:ty|ti|t)\s*(\d{{3}}){compact_boundary}",
        folded,
    ):
        _add_legacy_variants(
            variants,
            match.group(1),
            match.group(2),
            parsed_price_ty=parsed_price_ty,
        )

    for match in re.finditer(
        r"\bgia(?:\s+\w+){0,3}\s*[:=\-]?\s*(\d{1,2})(\d{3})(?!\d)",
        folded,
    ):
        _add_legacy_variants(
            variants,
            match.group(1),
            match.group(2),
            parsed_price_ty=parsed_price_ty,
        )

    return tuple(sorted(variants))


def _matches_legacy_variant(value: Any, variants: Iterable[float]) -> bool:
    return any(_same_price(value, variant) for variant in variants)


def build_price_repair_plan(
    listing: Mapping[str, Any],
    price_history: Iterable[Mapping[str, Any]],
) -> PriceRepairPlan | None:
    """Build a narrow repair plan for one Facebook listing."""
    text = "\n".join(
        str(part or "")
        for part in (listing.get("title"), listing.get("description"))
    )
    parsed = extract_price(text)
    if parsed is None:
        return None
    parsed = _round_price(parsed)

    variants = legacy_compact_price_variants(text)
    if not variants:
        return None

    area_m2 = listing.get("area_m2")
    ppm2 = _price_per_m2(parsed, area_m2)
    listing_update = None
    if (
        not _same_price(listing.get("price_ty"), parsed)
        and _matches_legacy_variant(listing.get("price_ty"), variants)
    ):
        listing_update = PriceValueUpdate(price_ty=parsed, price_per_m2=ppm2)

    history_updates: list[PriceHistoryUpdate] = []
    for row in price_history:
        old_price = _to_float(row.get("price_ty"))
        if _same_price(old_price, parsed):
            continue
        if not _matches_legacy_variant(old_price, variants):
            continue
        history_updates.append(
            PriceHistoryUpdate(
                price_history_id=int(row["id"]),
                old_price_ty=old_price,
                price_ty=parsed,
                price_per_m2=ppm2,
            )
        )

    if listing_update is None and not history_updates:
        return None
    return PriceRepairPlan(
        listing_id=int(listing["id"]),
        parsed_price_ty=parsed,
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
    where = [
        "source='facebook'",
        """(
            title ~* '(ty|ti|t)\\s*0[0-9]{2}'
         OR description ~* '(ty|ti|t)\\s*0[0-9]{2}'
         OR title ~* '(ty|ti|t)\\s*[1-9][0-9]{2}'
         OR description ~* '(ty|ti|t)\\s*[1-9][0-9]{2}'
         OR title ~* 'gi[aá]\\w*\\s*[:= -]*[0-9]{4}'
         OR description ~* 'gi[aá]\\w*\\s*[:= -]*[0-9]{4}'
        )""",
    ]
    ids = [int(item) for item in (listing_ids or [])]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        where.append(f"id IN ({placeholders})")
        params.extend(ids)
    sql = f"""
        SELECT id, title, description, price_ty, price_per_m2, area_m2
        FROM listings
        WHERE {' AND '.join(where)}
        ORDER BY id ASC
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


def repair_facebook_compact_prices(
    conn: Any,
    *,
    apply: bool = False,
    listing_ids: Iterable[int] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Audit or apply the compact-price repair against a DB connection."""
    plans: list[PriceRepairPlan] = []
    for listing in _candidate_rows(conn, listing_ids=listing_ids, limit=limit):
        plan = build_price_repair_plan(listing, _history_rows(conn, int(listing["id"])))
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
                "parsed_price_ty": plan.parsed_price_ty,
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

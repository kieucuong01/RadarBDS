"""Pure planning primitives for reconciling Guland result cards."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite
from typing import Any, Mapping


@dataclass(frozen=True)
class ExistingGulandSnapshot:
    raw_id: int
    listing_id: int
    url: str
    source_id: str | None
    price_ty: float | None
    first_seen_at: Any
    source_status: str


@dataclass(frozen=True)
class GulandReconciliationPlan:
    new_cards: tuple[dict, ...]
    unchanged_cards: tuple[dict, ...]
    changed_cards: tuple[dict, ...]
    invalid_price_cards: tuple[dict, ...]


def canonical_price_vnd(price_ty: object) -> int | None:
    """Normalize a price expressed in billions to one-million-VND precision."""
    if price_ty is None or isinstance(price_ty, bool):
        return None
    try:
        numeric = float(price_ty)
        decimal_value = Decimal(str(price_ty))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return None
    if not isfinite(numeric) or decimal_value <= 0:
        return None
    million_units = (decimal_value * Decimal("1000")).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return int(million_units) * 1_000_000


def plan_guland_cards(
    cards: list[dict],
    existing_by_url: Mapping[str, ExistingGulandSnapshot],
) -> GulandReconciliationPlan:
    """Partition cards without database, browser, logging, or global state."""
    new_cards: list[dict] = []
    unchanged_cards: list[dict] = []
    changed_cards: list[dict] = []
    invalid_price_cards: list[dict] = []

    for card in cards:
        url = str(card.get("url") or "")
        existing = existing_by_url.get(url)
        if existing is None:
            new_cards.append(card)
            continue

        card_price = canonical_price_vnd(card.get("price_ty"))
        if card_price is None:
            invalid_price_cards.append(card)
            continue

        existing_price = canonical_price_vnd(existing.price_ty)
        if existing_price == card_price:
            unchanged_cards.append(card)
        else:
            changed_cards.append(card)

    return GulandReconciliationPlan(
        new_cards=tuple(new_cards),
        unchanged_cards=tuple(unchanged_cards),
        changed_cards=tuple(changed_cards),
        invalid_price_cards=tuple(invalid_price_cards),
    )

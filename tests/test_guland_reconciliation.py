from datetime import datetime

from services.guland_reconciliation import (
    ExistingGulandSnapshot,
    canonical_price_vnd,
    plan_guland_cards,
)


FIRST_SEEN = datetime.fromisoformat("2026-07-01T08:00:00+07:00")


def test_canonical_price_rounds_to_one_million_vnd():
    assert canonical_price_vnd(2.5) == 2_500_000_000
    assert canonical_price_vnd(2.5004) == 2_500_000_000


def test_invalid_prices_never_become_changes():
    assert canonical_price_vnd(None) is None
    assert canonical_price_vnd(0) is None
    assert canonical_price_vnd(float("nan")) is None
    assert canonical_price_vnd("masked") is None


def test_planner_separates_new_unchanged_changed_and_invalid():
    new_url = "https://guland.vn/post/new-1001"
    same_url = "https://guland.vn/post/same-1002"
    changed_url = "https://guland.vn/post/changed-1003"
    masked_url = "https://guland.vn/post/masked-1004"
    existing = {
        same_url: ExistingGulandSnapshot(
            2, 12, same_url, "1002", 2.5, FIRST_SEEN, "active"
        ),
        changed_url: ExistingGulandSnapshot(
            3, 13, changed_url, "1003", 2.5, FIRST_SEEN, "active"
        ),
        masked_url: ExistingGulandSnapshot(
            4, 14, masked_url, "1004", 2.5, FIRST_SEEN, "active"
        ),
    }
    cards = [
        {"url": new_url, "price_ty": 1.9},
        {"url": same_url, "price_ty": 2.5},
        {"url": changed_url, "price_ty": 2.7},
        {"url": masked_url, "price_ty": None},
    ]

    plan = plan_guland_cards(cards, existing)

    assert [c["url"] for c in plan.new_cards] == [new_url]
    assert [c["url"] for c in plan.unchanged_cards] == [same_url]
    assert [c["url"] for c in plan.changed_cards] == [changed_url]
    assert [c["url"] for c in plan.invalid_price_cards] == [masked_url]


def test_planner_treats_increases_and_decreases_as_changes():
    increase_url = "https://guland.vn/post/increase-1005"
    decrease_url = "https://guland.vn/post/decrease-1006"
    existing = {
        increase_url: ExistingGulandSnapshot(
            5, 15, increase_url, "1005", 2.5, FIRST_SEEN, "active"
        ),
        decrease_url: ExistingGulandSnapshot(
            6, 16, decrease_url, "1006", 2.5, FIRST_SEEN, "active"
        ),
    }

    plan = plan_guland_cards(
        [
            {"url": increase_url, "price_ty": 2.7},
            {"url": decrease_url, "price_ty": 2.3},
        ],
        existing,
    )

    assert [card["url"] for card in plan.changed_cards] == [
        increase_url,
        decrease_url,
    ]

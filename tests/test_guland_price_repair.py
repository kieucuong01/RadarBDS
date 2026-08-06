import json

from services.guland_price_repair import (
    build_guland_price_repair_plan,
    legacy_decimal_area_price_variants,
)


def test_legacy_decimal_area_price_variants_cover_guland_area_line_bug():
    text = (
        "Ban dat 598.2m2 Phuong Phu An\n"
        "2.55 ty\n"
        "598.2m2"
    )

    assert legacy_decimal_area_price_variants(text) == (3.148,)


def test_build_guland_price_repair_plan_updates_listing_and_history():
    raw = {
        "post_id": "1766477",
        "title": "Ban dat 598.2m2 Phuong Phu An",
        "description": "Ban dat 598.2m2 Phuong Phu An\n2.55 ty\n598.2m2",
        "price_ty": 2.55,
        "area_m2": 598.2,
    }
    listing = {
        "id": 58918,
        "source_id": "1766477",
        "price_ty": 3.148,
        "price_per_m2": 5.262,
        "area_m2": 598.2,
        "raw_json": json.dumps(raw),
    }
    history = [
        {"id": 1, "price_ty": 2.55, "price_per_m2": 4.26},
        {"id": 2, "price_ty": 3.148, "price_per_m2": 5.262},
    ]

    plan = build_guland_price_repair_plan(listing, history)

    assert plan is not None
    assert plan.raw_price_ty == 2.55
    assert plan.listing_update is not None
    assert plan.listing_update.price_ty == 2.55
    assert plan.listing_update.price_per_m2 == 4.263
    assert [row.price_history_id for row in plan.history_updates] == [2]

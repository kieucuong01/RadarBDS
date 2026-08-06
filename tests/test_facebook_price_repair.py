from services.facebook_price_repair import (
    build_price_repair_plan,
    legacy_compact_price_variants,
)


def test_legacy_compact_price_variants_cover_leading_zero_and_ignored_fraction():
    assert 2.5 in legacy_compact_price_variants("Gia 2 ty 050")
    assert 1.99 in legacy_compact_price_variants("Gia 1ty099 trieu")
    assert 1.0 in legacy_compact_price_variants("Gia 1ty550")


def test_build_price_repair_plan_updates_listing_and_matching_history_snapshots():
    listing = {
        "id": 62104,
        "title": "Nha Tan An gia 2050",
        "description": "Gia 2 ty 050, DT 5.5x30",
        "price_ty": 2.5,
        "area_m2": 165,
        "price_per_m2": 15.152,
    }
    history = [
        {"id": 1, "price_ty": 2.5, "price_per_m2": 15.152},
        {"id": 2, "price_ty": 2.05, "price_per_m2": 12.424},
        {"id": 3, "price_ty": 1.9, "price_per_m2": 11.515},
    ]

    plan = build_price_repair_plan(listing, history)

    assert plan is not None
    assert plan.parsed_price_ty == 2.05
    assert plan.listing_update is not None
    assert plan.listing_update.price_ty == 2.05
    assert [row.price_history_id for row in plan.history_updates] == [1]
    assert plan.history_updates[0].price_ty == 2.05


def test_build_price_repair_plan_repairs_ignored_fraction_history_snapshot():
    listing = {
        "id": 66602,
        "title": "Dat Tan An hang ngop chu ha gia con 1ty",
        "description": "Dat Tan An hang ngop chu ha gia con 1ty550",
        "price_ty": 1.0,
        "area_m2": 100,
        "price_per_m2": 10.0,
    }
    history = [
        {"id": 10, "price_ty": 1.55, "price_per_m2": 15.5},
        {"id": 11, "price_ty": 1.0, "price_per_m2": 10.0},
    ]

    plan = build_price_repair_plan(listing, history)

    assert plan is not None
    assert plan.listing_update is not None
    assert plan.listing_update.price_ty == 1.55
    assert [row.price_history_id for row in plan.history_updates] == [11]
    assert plan.history_updates[0].price_ty == 1.55

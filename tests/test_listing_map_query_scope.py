from services.market_data import build_deal_sql, build_listing_filters


def test_deal_scope_requires_actionable_latest_valuation_and_display_mos():
    deal = build_deal_sql(15)

    assert "COALESCE(v.is_signal,0)=1" in deal.condition
    assert "source_quality_recheck" not in deal.condition
    assert "guland_weak_signal" not in deal.condition
    assert "guland_user_facing_risk" not in deal.condition
    assert "ambiguous_price_text" in deal.condition
    assert ">= 15.0" in deal.condition
    assert "sv.is_signal" not in deal.condition


def test_complete_listing_scope_reuses_every_public_filter():
    sql, params = build_listing_filters(
        sources=["facebook"],
        wards=["Phú Lợi"],
        prop_types=["dat_nen"],
        only_drops=False,
        area_min=80,
        area_max=150,
        price_min=1,
        price_max=3,
        keyword="ĐX 43",
        date_range="1m",
        require_complete=True,
        prefix="l.",
    )

    assert "l.ward IN (?)" in sql
    assert "l.source IN (?)" in sql
    assert "l.property_type IN (?)" in sql
    assert "l.area_m2 >= ?" in sql
    assert "l.area_m2 <= ?" in sql
    assert "l.price_ty >= ?" in sql
    assert "l.price_ty <= ?" in sql
    assert "NULLIF(TRIM(COALESCE(l.ward,'')), '') IS NOT NULL" in sql
    assert "l.price_ty IS NOT NULL AND l.price_ty > 0" in sql
    assert "l.area_m2 IS NOT NULL AND l.area_m2 > 0" in sql
    assert params[:3] == ["Phú Lợi", "facebook", "dat_nen"]
    assert 80 in params
    assert 150 in params
    assert 1 in params
    assert 3 in params
    assert " LIKE ?" in sql
    assert "-1 months" in params
    assert any(
        str(value).startswith("%") and "43" in str(value)
        for value in params
    )


def test_listing_scope_uses_parameter_placeholders_for_untrusted_filters():
    attack = "Phú Lợi') OR 1=1 --"

    sql, params = build_listing_filters(
        wards=[attack],
        sources=["facebook"],
        prefix="l.",
    )

    assert attack not in sql
    assert "l.ward IN (?)" in sql
    assert params[0] == attack


def test_public_listing_scope_uses_one_indexed_publisher_anti_join():
    sql, _params = build_listing_filters(
        sources=["facebook", "guland"],
        prefix="l.",
    )

    assert sql.count("NOT EXISTS") == 1
    assert sql.count("FROM listing_publishers lp") == 1
    assert "JOIN source_publishers sp ON sp.id = lp.publisher_id" in sql
    assert "lp.listing_id = l.id" in sql

    admin_sql, _admin_params = build_listing_filters(
        sources=["facebook", "guland"],
        prefix="l.",
        include_guland_high_activity=True,
    )
    assert "FROM listing_publishers lp" not in admin_sql

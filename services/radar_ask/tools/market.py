"""Server-owned market, opportunity, price-drop, and listing-risk tools."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from services.signal_quality import DEFAULT_SIGNAL_MOS_MIN_PCT

from ..contracts import EvidenceItem, SourceKind
from ..evidence import EvidenceBuilder, stable_evidence_id
from ..registry import (
    CompareAreasArgs,
    InspectListingRisksArgs,
    MarketTrendArgs,
    MatchBudgetArgs,
    RankPriceDropAreasArgs,
    RoadMarketArgs,
    SearchDealsArgs,
    ToolContext,
)
from .entities import (
    CANONICAL_CITY_WARDS,
    _as_of,
    _canonical_city,
    _read_context,
    _row_dict,
)
from .valuation import (
    CONFIDENCE_WARNING_FLAGS,
    DETERMINISTIC_QUALITY_BLOCKERS,
    _asking_statistics,
    _configure_timeout,
    _flags,
    _listing_quality_sql,
    _market_row_eligible,
    _number,
    _settings,
)


MARKET_COLUMNS = """
    listing_id, title, source, ward, road_name, road_tier, property_type,
    price_ty, price_per_m2, area_m2, frontage_m, depth_m, has_so,
    price_dropped, price_drop_pct, possibly_duplicate, suspicious_bait,
    extraction_quality_flags, public_visible,
    COALESCE(last_seen_at, crawled_at) AS activity_at
"""

SIGNAL_COLUMNS = """
    listing_id, title, source, ward, road_name, road_tier, property_type,
    price_ty, listing_price_per_m2 AS price_per_m2, area_m2,
    frontage_m, depth_m, has_so, price_dropped, price_drop_pct,
    possibly_duplicate, suspicious_bait, source_quality_flags,
    source_quality_recheck, fair_ppm2, actual_ppm2, mos_pct,
    signal_score, is_actionable, publisher_visible_public,
    COALESCE(activity_at, refreshed_at) AS activity_at,
    price_updated_at, refreshed_at
"""


def _rows(cursor) -> list[dict[str, Any]]:
    return [_row_dict(cursor, raw) for raw in cursor.fetchall()]


def _latest_as_of(rows: list[Mapping[str, Any]]):
    return max(_as_of(row.get("activity_at") or row.get("crawled_at")) for row in rows)


def _aggregate_market_item(
    *,
    source_ref: str,
    rows: list[Mapping[str, Any]],
    value: dict[str, Any],
    method: str,
) -> EvidenceItem:
    as_of = _latest_as_of(rows)
    version = f"market:{as_of.isoformat(timespec='seconds')}:{len(rows)}"
    return EvidenceItem(
        evidence_id=stable_evidence_id("market_stat", source_ref, version),
        source_kind=SourceKind.MARKET_STAT,
        source_ref=source_ref,
        value=value,
        unit="million_vnd_per_m2",
        calculation_method=method,
        as_of=as_of,
        dataset_version=version,
        sample_size=len(rows),
        provenance={"method": method},
    )


def _fetch_exact_road(
    conn,
    *,
    road: str,
    ward: str | None,
    property_type: str | None,
    window_days: int,
    row_limit: int,
    tier: str,
) -> list[dict[str, Any]]:
    visibility_sql = "" if tier == "admin" else "AND public_visible"
    cursor = conn.execute(
        f"""
        /* radar_ask:road_exact */
        SELECT {MARKET_COLUMNS}
        FROM public.radar_ask_v_listings
        WHERE LOWER(road_name)=LOWER(%s)
          AND (CAST(%s AS text) IS NULL OR ward=%s)
          AND (CAST(%s AS text) IS NULL OR property_type=%s)
          {visibility_sql}
          AND {_listing_quality_sql()}
          AND COALESCE(last_seen_at,crawled_at)::timestamptz
              >= NOW() - (%s * INTERVAL '1 day')
        ORDER BY COALESCE(last_seen_at,crawled_at) DESC, listing_id DESC
        LIMIT %s
        """,
        (road, ward, ward, property_type, property_type, window_days, row_limit),
    )
    return _rows(cursor)


def _fetch_road_scopes(
    conn,
    *,
    road: str,
    allowed_wards: set[str],
    tier: str,
) -> list[dict[str, Any]]:
    visibility_sql = "" if tier == "admin" else "AND public_visible"
    params: list[Any] = [road]
    city_sql = ""
    if allowed_wards:
        ordered_wards = sorted(allowed_wards)
        city_sql = f"AND ward IN ({','.join(['%s'] * len(ordered_wards))})"
        params.extend(ordered_wards)
    params.append(10)
    cursor = conn.execute(
        f"""
        /* radar_ask:road_scopes */
        SELECT ward, COUNT(*)::integer AS sample_count,
               MAX(COALESCE(last_seen_at,crawled_at)::timestamptz) AS as_of
        FROM public.radar_ask_v_listings
        WHERE LOWER(road_name)=LOWER(%s)
          {city_sql}
          {visibility_sql}
        GROUP BY ward
        ORDER BY ward
        LIMIT %s
        """,
        tuple(params),
    )
    return _rows(cursor)


def _fetch_ward_tier_fallback(
    conn,
    *,
    ward: str,
    road_tier: int,
    property_type: str | None,
    row_limit: int,
    tier: str,
) -> list[dict[str, Any]]:
    visibility_sql = "" if tier == "admin" else "AND public_visible"
    cursor = conn.execute(
        f"""
        /* radar_ask:road_fallback */
        SELECT {MARKET_COLUMNS}
        FROM public.radar_ask_v_listings
        WHERE ward=%s AND COALESCE(road_tier,0)=%s
          AND (CAST(%s AS text) IS NULL OR property_type=%s)
          {visibility_sql}
          AND {_listing_quality_sql()}
          AND COALESCE(last_seen_at,crawled_at)::timestamptz
              >= NOW() - (180 * INTERVAL '1 day')
        ORDER BY COALESCE(last_seen_at,crawled_at) DESC, listing_id DESC
        LIMIT %s
        """,
        (ward, road_tier, property_type, property_type, row_limit),
    )
    return _rows(cursor)


def estimate_road_market(*, args: RoadMarketArgs, context: ToolContext):
    question = f"road market {args.road}"
    settings = _settings()
    canonical_city = _canonical_city(args.city)
    if args.city and canonical_city is None:
        return (
            EvidenceBuilder(question_snapshot=question)
            .missing("city_not_supported_or_unresolved")
            .build()
        )
    allowed_wards = set(CANONICAL_CITY_WARDS.get(canonical_city or "", ()))
    if args.ward and allowed_wards and args.ward not in allowed_wards:
        return (
            EvidenceBuilder(question_snapshot=question)
            .missing("city_ward_scope_mismatch")
            .build()
        )

    def eligible_exact(rows):
        return [
            row
            for row in rows
            if _market_row_eligible(row, tier=context.ask.tier)
            and (not allowed_wards or row.get("ward") in allowed_wards)
        ]

    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        effective_ward = args.ward
        if effective_ward is None:
            scopes = _fetch_road_scopes(
                conn,
                road=args.road,
                allowed_wards=allowed_wards,
                tier=context.ask.tier,
            )
            scope_wards = sorted(
                {str(row.get("ward")) for row in scopes if row.get("ward")}
            )
            if len(scope_wards) > 1:
                return (
                    EvidenceBuilder(question_snapshot=question)
                    .clarify([f"{args.road}, {ward}" for ward in scope_wards])
                    .missing("road_location_is_ambiguous")
                    .build()
                )
            if scope_wards:
                effective_ward = scope_wards[0]
        exact_rows = _fetch_exact_road(
            conn,
            road=args.road,
            ward=effective_ward,
            property_type=args.property_type,
            window_days=args.window_days,
            row_limit=settings.evidence_row_limit,
            tier=context.ask.tier,
        )
        exact = eligible_exact(exact_rows)
        window_used = args.window_days
        extended = False
        if args.window_days <= 90 and len(exact) < 3:
            exact_rows = _fetch_exact_road(
                conn,
                road=args.road,
                ward=effective_ward,
                property_type=args.property_type,
                window_days=180,
                row_limit=settings.evidence_row_limit,
                tier=context.ask.tier,
            )
            exact = eligible_exact(exact_rows)
            window_used = 180
            extended = True

        scope = "exact_road"
        used_rows = exact
        ward = effective_ward or (str(exact[0].get("ward")) if exact else None)
        fallback_tier = 0
        if len(exact) < 3:
            if exact:
                fallback_tier = Counter(
                    int(row.get("road_tier") or 0) for row in exact
                ).most_common(1)[0][0]
            if ward:
                fallback_rows = _fetch_ward_tier_fallback(
                    conn,
                    ward=ward,
                    road_tier=fallback_tier,
                    property_type=args.property_type,
                    row_limit=settings.evidence_row_limit,
                    tier=context.ask.tier,
                )
                used_rows = [
                    row
                    for row in fallback_rows
                    if _market_row_eligible(row, tier=context.ask.tier)
                ]
                scope = "ward_road_tier_fallback"
                window_used = 180

    if not used_rows:
        return (
            EvidenceBuilder(question_snapshot=question)
            .missing("eligible_road_market_sample_not_found")
            .build()
        )
    stats = _asking_statistics(used_rows)
    builder = (
        EvidenceBuilder(question_snapshot=question)
        .resolve(road=args.road, ward=ward)
        .warn("asking_prices_not_transaction_prices")
        .calculate(
            market_scope=scope,
            road=args.road,
            ward=ward,
            property_type=args.property_type,
            window_days_used=window_used,
            road_tier=fallback_tier if scope != "exact_road" else None,
            **stats,
        )
    )
    if extended:
        builder.warn(f"extended_window_{args.window_days}_to_180_days")
    if scope != "exact_road":
        builder.warn("insufficient_exact_road")
    elif len(exact) < 5:
        builder.warn("low_sample")
    source_ref = (
        f"road-market:{ward or 'unknown'}:{args.road}:"
        f"{scope}:{window_used}d"
    )
    return builder.add(
        _aggregate_market_item(
            source_ref=source_ref,
            rows=used_rows,
            value={
                "road": args.road,
                "ward": ward,
                "market_scope": scope,
                "window_days": window_used,
                **stats,
                "sample_listing_refs": [
                    f"radar-listing:{int(row['listing_id'])}" for row in used_rows[:10]
                ],
            },
            method="bounded_eligible_asking_price_distribution",
        )
    ).build()


def _fetch_area_sample(
    conn,
    *,
    area: str,
    property_type: str | None,
    window_days: int,
    row_limit: int,
    tier: str,
) -> list[dict[str, Any]]:
    visibility_sql = "" if tier == "admin" else "AND public_visible"
    cursor = conn.execute(
        f"""
        /* radar_ask:area_sample */
        SELECT {MARKET_COLUMNS}
        FROM public.radar_ask_v_listings
        WHERE ward=%s
          AND (CAST(%s AS text) IS NULL OR property_type=%s)
          {visibility_sql}
          AND {_listing_quality_sql()}
          AND COALESCE(last_seen_at,crawled_at)::timestamptz
              >= NOW() - (%s * INTERVAL '1 day')
        ORDER BY COALESCE(last_seen_at,crawled_at) DESC, listing_id DESC
        LIMIT %s
        """,
        (area, property_type, property_type, window_days, row_limit),
    )
    return _rows(cursor)


def compare_areas(*, args: CompareAreasArgs, context: ToolContext):
    question = f"compare areas {' / '.join(args.areas)}"
    settings = _settings()
    builder = (
        EvidenceBuilder(
            question_snapshot=question,
            row_limit=min(len(args.areas), settings.evidence_row_limit),
        )
        .warn("asking_prices_not_transaction_prices")
    )
    calculations: dict[str, Any] = {}
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        for area in args.areas:
            rows = _fetch_area_sample(
                conn,
                area=area,
                property_type=args.property_type,
                window_days=args.window_days,
                row_limit=settings.evidence_row_limit,
                tier=context.ask.tier,
            )
            eligible = [
                row for row in rows if _market_row_eligible(row, tier=context.ask.tier)
            ]
            if not eligible:
                calculations[area] = {"sample_count": 0}
                continue
            stats = _asking_statistics(eligible)
            calculations[area] = stats
            builder.add(
                _aggregate_market_item(
                    source_ref=f"ward-market:{area}:{args.window_days}d",
                    rows=eligible,
                    value={"ward": area, "property_type": args.property_type, **stats},
                    method="bounded_ward_asking_price_distribution",
                )
            )
    if not any(int(value.get("sample_count") or 0) for value in calculations.values()):
        return builder.missing("eligible_area_samples_not_found").build()
    return builder.calculate(
        metric="asking_price_per_m2",
        window_days=args.window_days,
        areas=calculations,
    ).build()


def get_market_trend(*, args: MarketTrendArgs, context: ToolContext):
    question = f"market trend {args.ward or args.road or 'all'}"
    settings = _settings()
    visibility_sql = "" if context.ask.tier == "admin" else "AND public_visible"
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        cursor = conn.execute(
            f"""
            /* radar_ask:market_trend */
            WITH eligible AS (
                SELECT price_per_m2,
                       COALESCE(last_seen_at,crawled_at)::timestamptz AS activity_at
                FROM public.radar_ask_v_listings
                WHERE (CAST(%s AS text) IS NULL OR ward=%s)
                  AND (CAST(%s AS text) IS NULL OR LOWER(road_name)=LOWER(%s))
                  AND (CAST(%s AS text) IS NULL OR property_type=%s)
                  {visibility_sql}
                  AND {_listing_quality_sql()}
                  AND COALESCE(last_seen_at,crawled_at)::timestamptz
                      >= NOW() - (%s * INTERVAL '1 day')
            ), periodized AS (
                SELECT CASE
                           WHEN activity_at >= NOW() - (
                               %s::double precision / 2.0 * INTERVAL '1 day'
                           ) THEN 'current'
                           ELSE 'previous'
                       END AS period,
                       price_per_m2,
                       activity_at
                FROM eligible
            )
            SELECT period,
                   COUNT(*)::integer AS sample_count,
                   percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY price_per_m2
                   )::double precision AS median_asking_ppm2_million,
                   MAX(activity_at) AS activity_at
            FROM periodized
            GROUP BY period
            ORDER BY period
            """,
            (
                args.ward,
                args.ward,
                args.road,
                args.road,
                args.property_type,
                args.property_type,
                args.window_days,
                args.window_days,
            ),
        )
        period_rows = _rows(cursor)
    periods = {str(row.get("period")): row for row in period_rows}
    if "previous" not in periods or "current" not in periods:
        return (
            EvidenceBuilder(question_snapshot=question)
            .missing("market_trend_requires_both_periods")
            .build()
        )
    previous = periods["previous"]
    current = periods["current"]
    previous_median = float(previous["median_asking_ppm2_million"])
    current_median = float(current["median_asking_ppm2_million"])
    change_pct = (
        round((current_median - previous_median) / previous_median * 100, 2)
        if previous_median
        else None
    )
    calculation = {
        "metric": "median_asking_price_per_m2",
        "window_days": args.window_days,
        "previous_sample_count": int(previous.get("sample_count") or 0),
        "current_sample_count": int(current.get("sample_count") or 0),
        "previous_median_asking_ppm2_million": round(previous_median, 2),
        "current_median_asking_ppm2_million": round(current_median, 2),
        "change_pct": change_pct,
    }
    as_of = max(_as_of(previous.get("activity_at")), _as_of(current.get("activity_at")))
    version = f"market-trend:{as_of.isoformat(timespec='seconds')}"
    return (
        EvidenceBuilder(question_snapshot=question)
        .resolve(ward=args.ward, road=args.road)
        .warn("asking_price_trend_not_transaction_price_index")
        .calculate(**calculation)
        .add(
            EvidenceItem(
                evidence_id=stable_evidence_id(
                    "market_stat",
                    f"market-trend:{args.ward or 'all'}:{args.road or 'all'}:{args.window_days}d",
                    version,
                ),
                source_kind=SourceKind.MARKET_STAT,
                source_ref=f"market-trend:{args.ward or 'all'}:{args.road or 'all'}:{args.window_days}d",
                value=calculation,
                unit="million_vnd_per_m2",
                calculation_method="postgres_two_period_median_asking_price_change",
                as_of=as_of,
                dataset_version=version,
                sample_size=int(previous.get("sample_count") or 0)
                + int(current.get("sample_count") or 0),
                provenance={"method": "fixed_now_anchored_two_period_aggregate"},
            )
        )
        .build()
    )


def match_budget(*, args: MatchBudgetArgs, context: ToolContext):
    question = f"match budget {args.budget_ty} billion VND"
    settings = _settings()
    budget = float(args.budget_ty)
    canonical_city = _canonical_city(args.city)
    if args.city and canonical_city is None:
        return (
            EvidenceBuilder(question_snapshot=question)
            .missing("city_not_supported_or_unresolved")
            .build()
        )
    city_wards = set(CANONICAL_CITY_WARDS.get(canonical_city or "", ()))
    sql_filters = ["price_ty>0", "price_ty<=%s"]
    sql_params: list[Any] = [budget]
    if city_wards:
        ordered_city_wards = sorted(city_wards)
        sql_filters.append(
            f"ward IN ({','.join(['%s'] * len(ordered_city_wards))})"
        )
        sql_params.extend(ordered_city_wards)
    if args.wards:
        sql_filters.append(f"ward IN ({','.join(['%s'] * len(args.wards))})")
        sql_params.extend(args.wards)
    if args.property_types:
        sql_filters.append(
            f"property_type IN ({','.join(['%s'] * len(args.property_types))})"
        )
        sql_params.extend(args.property_types)
    if context.ask.tier != "admin":
        sql_filters.append("public_visible")
    sql_filters.append(_listing_quality_sql())
    sql_params.append(settings.evidence_row_limit)
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        cursor = conn.execute(
            f"""
            /* radar_ask:budget */
            SELECT {MARKET_COLUMNS}
            FROM public.radar_ask_v_listings
            WHERE {' AND '.join(sql_filters)}
            ORDER BY price_ty DESC, COALESCE(last_seen_at,crawled_at) DESC
            LIMIT %s
            """,
            tuple(sql_params),
        )
        raw_rows = _rows(cursor)
    eligible = [
        row
        for row in raw_rows
        if _market_row_eligible(row, tier=context.ask.tier)
        and (_number(row.get("price_ty")) or float("inf")) <= budget
        and (not args.wards or row.get("ward") in args.wards)
        and (not city_wards or row.get("ward") in city_wards)
        and (not args.property_types or row.get("property_type") in args.property_types)
    ][: min(args.limit, settings.evidence_row_limit)]
    if not eligible:
        return (
            EvidenceBuilder(question_snapshot=question)
            .missing("no_eligible_listings_within_budget")
            .build()
        )
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in eligible:
        grouped[str(row.get("ward") or "unknown")].append(row)
    area_matches = []
    for ward, rows in grouped.items():
        prices = [float(row["price_ty"]) for row in rows]
        ppm2 = [float(row["price_per_m2"]) for row in rows]
        area_matches.append(
            {
                "ward": ward,
                "listing_count": len(rows),
                "median_asking_price_ty": round(statistics.median(prices), 3),
                "median_asking_ppm2_million": round(statistics.median(ppm2), 2),
                "budget_headroom_ty": round(budget - statistics.median(prices), 3),
            }
        )
    area_matches.sort(
        key=lambda row: (row["listing_count"], row["budget_headroom_ty"]), reverse=True
    )
    builder = (
        EvidenceBuilder(
            question_snapshot=question,
            row_limit=min(args.limit, settings.evidence_row_limit),
        )
        .warn("matches_use_current_asking_prices_not_transaction_prices")
        .calculate(
            budget_ty=budget,
            matched_listing_count=len(eligible),
            area_matches=area_matches,
        )
    )
    for row in eligible:
        listing_id = int(row["listing_id"])
        as_of = _as_of(row.get("activity_at"))
        version = f"budget-match:{as_of.isoformat(timespec='seconds')}"
        source_ref = f"radar-listing:{listing_id}:budget-match"
        builder.add(
            EvidenceItem(
                evidence_id=stable_evidence_id("listing", source_ref, version),
                source_kind=SourceKind.LISTING,
                source_ref=source_ref,
                value={
                    "listing_ref": f"radar-listing:{listing_id}",
                    "ward": row.get("ward"),
                    "property_type": row.get("property_type"),
                    "asking_price_ty": _number(row.get("price_ty")),
                    "asking_price_per_m2_million": _number(row.get("price_per_m2")),
                    "area_m2": _number(row.get("area_m2")),
                },
                as_of=as_of,
                dataset_version=version,
                provenance={"method": "bounded_budget_match"},
            )
        )
    return builder.build()


def _effective_mos_floor(args: SearchDealsArgs, *, tier: str) -> float:
    requested = float(args.mos_min_pct)
    if tier in {"vip", "admin"}:
        return max(10.0, requested)
    return max(DEFAULT_SIGNAL_MOS_MIN_PCT, requested)


def _signal_publicly_visible(row: Mapping[str, Any], *, tier: str) -> bool:
    return tier == "admin" or bool(row.get("publisher_visible_public", True))


def search_deals(*, args: SearchDealsArgs, context: ToolContext):
    question = "search actionable Radar deals"
    settings = _settings()
    effective_mos = _effective_mos_floor(args, tier=context.ask.tier)
    sql_filters = ["is_actionable", "mos_pct>=%s"]
    sql_params: list[Any] = [effective_mos]
    if args.max_price_per_m2_million is not None:
        sql_filters.append("listing_price_per_m2<=%s")
        sql_params.append(float(args.max_price_per_m2_million))
    if args.max_budget_ty is not None:
        sql_filters.append("price_ty<=%s")
        sql_params.append(float(args.max_budget_ty))
    if args.wards:
        sql_filters.append(f"ward IN ({','.join(['%s'] * len(args.wards))})")
        sql_params.extend(args.wards)
    if args.property_types:
        sql_filters.append(
            f"property_type IN ({','.join(['%s'] * len(args.property_types))})"
        )
        sql_params.extend(args.property_types)
    if context.ask.tier != "admin":
        sql_filters.append("publisher_visible_public")
    sql_params.append(settings.evidence_row_limit)
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        cursor = conn.execute(
            f"""
            /* radar_ask:deals */
            SELECT {SIGNAL_COLUMNS}
            FROM public.radar_ask_v_signal_cards
            WHERE {' AND '.join(sql_filters)}
            ORDER BY signal_score DESC, mos_pct DESC, listing_id DESC
            LIMIT %s
            """,
            tuple(sql_params),
        )
        raw_rows = _rows(cursor)
    eligible = []
    for row in raw_rows:
        ppm2 = _number(row.get("price_per_m2"))
        price = _number(row.get("price_ty"))
        mos = _number(row.get("mos_pct"))
        if not bool(row.get("is_actionable")):
            continue
        if not _signal_publicly_visible(row, tier=context.ask.tier):
            continue
        if mos is None or mos < effective_mos:
            continue
        if args.max_price_per_m2_million is not None and (
            ppm2 is None or ppm2 > float(args.max_price_per_m2_million)
        ):
            continue
        if args.max_budget_ty is not None and (
            price is None or price > float(args.max_budget_ty)
        ):
            continue
        if args.wards and row.get("ward") not in args.wards:
            continue
        if args.property_types and row.get("property_type") not in args.property_types:
            continue
        eligible.append(row)
    evidence_limit = min(args.limit, settings.evidence_row_limit)
    eligible = eligible[:evidence_limit]
    builder = (
        EvidenceBuilder(question_snapshot=question, row_limit=evidence_limit)
        .warn("asking_price_and_model_fair_value_are_not_transaction_prices")
        .calculate(
            effective_mos_min_pct=effective_mos,
            actionable_gate="signal_card_read_model.is_actionable_from_shared_signal_quality",
            result_count=len(eligible),
        )
    )
    if effective_mos < DEFAULT_SIGNAL_MOS_MIN_PCT:
        builder.warn("below_public_mos_threshold_caution")
    if not eligible:
        return builder.missing("no_actionable_deals_match_filters").build()
    for row in eligible:
        listing_id = int(row["listing_id"])
        as_of = _as_of(row.get("refreshed_at") or row.get("activity_at"))
        version = f"signal:{as_of.isoformat(timespec='seconds')}"
        source_ref = f"radar-signal:{listing_id}"
        builder.add(
            EvidenceItem(
                evidence_id=stable_evidence_id("valuation", source_ref, version),
                source_kind=SourceKind.VALUATION,
                source_ref=source_ref,
                value={
                    "listing_ref": f"radar-listing:{listing_id}",
                    "ward": row.get("ward"),
                    "road_name": row.get("road_name"),
                    "property_type": row.get("property_type"),
                    "asking_price_ty": _number(row.get("price_ty")),
                    "asking_price_per_m2_million": _number(row.get("price_per_m2")),
                    "fair_price_per_m2_million": _number(row.get("fair_ppm2")),
                    "mos_pct": _number(row.get("mos_pct")),
                    "signal_score": int(row.get("signal_score") or 0),
                    "area_m2": _number(row.get("area_m2")),
                },
                as_of=as_of,
                dataset_version=version,
                sample_size=None,
                provenance={"method": "shared_actionable_signal_read_model"},
                quality_flags=_flags(row.get("source_quality_flags")),
            )
        )
    return builder.build()


def rank_price_drop_areas(*, args: RankPriceDropAreasArgs, context: ToolContext):
    question = f"rank price drop areas {args.window_days} days"
    settings = _settings()
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        visibility_sql = (
            "" if context.ask.tier == "admin" else "AND publisher_visible_public"
        )
        cursor = conn.execute(
            f"""
            /* radar_ask:price_drop_areas */
            SELECT ward,
                   COUNT(DISTINCT listing_id)::integer AS signal_count,
                   percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY price_drop_pct
                   )::double precision AS median_price_drop_pct,
                   percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY mos_pct
                   )::double precision AS median_mos_pct,
                   MAX(price_updated_at::timestamptz) AS as_of
            FROM public.radar_ask_v_signal_cards
            WHERE is_actionable AND price_dropped
              AND mos_pct>=15
              {visibility_sql}
              AND price_updated_at::timestamptz >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY ward
            ORDER BY signal_count DESC,
                     median_price_drop_pct DESC NULLS LAST,
                     median_mos_pct DESC NULLS LAST,
                     ward
            LIMIT %s
            """,
            (args.window_days, min(args.limit, settings.evidence_row_limit)),
        )
        aggregate_rows = _rows(cursor)
    areas = [
        {
            "ward": str(row.get("ward") or "unknown"),
            "signal_count": int(row.get("signal_count") or 0),
            "median_price_drop_pct": _number(row.get("median_price_drop_pct")),
            "median_mos_pct": _number(row.get("median_mos_pct")),
        }
        for row in aggregate_rows
    ]
    builder = (
        EvidenceBuilder(
            question_snapshot=question,
            row_limit=max(1, min(settings.evidence_row_limit, len(areas))),
        )
        .calculate(
            window_days=args.window_days,
            actionable_gate="signal_card_read_model.is_actionable_from_shared_signal_quality",
            areas=areas,
        )
    )
    if not areas:
        return builder.missing("no_actionable_price_drop_signals_in_window").build()
    for area, row in zip(areas, aggregate_rows, strict=True):
        as_of = _as_of(row.get("as_of"))
        version = f"price-drop-area:{as_of.isoformat(timespec='seconds')}"
        source_ref = f"price-drop-area:{area['ward']}:{args.window_days}d"
        builder.add(
            EvidenceItem(
                evidence_id=stable_evidence_id("market_stat", source_ref, version),
                source_kind=SourceKind.MARKET_STAT,
                source_ref=source_ref,
                value=area,
                unit="signals",
                calculation_method="postgres_actionable_price_drop_aggregate_by_ward",
                as_of=as_of,
                dataset_version=version,
                sample_size=area["signal_count"],
                provenance={"method": "shared_actionable_gate_public_mos_15"},
            )
        )
    return builder.build()


def inspect_listing_risks(*, args: InspectListingRisksArgs, context: ToolContext):
    question = f"inspect listing risks {args.listing_id}"
    settings = _settings()
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        listing_cursor = conn.execute(
            """
            /* radar_ask:risk_listing */
            SELECT listing_id, ward, road_name, property_type, price_ty,
                   price_per_m2, area_m2, frontage_m, depth_m, has_so,
                   possibly_duplicate, duplicate_of_id, suspicious_bait,
                   extraction_quality_flags, public_visible,
                   COALESCE(last_seen_at,crawled_at) AS activity_at
            FROM public.radar_ask_v_listings
            WHERE listing_id=%s
            LIMIT 1
            """,
            (args.listing_id,),
        )
        listing_raw = listing_cursor.fetchone()
        if listing_raw is None:
            return (
                EvidenceBuilder(question_snapshot=question)
                .missing("listing_not_found_or_not_visible")
                .build()
            )
        listing = _row_dict(listing_cursor, listing_raw)
        if context.ask.tier != "admin" and not bool(listing.get("public_visible")):
            return (
                EvidenceBuilder(question_snapshot=question)
                .missing("listing_not_found_or_not_visible")
                .build()
            )
        valuation_cursor = conn.execute(
            """
            /* radar_ask:risk_valuation */
            SELECT valuation_id, listing_id, fair_ppm2, actual_ppm2, mos_pct,
                   is_signal, signal_score, n_segment, source_quality_flags,
                   source_quality_recheck, legal_status, trust_tier,
                   trust_score, legal_flags, computed_at, valuation_trace
            FROM public.radar_ask_v_valuations
            WHERE listing_id=%s
            ORDER BY computed_at DESC, valuation_id DESC
            LIMIT 1
            """,
            (args.listing_id,),
        )
        valuation_raw = valuation_cursor.fetchone()
        valuation = (
            _row_dict(valuation_cursor, valuation_raw) if valuation_raw is not None else {}
        )

    all_flags = set(_flags(listing.get("extraction_quality_flags")))
    all_flags.update(_flags(valuation.get("source_quality_flags")))
    legal_flags = set(_flags(valuation.get("legal_flags")))
    legal_blockers = {
        "area_mismatch",
        "ward_mismatch",
        "road_conflict",
        "tho_cu_mismatch",
    }
    blocking = set(all_flags & DETERMINISTIC_QUALITY_BLOCKERS)
    warnings = set(all_flags & CONFIDENCE_WARNING_FLAGS)
    blocking.update(legal_flags & legal_blockers)
    warnings.update(legal_flags - legal_blockers)
    if bool(listing.get("possibly_duplicate")) or listing.get("duplicate_of_id"):
        blocking.add("possibly_duplicate")
    if bool(listing.get("suspicious_bait")):
        blocking.add("suspicious_bait")
    if bool(valuation.get("source_quality_recheck")):
        warnings.add("source_quality_recheck_required")
    legal_status = str(valuation.get("legal_status") or "unverified")
    trust_tier = str(valuation.get("trust_tier") or "candidate_signal")
    if legal_status not in {"verified", "has_document"} and trust_tier != "has_legal_doc":
        warnings.add("legal_status_not_verified")

    as_of = _as_of(valuation.get("computed_at") or listing.get("activity_at"))
    version = f"risk:{as_of.isoformat(timespec='seconds')}"
    source_ref = f"radar-listing:{args.listing_id}:risk"
    value = {
        "listing_ref": f"radar-listing:{args.listing_id}",
        "asking_price_ty": _number(listing.get("price_ty")),
        "asking_price_per_m2_million": _number(listing.get("price_per_m2")),
        "fair_price_per_m2_million": _number(valuation.get("fair_ppm2")),
        "mos_pct": _number(valuation.get("mos_pct")),
        "sample_count": int(valuation.get("n_segment") or 0),
        "blocking_flags": sorted(blocking),
        "warning_flags": sorted(warnings),
        "legal_flags": sorted(legal_flags),
        "legal_status": legal_status,
        "trust_tier": trust_tier,
    }
    builder = (
        EvidenceBuilder(question_snapshot=question)
        .resolve(listing_ref=f"radar-listing:{args.listing_id}")
        .calculate(
            blocking_flags=sorted(blocking),
            warning_flags=sorted(warnings),
            risk_level="high" if blocking else ("needs_checks" if warnings else "normal"),
        )
        .add(
            EvidenceItem(
                evidence_id=stable_evidence_id("valuation", source_ref, version),
                source_kind=SourceKind.VALUATION,
                source_ref=source_ref,
                value=value,
                as_of=as_of,
                dataset_version=version,
                sample_size=int(valuation.get("n_segment") or 0),
                provenance={"method": "deterministic_listing_and_latest_valuation_risk_flags"},
                quality_flags=sorted(all_flags),
            )
        )
    )
    for warning in sorted(warnings):
        builder.warn(warning)
    if blocking:
        builder.warn("deterministic_quality_blockers_present")
    return builder.build()

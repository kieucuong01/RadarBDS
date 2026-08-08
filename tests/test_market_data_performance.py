from contextlib import contextmanager

import pytest


def test_city_map_includes_phu_tho_under_thu_dau_mot():
    import services.market_data as market_data

    assert "Phú Thọ" in market_data.CITY_MAP["THỦ DẦU MỘT"]
    assert market_data.get_city_for_ward("Phú Thọ") == "THỦ DẦU MỘT"


def test_listing_map_summary_releases_version_connection_before_compact_query(
    monkeypatch,
):
    import services.listing_map as listing_map

    class _MapConnection:
        def __init__(self):
            self.queries = []

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            if "AS data_version" in sql:
                return _FakeCursor(row={"data_version": "v1"})
            return _FakeCursor(rows=[])

    connection = _MapConnection()
    entered = 0

    @contextmanager
    def fake_get_conn():
        nonlocal entered
        entered += 1
        yield connection

    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)
    result = listing_map.load_listing_map_summary(
        mode="signals",
        tier="guest",
        filters=listing_map.MapFilters(
            city="THỦ DẦU MỘT",
            wards=("Phú Lợi",),
            sources=("facebook",),
        ),
    )

    assert entered == 2
    assert len(connection.queries) == 2
    summary_sql = connection.queries[1][0]
    assert "listing_map_locations" in summary_sql
    assert summary_sql.count("NOT EXISTS") == 1
    assert summary_sql.count("FROM listing_publishers lp") == 2
    assert "listing_images" not in summary_sql
    assert "LEFT JOIN LATERAL" not in summary_sql
    assert result["summary"]["total"] == 0


def test_listing_map_items_releases_version_connection_before_item_query(
    monkeypatch,
):
    import services.listing_map as listing_map

    class _MapConnection:
        def __init__(self):
            self.queries = []

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            if "AS data_version" in sql:
                return _FakeCursor(row={"data_version": "v1"})
            return _FakeCursor(rows=[])

    connection = _MapConnection()
    entered = 0

    @contextmanager
    def fake_get_conn():
        nonlocal entered
        entered += 1
        yield connection

    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)
    result = listing_map.load_listing_map_items(
        mode="signals",
        tier="guest",
        filters=listing_map.MapFilters(
            city="THỦ DẦU MỘT",
            wards=("Phú Lợi",),
            sources=("facebook",),
        ),
        location_key="ward:thu-dau-mot:phu-loi",
        page=1,
        limit=20,
    )

    assert entered == 2
    assert len(connection.queries) == 2
    assert result["items"] == []


class _FakeCursor:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeReadConnection:
    def __init__(self):
        self.queries = []
        self.closed = False

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        if "COUNT(*)" in sql:
            return _FakeCursor(row=(0,))
        return _FakeCursor(rows=[])

    def close(self):
        self.closed = True
        raise AssertionError("market data reads should not close the shared connection")


def _signal_row(row_id: int = 1, **overrides):
    row = {
        "id": row_id,
        "title": f"Signal {row_id}",
        "description": "",
        "mos_pct": 20.0,
        "actual_ppm2": 10.0,
        "fair_ppm2": 12.0,
        "is_signal": 1,
        "area_m2": 100.0,
        "frontage_m": None,
        "depth_m": None,
        "price_ty": 1.0,
        "property_type": "dat_nen",
        "road_type": "duong_nhua",
        "road_width_m": None,
        "tho_cu_m2": None,
        "tho_cu_ratio": None,
        "is_hot": 0,
        "price_dropped": 0,
        "price_drop_pct": None,
        "price_first_ty": None,
        "suspicious_bait": 0,
        "duplicate_of_id": None,
        "url": "https://example.test/listing",
        "crawled_at": "2026-06-08T00:00:00",
        "posted_at": "2026-06-08T00:00:00",
        "ward": "Tan An",
        "road_tier": 2,
        "has_so": None,
        "signal_score": 20,
        "trust_tier": "candidate_signal",
        "trust_score": 0,
        "legal_status": "unverified",
        "legal_flags": "",
        "source_quality_flags": "",
        "source_quality_recheck": 0,
        "has_legal_doc_image": 0,
        "primary_local_path": None,
        "primary_img_url": None,
        "image_count": 0,
        "source": "facebook",
        "is_fresh_locked": 0,
    }
    row.update(overrides)
    return row


def test_load_signals_uses_shared_connection_scope(monkeypatch):
    import services.market_data as market_data

    conn = _FakeReadConnection()

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield conn

    def fail_fresh_connect(_db_path=None):
        raise AssertionError("load_signals opened a fresh connection")

    monkeypatch.setattr(market_data, "connect", fail_fresh_connect, raising=False)
    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn, raising=False)

    result = market_data.load_signals(None, sources=["facebook"], wards=["Tan An"], tier="admin")

    assert result["total"] == 0
    assert result["signals"] == []
    assert conn.closed is False
    assert len(conn.queries) == 1
    assert conn.queries[0][0].count("NOT EXISTS") == 0
    assert conn.queries[0][0].count("LEFT JOIN listing_publishers feed_lp") == 1
    assert conn.queries[0][0].count("LEFT JOIN source_publishers feed_sp") == 1
    assert "COUNT(*) OVER()" in conn.queries[0][0]
    assert "LEFT JOIN LATERAL" in conn.queries[0][0]
    assert "image_count" in conn.queries[0][0]


def test_load_signals_feature_flag_selects_read_model(monkeypatch):
    import services.market_data as market_data

    calls = []
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setattr(
        market_data,
        "load_signals_from_read_model",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or {
            "signals": [],
            "page": 1,
            "limit": 30,
            "has_more": False,
            "sort": "newest",
            "tier": "guest",
        },
    )

    payload = market_data.load_signals(None, include_total=False)

    assert payload["signals"] == []
    assert len(calls) == 1
    assert calls[0][1]["include_total"] is False


def test_load_signals_feature_off_keeps_legacy_query(monkeypatch):
    import services.market_data as market_data

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "0")
    called = {"legacy": 0}
    monkeypatch.setattr(
        market_data,
        "_load_signals_legacy",
        lambda *args, **kwargs: called.__setitem__(
            "legacy", called["legacy"] + 1
        )
        or {"signals": []},
    )

    market_data.load_signals(None)

    assert called["legacy"] == 1


def test_load_signals_joins_publisher_activity_once(monkeypatch):
    import services.market_data as market_data

    conn = _FakeReadConnection()

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield conn

    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn)
    market_data.load_signals(
        None,
        sources=["facebook", "guland"],
        wards=["Tan An"],
        tier="guest",
        include_total=False,
    )

    sql = conn.queries[0][0]
    assert sql.count("LEFT JOIN listing_publishers feed_lp") == 1
    assert sql.count("LEFT JOIN source_publishers feed_sp") == 1
    assert "NOT EXISTS" not in sql
    assert "SELECT CASE" not in sql


def test_load_signals_fast_page_skips_total_count_and_uses_limit_plus_one(monkeypatch):
    import services.market_data as market_data

    class _FastSignalConnection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            return _FakeCursor(rows=[_signal_row(i) for i in range(1, 4)])

        def close(self):
            self.closed = True
            raise AssertionError("load_signals should keep shared read connection open")

    conn = _FastSignalConnection()

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield conn

    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn, raising=False)

    result = market_data.load_signals(
        None,
        sources=["facebook"],
        wards=["Tan An"],
        tier="admin",
        limit=2,
        include_total=False,
    )

    sql, params = conn.queries[0]
    assert "COUNT(*) OVER()" not in sql
    assert params[-2:] == [3, 0]
    assert len(result["signals"]) == 2
    assert result["has_more"] is True
    assert "total" not in result
    assert "pages" not in result
    assert conn.closed is False


def test_signal_feed_materializes_compact_valuation_ctes():
    import services.market_data as market_data

    assert "latest_valuation AS MATERIALIZED (" in market_data.LATEST_VALUATION_CTE
    assert (
        "latest_shadow_valuation AS MATERIALIZED ("
        in market_data.LATEST_SHADOW_VALUATION_CTE
    )
    assert "vsr.*" not in market_data.LATEST_SHADOW_VALUATION_CTE
    for column in (
        "vsr.listing_id",
        "vsr.is_signal",
        "vsr.actual_ppm2",
        "vsr.fair_ppm2",
        "vsr.mos_pct",
        "vsr.signal_score",
        "vsr.trust_tier",
        "vsr.trust_score",
        "vsr.legal_status",
        "vsr.legal_flags",
        "vsr.source_quality_flags",
        "vsr.source_quality_recheck",
    ):
        assert column in market_data.LATEST_SHADOW_VALUATION_CTE


def test_related_price_drop_rows_are_materialized_once():
    from services.market_data import (
        RELATED_PRICE_DROP_CTE,
        related_price_drop_join_sql,
    )

    assert "related_price_drops AS MATERIALIZED (" in RELATED_PRICE_DROP_CTE
    assert "GROUP BY drop_child.duplicate_of_id" in RELATED_PRICE_DROP_CTE
    join_sql = related_price_drop_join_sql("l", "related_drop")
    assert "LEFT JOIN related_price_drops related_drop" in join_sql
    assert "GROUP BY" not in join_sql


def test_score_sort_does_not_emit_invalid_order_by_zero():
    import services.market_data as market_data

    score_sort = market_data._signal_sort_sql("score_desc")

    assert "ORDER BY" not in score_sort
    assert not score_sort.strip().startswith("0,")
    assert "COALESCE(v.signal_score, 0) DESC" in score_sort


def test_load_counts_uses_shared_connection_and_legacy_signal_fallback(monkeypatch):
    import services.market_data as market_data

    class _CountsConnection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            if "JOIN latest_valuation" in sql:
                return _FakeCursor(row={"signals": 3})
            return _FakeCursor(row={
                "total": 12,
                "hot": 1,
                "new_recent_days_7": 2,
                "price_drops": 4,
            })

        def close(self):
            self.closed = True
            raise AssertionError("market count reads should not close the shared connection")

    conn = _CountsConnection()
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "0")

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield conn

    def fail_fresh_connect(_db_path=None):
        raise AssertionError("load_counts opened a fresh connection")

    monkeypatch.setattr(market_data, "connect", fail_fresh_connect, raising=False)
    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn, raising=False)

    result = market_data.load_counts(None, sources=["facebook"], wards=["Tan An"])

    assert result["total"] == 12
    assert result["signals"] == 3
    assert result["new_recent_days_7"] == 2
    assert conn.closed is False
    assert len(conn.queries) == 2
    assert "FROM listings" in conn.queries[0][0]
    assert "latest_valuation" not in conn.queries[0][0]
    assert "listing_images" not in conn.queries[0][0]
    assert "LEFT JOIN LATERAL" not in conn.queries[0][0]
    assert "JOIN latest_valuation" in conn.queries[1][0]


def test_load_dashboard_summary_uses_compact_read_model(monkeypatch):
    import services.market_data as market_data

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "0")

    class _DashboardConnection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            if "JOIN latest_valuation" in sql:
                return _FakeCursor(row={"signals": 7})
            if "GROUP BY property_type" in sql:
                return _FakeCursor(rows=[
                    {"property_type": "dat_nen", "mean_ppm2": 25.5, "n_samples": 12},
                    {"property_type": "nha_dat", "mean_ppm2": 30.0, "n_samples": 8},
                    {"property_type": "nha_tro", "mean_ppm2": 18.0, "n_samples": 3},
                    {"property_type": "chung_cu", "mean_ppm2": 35.0, "n_samples": 2},
                ])
            if "SELECT DISTINCT ward" in sql:
                return _FakeCursor(rows=[("Tan An",), ("Hiep An",)])
            if "SELECT DISTINCT source" in sql:
                return _FakeCursor(rows=[("facebook",)])
            return _FakeCursor(row={
                "total": 20,
                "signals": 0,
                "hot": 2,
                "new_recent_days_7": 5,
                "price_drops": 3,
            })

        def close(self):
            self.closed = True
            raise AssertionError("dashboard summary reads should not close the shared connection")

    conn = _DashboardConnection()

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield conn

    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn, raising=False)

    result = market_data.load_dashboard_summary(
        None,
        sources=["facebook"],
        wards=["Tan An"],
        include_trend=False,
        tier="admin",
    )

    assert result["stats"]["total"] == 20
    assert result["stats"]["signals"] == 7
    assert result["market"][0]["type"] == "dat_nen"
    assert [item["label"] for item in result["market"]] == [
        "Đất",
        "Nhà đất",
        "Nhà trọ",
        "Chung cư",
    ]
    assert result["trend_data"] == {}
    assert conn.closed is False
    assert len(conn.queries) == 5
    sql_text = "\n".join(sql for sql, _ in conn.queries)
    assert "FROM listing_publishers lp" in sql_text
    assert "SELECT * FROM listings" not in sql_text
    assert "listing_images" not in sql_text
    assert "LEFT JOIN LATERAL" not in sql_text


def test_load_dashboard_summary_counts_signals_from_read_model_when_enabled(
    monkeypatch,
):
    import services.market_data as market_data

    class _DashboardConnection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            if "FROM signal_card_read_model rm" in sql:
                return _FakeCursor(row={"signals": 7})
            if "JOIN latest_valuation" in sql:
                return _FakeCursor(row={"signals": 7})
            if "GROUP BY property_type" in sql:
                return _FakeCursor(rows=[])
            if "SELECT DISTINCT ward" in sql:
                return _FakeCursor(rows=[("Tan An",)])
            if "SELECT DISTINCT source" in sql:
                return _FakeCursor(rows=[("facebook",)])
            return _FakeCursor(row={
                "total": 20,
                "signals": 0,
                "hot": 2,
                "new_recent_days_7": 5,
                "price_drops": 3,
            })

        def close(self):
            self.closed = True
            raise AssertionError(
                "dashboard summary reads should not close the shared connection"
            )

    conn = _DashboardConnection()

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield conn

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn, raising=False)

    result = market_data.load_dashboard_summary(
        None,
        sources=["facebook"],
        wards=["Tan An"],
        mos_min=10,
        date_range="3m",
        include_trend=False,
        tier="guest",
    )

    assert result["stats"]["signals"] == 7
    sql_text = "\n".join(sql for sql, _ in conn.queries)
    assert "FROM signal_card_read_model rm" in sql_text
    assert "latest_valuation" not in sql_text
    assert conn.closed is False


def test_load_counts_includes_filtered_signal_count_when_read_model_enabled(
    monkeypatch,
):
    import services.market_data as market_data
    import services.signal_read_model as signal_read_model

    class _CountsConnection:
        def __init__(self):
            self.closed = False

        def execute(self, _sql, _params=None):
            return _FakeCursor(row={
                "total": 20,
                "hot": 2,
                "new_recent_days_7": 5,
                "price_drops": 3,
            })

        def close(self):
            self.closed = True

    captured = {}
    conn = _CountsConnection()
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setattr(
        market_data,
        "_open_read_conn",
        lambda _db_path=None: conn,
    )

    def fake_count(_conn, **kwargs):
        captured.update(kwargs)
        return 7

    monkeypatch.setattr(
        signal_read_model,
        "count_signals_from_read_model",
        fake_count,
    )

    stats = market_data.load_counts(
        None,
        sources=["facebook"],
        wards=["Tan An"],
        mos_min=18,
        date_range="1m",
        tier="free",
    )

    assert stats == {
        "total": 20,
        "signals": 7,
        "hot": 2,
        "new_recent_days_7": 5,
        "price_drops": 3,
    }
    assert captured["sources"] == ["facebook"]
    assert captured["wards"] == ["Tan An"]
    assert captured["mos_min"] == 15.0
    assert captured["date_range"] == "1m"
    assert captured["tier"] == "free"
    assert conn.closed is True


def test_load_counts_uses_listing_projection_after_durable_publication(
    monkeypatch,
):
    import services.listing_feed as listing_feed
    import services.market_data as market_data
    import services.signal_read_model as signal_read_model

    class _CountsConnection:
        def __init__(self):
            self.closed = False

        def execute(self, _sql, _params=None):
            raise AssertionError("legacy listings count query should not run")

        def close(self):
            self.closed = True

    conn = _CountsConnection()
    captured = {}
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    monkeypatch.setattr(
        market_data,
        "_open_read_conn",
        lambda _db_path=None: conn,
    )

    def fake_listing_counts(_conn, **kwargs):
        captured.update(kwargs)
        return {
            "total": 20,
            "hot": 2,
            "new_recent_days_7": 5,
            "price_drops": 3,
        }

    monkeypatch.setattr(
        listing_feed,
        "load_listing_counts_from_read_model",
        fake_listing_counts,
    )
    monkeypatch.setattr(
        signal_read_model,
        "count_signals_from_read_model",
        lambda _conn, **_kwargs: 7,
    )

    stats = market_data.load_counts(
        None,
        sources=["facebook"],
        wards=["Tân An"],
        date_range="3m",
        tier="admin",
        listings_version=4,
    )

    assert stats == {
        "total": 20,
        "signals": 7,
        "hot": 2,
        "new_recent_days_7": 5,
        "price_drops": 3,
    }
    assert captured["sources"] == ["facebook"]
    assert captured["wards"] == ["Tân An"]
    assert captured["date_range"] == "3m"
    assert captured["tier"] == "admin"
    assert conn.closed is True


def test_api_counts_passes_durable_listing_version(monkeypatch):
    import app as radar_app

    captured = {}

    def fake_counts(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "total": 20,
            "signals": 7,
            "hot": 2,
            "new_recent_days_7": 5,
            "price_drops": 3,
        }

    monkeypatch.setattr(radar_app, "load_counts", fake_counts)
    monkeypatch.setattr(
        radar_app,
        "_public_dataset_versions",
        lambda _names: {"signals": 5},
    )
    monkeypatch.setattr(
        radar_app,
        "_listing_dataset_versions",
        lambda: {"listings": 4},
    )

    response = radar_app.app.test_client().get(
        "/api/counts?cache_refresh=1"
    )

    assert response.status_code == 200
    assert response.get_json()["stats"]["signals"] == 7
    assert captured["listings_version"] == 4


def test_api_dashboard_uses_fast_summary_loader(monkeypatch):
    import app as radar_app

    def fake_summary(*_args, **_kwargs):
        return {
            "stats": {"total": 20, "signals": 7, "hot": 2, "new_recent_days_7": 5, "price_drops": 3},
            "market": [],
            "trend_data": {},
            "all_wards": ["Tan An"],
            "all_sources": ["facebook"],
            "wards_by_city": {},
        }

    monkeypatch.setattr(radar_app, "load_dashboard_summary", fake_summary)
    monkeypatch.setattr(radar_app, "_get_signals_version", lambda _db_path: "test-version")

    response = radar_app.app.test_client().get("/api/dashboard?cache_refresh=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["stats"]["signals"] == 7
    assert payload["signals_version"] == "test-version"


def test_get_signals_version_uses_primary_key_dataset_counter(monkeypatch):
    import app as radar_app

    class _VersionConnection:
        def __init__(self):
            self.queries = []

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
            return _FakeCursor(rows=[{"dataset_name": "signals", "version": 17}])

    conn = _VersionConnection()

    @contextmanager
    def fake_get_conn():
        yield conn

    monkeypatch.setattr(radar_app, "get_conn", fake_get_conn)

    assert radar_app._get_signals_version("ignored") == "17"
    assert len(conn.queries) == 1
    sql, params = conn.queries[0]
    assert "FROM public_dataset_versions" in sql
    assert "MAX(" not in sql
    assert params == ("signals",)


def test_api_signals_uses_identical_bounded_values_for_cache_and_loader(monkeypatch):
    import app as radar_app

    cache_calls = []
    loader_calls = []

    def fake_load_signals(*_args, **kwargs):
        loader_calls.append(kwargs)
        return {
            "signals": [],
            "page": kwargs.get("page", 1),
            "limit": kwargs.get("limit", 30),
            "has_more": False,
            "sort": kwargs.get("sort", "newest"),
            "tier": kwargs.get("tier"),
        }

    def fake_cache(**kwargs):
        cache_calls.append(kwargs)
        return radar_app.CacheResult(kwargs["loader"](), "miss", 0.0)

    monkeypatch.setattr(radar_app, "load_signals", fake_load_signals)
    monkeypatch.setattr(radar_app, "get_or_load_public_payload", fake_cache)

    client = radar_app.app.test_client()
    query = "&".join(
        ["page=-50", "limit=900", "sort=not-real", f"q={'x' * 120}"]
        + [f"ward=W{i:03d}" for i in range(80)]
        + [f"source=s{i}" for i in range(8)]
        + [f"prop_type=p{i}" for i in range(12)]
        + [f"area_range={i}:{i + 1}" for i in range(20)]
        + [f"price_range={i}:{i + 1}" for i in range(20)]
    )
    assert client.get(f"/api/signals?{query}").status_code == 200

    cache_query = cache_calls[0]["query"]
    loader = loader_calls[0]
    assert cache_query["page"] == loader["page"] == 1
    assert cache_query["limit"] == loader["limit"] == 100
    assert cache_query["sort"] == loader["sort"] == "newest"
    assert cache_query["keyword"] == loader["keyword"] == "x" * 80
    assert cache_query["wards"] == loader["wards"]
    assert cache_query["sources"] == loader["sources"]
    assert cache_query["prop_types"] == loader["prop_types"]
    assert cache_query["area_ranges"] == loader["area_ranges"]
    assert cache_query["price_ranges"] == loader["price_ranges"]
    assert len(loader["wards"]) == 64
    assert len(loader["sources"]) <= 4
    assert len(loader["prop_types"]) <= 8
    assert len(loader["area_ranges"]) == 12
    assert len(loader["price_ranges"]) == 12


@pytest.mark.parametrize(
    ("tier", "query", "expected"),
    [
        ("guest", "", 15.0),
        ("guest", "?mos_min=10", 15.0),
        ("free", "?mos_min=10", 15.0),
        ("vip", "", 15.0),
        ("vip", "?mos_min=10", 10.0),
        ("admin", "?mos_min=12.5", 12.5),
        ("admin", "?mos_min=nan", 15.0),
    ],
)
def test_api_signals_normalizes_mos_before_cache_and_loader(
    monkeypatch, tier, query, expected
):
    import app as radar_app
    import auth.core as auth_core

    captured = {"cache": None, "loader": None}

    monkeypatch.setattr(auth_core, "current_tier", lambda: tier)
    monkeypatch.setattr(radar_app, "current_tier", lambda: tier)
    monkeypatch.setattr(
        radar_app,
        "_public_dataset_versions",
        lambda _names: {"signals": 1},
    )

    def fake_load_signals(*_args, **kwargs):
        captured["loader"] = kwargs["mos_min"]
        return {
            "signals": [],
            "page": 1,
            "limit": 30,
            "total": 0,
            "pages": 0,
        }

    def fake_cache(**kwargs):
        captured["cache"] = kwargs["query"]["mos_min"]
        return radar_app.CacheResult(kwargs["loader"](), "miss", 0.0)

    monkeypatch.setattr(radar_app, "load_signals", fake_load_signals)
    monkeypatch.setattr(radar_app, "get_or_load_public_payload", fake_cache)

    response = radar_app.app.test_client().get(f"/api/signals{query}")

    assert response.status_code == 200
    assert captured == {"cache": expected, "loader": expected}


def test_api_listings_uses_identical_bounded_values_for_cache_and_loader(monkeypatch):
    import app as radar_app
    import auth.core as auth_core

    cache_calls = []
    loader_calls = []

    def fake_load_listing_feed(*_args, **kwargs):
        loader_calls.append(kwargs)
        return {
            "listings": [],
            "page": kwargs["page"],
            "limit": kwargs["limit"],
            "total": 0,
            "pages": 0,
        }

    def fake_cache(**kwargs):
        cache_calls.append(kwargs)
        return radar_app.CacheResult(kwargs["loader"](), "miss", 0.0)

    def fail_rate_limit_db(*_args, **_kwargs):
        raise AssertionError("cached listings must not write DB rate-limit rows")

    auth_core.clear_rate_limit_cache()
    monkeypatch.setattr(auth_core, "get_conn", fail_rate_limit_db)
    monkeypatch.setattr(radar_app, "_public_cache_enabled", lambda: True)
    monkeypatch.setattr(
        radar_app,
        "get_current_dataset_versions",
        lambda names: {name: 9 for name in names},
    )
    monkeypatch.setattr(
        radar_app,
        "get_durable_dataset_versions",
        lambda names: {name: 9 for name in names},
        raising=False,
    )
    monkeypatch.setattr(radar_app, "load_listing_feed", fake_load_listing_feed)
    monkeypatch.setattr(radar_app, "get_or_load_public_payload", fake_cache)

    client = radar_app.app.test_client()
    query = "&".join(
        [
            "page=9000",
            "limit=900",
            "complete=1",
            "sort_by=price",
            "sort_dir=desc",
            "load_run=client-only",
            f"q={'x' * 120}",
        ]
        + [f"ward=W{i:03d}" for i in range(80)]
        + [f"source=s{i}" for i in range(8)]
        + [f"prop_type=p{i}" for i in range(12)]
        + [f"area_range={i}:{i + 1}" for i in range(20)]
        + [f"price_range={i}:{i + 1}" for i in range(20)]
    )
    response = client.get(f"/api/listings?{query}")

    assert response.status_code == 200
    assert response.headers["X-Radar-Dataset-Version"] == "9"
    assert cache_calls[0]["endpoint"] == "listings"
    assert cache_calls[0]["versions"] == {"listings": 9}
    cache_query = cache_calls[0]["query"]
    loader = loader_calls[0]
    assert cache_query["page"] == loader["page"] == 2000
    assert cache_query["limit"] == loader["limit"] == 100
    assert cache_query["complete"] is loader["complete_only"] is True
    assert cache_query["sort"] == "price:desc"
    assert loader["sort_by"] == "price"
    assert loader["sort_dir"] == "desc"
    assert loader["listings_version"] == 9
    assert cache_query["keyword"] == loader["keyword"] == "x" * 80
    assert cache_query["wards"] == loader["wards"]
    assert cache_query["sources"] == loader["sources"]
    assert cache_query["prop_types"] == loader["prop_types"]
    assert cache_query["area_ranges"] == loader["area_ranges"]
    assert cache_query["price_ranges"] == loader["price_ranges"]
    assert len(loader["wards"]) == 64
    assert len(loader["sources"]) <= 4
    assert len(loader["prop_types"]) <= 8
    assert len(loader["area_ranges"]) == 12
    assert len(loader["price_ranges"]) == 12


def test_api_listings_fails_closed_when_redis_version_is_stale_positive(
    monkeypatch,
):
    import app as radar_app
    import auth.core as auth_core

    cache_calls = []
    loader_calls = []

    auth_core.clear_rate_limit_cache()
    monkeypatch.setattr(radar_app, "_public_cache_enabled", lambda: True)
    monkeypatch.setattr(
        radar_app,
        "get_current_dataset_versions",
        lambda names: {name: 9 for name in names},
    )
    monkeypatch.setattr(
        radar_app,
        "get_durable_dataset_versions",
        lambda names: {name: 0 for name in names},
        raising=False,
    )

    def fake_loader(*_args, **kwargs):
        loader_calls.append(kwargs)
        return {
            "listings": [],
            "page": kwargs["page"],
            "limit": kwargs["limit"],
            "total": 0,
            "pages": 0,
        }

    def fake_cache(**kwargs):
        cache_calls.append(kwargs)
        return radar_app.CacheResult(kwargs["loader"](), "miss", 0.0)

    monkeypatch.setattr(radar_app, "load_listing_feed", fake_loader)
    monkeypatch.setattr(radar_app, "get_or_load_public_payload", fake_cache)

    response = radar_app.app.test_client().get(
        "/api/listings?page=1&limit=50"
    )

    assert response.status_code == 200
    assert response.headers["X-Radar-Dataset-Version"] == "0"
    assert cache_calls[0]["versions"] == {"listings": 0}
    assert loader_calls[0]["listings_version"] == 0


def test_load_trend_data_includes_sample_count(monkeypatch):
    import services.market_data as market_data

    class _TrendConnection:
        def __init__(self):
            self.closed = False

        def execute(self, _sql, _params=None):
            return _FakeCursor(rows=[
                {"time_key": "M-2026-05", "ward": "Ward A", "price_per_m2": 10.0},
                {"time_key": "M-2026-05", "ward": "Ward A", "price_per_m2": 12.0},
                {"time_key": "M-2026-05", "ward": "Ward A", "price_per_m2": 14.0},
            ])

        def close(self):
            self.closed = True

    conn = _TrendConnection()
    monkeypatch.setattr(market_data, "_open_read_conn", lambda _db_path=None: conn)

    result = market_data.load_trend_data(
        None,
        sources=["facebook"],
        wards=["Ward A"],
        trend_period="month",
    )

    point = result["Ward A"][0]
    assert point["median_ppm2"] == 12.0
    assert point["sample_count"] == 3
    assert conn.closed is True


def test_load_trend_data_applies_date_range_and_keyword(monkeypatch):
    import services.market_data as market_data

    class _TrendConnection:
        def __init__(self):
            self.closed = False
            self.queries = []

        def execute(self, sql, params=None):
            self.queries.append((sql, params or []))
            assert "CAST(" in sql
            assert "% road %" in params
            assert "-7 days" in params
            return _FakeCursor(rows=[
                {"time_key": "D-2026-08-07", "ward": "Ward A", "price_per_m2": 10.0},
                {"time_key": "D-2026-08-07", "ward": "Ward A", "price_per_m2": 12.0},
            ])

        def close(self):
            self.closed = True

    conn = _TrendConnection()
    monkeypatch.setattr(market_data, "_open_read_conn", lambda _db_path=None: conn)

    result = market_data.load_trend_data(
        None,
        sources=["facebook"],
        wards=["Ward A"],
        keyword="Road",
        date_range="1w",
    )

    assert result["Ward A"][0]["sample_count"] == 2
    assert conn.closed is True


def test_api_trends_passes_date_range_and_keyword_to_loader(monkeypatch):
    import app as radar_app

    captured = {}

    def fake_trend(*_args, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(radar_app, "load_trend_data", fake_trend)

    response = radar_app.app.test_client().get(
        "/api/trends?ward=Ward%20A&source=facebook&date_range=1w&q=Road"
    )

    assert response.status_code == 200
    assert captured["date_range"] == "1w"
    assert captured["keyword"] == "Road"


def test_load_market_indicators_includes_area_risk_radar(monkeypatch):
    import services.market_data as market_data

    class _IndicatorConnection:
        def __init__(self):
            self.closed = False

        def execute(self, sql, params=None):
            if "SUM(has_price_drop)" in sql:
                return _FakeCursor(rows=[
                    {"ward": "Ward A", "total_count": 10, "distress_count": 4},
                    {"ward": "Ward B", "total_count": 12, "distress_count": 1},
                ])
            if "strftime('%Y-%m'" in sql:
                current_month = market_data.date.today().strftime("%Y-%m")
                return _FakeCursor(rows=[
                    {"ward": "Ward A", "month_key": current_month, "new_count": 18},
                    {"ward": "Ward B", "month_key": current_month, "new_count": 4},
                ])
            if "risk_deal_rows" in sql:
                return _FakeCursor(rows=[
                    {"ward": "Ward A", "mos_pct": 28.0, "is_signal": 1},
                    {"ward": "Ward A", "mos_pct": 22.0, "is_signal": 1},
                    {"ward": "Ward B", "mos_pct": 18.0, "is_signal": 1},
                    {"ward": "Ward B", "mos_pct": 0.0, "is_signal": 0},
                ])
            return _FakeCursor(rows=[])

        def close(self):
            self.closed = True

    conn = _IndicatorConnection()
    monkeypatch.setattr(market_data, "_open_read_conn", lambda _db_path=None: conn)

    result = market_data.load_market_indicators(
        None,
        sources=["facebook"],
        wards=["Ward A", "Ward B"],
    )

    radar = result["area_risk_radar"]
    assert radar[0]["ward"] == "Ward A"
    assert radar[0]["risk_score"] > radar[1]["risk_score"]
    assert radar[0]["distress_ratio_pct"] == 40.0
    assert radar[0]["median_mos"] == 25.0
    assert radar[0]["deal_count"] == 2
    assert radar[0]["verdict_key"] == "selloff"
    assert result["summary"]["area_risk_hotspots"] == 1
    assert conn.closed is True


def test_load_market_indicators_applies_date_keyword_and_mos_scope(monkeypatch):
    import services.market_data as market_data

    class _IndicatorConnection:
        def __init__(self):
            self.closed = False
            self.queries = []

        def execute(self, sql, params=None):
            params = params or []
            self.queries.append((sql, params))
            assert "% road %" in params
            assert "-1 months" in params
            if "risk_deal_rows" in sql:
                assert 15.0 in params
                assert params[0] == 15.0
                return _FakeCursor(rows=[
                    {"ward": "Ward A", "mos_pct": 18.0, "is_signal": 1},
                ])
            if "SUM(has_price_drop)" in sql:
                return _FakeCursor(rows=[
                    {"ward": "Ward A", "total_count": 8, "distress_count": 2},
                ])
            if "strftime('%Y-%m'" in sql:
                return _FakeCursor(rows=[])
            return _FakeCursor(rows=[])

        def close(self):
            self.closed = True

    conn = _IndicatorConnection()
    monkeypatch.setattr(market_data, "_open_read_conn", lambda _db_path=None: conn)

    result = market_data.load_market_indicators(
        None,
        sources=["facebook"],
        wards=["Ward A"],
        keyword="Road",
        date_range="1m",
        mos_min=10,
        tier="guest",
    )

    assert result["distress_ratio"][0]["sample_confidence"] == "medium"
    assert result["summary"]["date_range"] == "1m"
    assert result["summary"]["mos_min"] == 15.0
    assert conn.closed is True


def test_api_heatmap_delegates_to_market_opportunity_loader_with_normalized_scope(
    monkeypatch,
):
    import app as radar_app
    import auth.core as auth_core

    captured = {}

    monkeypatch.setattr(auth_core, "current_tier", lambda: "guest")
    monkeypatch.setattr(radar_app, "current_tier", lambda: "guest")

    def fake_loader(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return {
            "rows": [],
            "summary": {"total_wards": 0, "total_deals": 0},
            "applied_filters": {},
            "as_of": "2026-08-07T00:00:00",
        }

    def fail_fresh_connect(_db_path=None):
        raise AssertionError("api_heatmap should not open a route-owned connection")

    monkeypatch.setattr(radar_app, "load_market_opportunities", fake_loader)
    monkeypatch.setattr(radar_app, "connect", fail_fresh_connect, raising=False)

    response = radar_app.app.test_client().get(
        "/api/heatmap?"
        "ward=Ward%20A&source=facebook&prop_type=dat_nen"
        "&mos_min=10&date_range=1w&q=Ring%20Road"
        "&area_range=80:120&price_range=1:3"
    )

    assert response.status_code == 200
    assert captured["wards"] == ["Ward A"]
    assert captured["sources"] == ["facebook"]
    assert captured["prop_types"] == ["dat_nen"]
    assert captured["mos_min"] == 15.0
    assert captured["tier"] == "guest"
    assert captured["date_range"] == "1w"
    assert captured["keyword"] == "Ring Road"
    assert captured["area_ranges"] == [(80.0, 120.0)]
    assert captured["price_ranges"] == [(1.0, 3.0)]


def test_load_market_opportunities_uses_shared_scope_and_global_totals(monkeypatch):
    import services.market_data as market_data

    class _OpportunityConnection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, sql, params=None):
            self.queries.append((sql, params or []))
            assert "CAST(" in sql
            assert "% ring %" in params
            assert "% road %" in params
            assert "-1 months" in params
            assert 15.0 in params
            assert params[-1] == 15.0
            assert "filtered_listings AS MATERIALIZED" in sql
            assert "FROM filtered_listings l" in sql
            assert "WHERE vr.listing_id = l.id" in sql
            assert "WHERE vsr.listing_id = l.id" in sql
            return _FakeCursor(rows=[
                {
                    "ward": "Ward A",
                    "total_count": 3,
                    "deal_count": 2,
                    "median_mos": 25.0,
                    "avg_signal_mos": 25.0,
                    "signal_rate": 66.7,
                    "avg_price": 11.0,
                    "median_price": 11.0,
                    "avg_price_ty": 1.1,
                    "avg_fair_ty": 1.4,
                },
                {
                    "ward": "Ward B",
                    "total_count": 4,
                    "deal_count": 3,
                    "median_mos": 18.0,
                    "avg_signal_mos": 19.0,
                    "signal_rate": 75.0,
                    "avg_price": 9.0,
                    "median_price": 9.0,
                    "avg_price_ty": 0.9,
                    "avg_fair_ty": 1.1,
                },
                {
                    "ward": "Ward C",
                    "total_count": 2,
                    "deal_count": 0,
                    "median_mos": 0.0,
                    "avg_signal_mos": 0.0,
                    "signal_rate": 0.0,
                    "avg_price": 8.0,
                    "median_price": 8.0,
                    "avg_price_ty": 0.8,
                    "avg_fair_ty": 0.0,
                },
            ])

        def close(self):
            self.closed = True
            raise AssertionError("market opportunity loader should keep shared read connection open")

    conn = _OpportunityConnection()

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield conn

    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn, raising=False)

    result = market_data.load_market_opportunities(
        None,
        sources=["facebook"],
        wards=["Ward A", "Ward B"],
        prop_types=["dat_nen"],
        mos_min=10,
        tier="guest",
        date_range="1m",
        keyword="Ring Road",
    )

    assert result["summary"]["total_wards"] == 3
    assert result["summary"]["eligible_wards"] == 2
    assert result["summary"]["total_deals"] == 5
    assert result["summary"]["shown_wards"] == 2
    assert [row["ward"] for row in result["rows"]] == ["Ward A", "Ward B"]
    assert result["rows"][0]["rank_label"] == "Bien an toan tot"
    assert result["rows"][1]["rank_label"] == "Nhieu deal nhat"
    assert result["applied_filters"]["mos_min"] == 15.0
    assert result["applied_filters"]["date_range"] == "1m"
    assert conn.closed is False


def test_load_market_opportunities_uses_indexed_lateral_latest_rows(monkeypatch):
    import services.market_data as market_data

    captured = {}

    class _CaptureConnection:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = list(params or [])
            return _FakeCursor(rows=[])

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield _CaptureConnection()

    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn)

    result = market_data.load_market_opportunities(
        None,
        sources=["facebook"],
        wards=["Ward A"],
        mos_min=15,
        tier="guest",
        date_range="3m",
    )

    sql = captured["sql"]
    assert result["rows"] == []
    assert "filtered_listings AS MATERIALIZED" in sql
    assert "latest_valuation AS MATERIALIZED" not in sql
    assert "latest_shadow_valuation AS MATERIALIZED" not in sql
    assert sql.count("LEFT JOIN LATERAL") == 2
    assert "FROM valuation_results vr" in sql
    assert "WHERE vr.listing_id = l.id" in sql
    assert "ORDER BY vr.computed_at DESC, vr.id DESC" in sql
    assert "FROM valuation_shadow_results vsr" in sql
    assert "WHERE vsr.listing_id = l.id" in sql
    assert "ORDER BY vsr.computed_at DESC, vsr.id DESC" in sql
    assert sql.count("LIMIT 1") == 2


def test_schema_defines_feed_performance_indexes():
    from db.schema import SCHEMA_SQL

    assert "idx_valuation_signal_trust_score" in SCHEMA_SQL
    assert "trust_score DESC" in SCHEMA_SQL
    assert "signal_score DESC" in SCHEMA_SQL
    assert "idx_images_listing_legal_order" in SCHEMA_SQL


def test_valuation_results_create_table_contains_signal_score_for_clean_db_index():
    import re

    from db.schema import SCHEMA_SQL

    match = re.search(
        r"CREATE TABLE IF NOT EXISTS valuation_results \((.*?)\);\s*CREATE INDEX",
        SCHEMA_SQL,
        flags=re.S,
    )

    assert match is not None
    assert "signal_score" in match.group(1)


def test_dashboard_guest_rate_limit_uses_memory_without_db(monkeypatch):
    from flask import Flask
    import auth.core as auth

    auth.clear_rate_limit_cache()
    db_calls = {"n": 0}

    def fail_get_conn():
        db_calls["n"] += 1
        raise AssertionError("dashboard guest rate limit should not hit the database")

    monkeypatch.setattr(auth, "get_conn", fail_get_conn)

    flask_app = Flask(__name__)

    @auth.rate_limit("dashboard", limits={"guest": 2})
    def view():
        return {"ok": True}

    with flask_app.test_request_context("/", environ_base={"REMOTE_ADDR": "1.2.3.4"}):
        assert view() == {"ok": True}
        assert view() == {"ok": True}
        limited = view()

    assert db_calls["n"] == 0
    assert limited[1] == 429

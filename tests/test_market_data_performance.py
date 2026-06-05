from contextlib import contextmanager


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
    assert "COUNT(*) OVER()" in conn.queries[0][0]
    assert "LEFT JOIN LATERAL" in conn.queries[0][0]
    assert "image_count" in conn.queries[0][0]


def test_load_counts_uses_compact_shared_connection_scope(monkeypatch):
    import services.market_data as market_data

    class _CountsConnection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, sql, params=None):
            self.queries.append((sql, params))
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

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield conn

    def fail_fresh_connect(_db_path=None):
        raise AssertionError("load_counts opened a fresh connection")

    monkeypatch.setattr(market_data, "connect", fail_fresh_connect, raising=False)
    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn, raising=False)

    result = market_data.load_counts(None, sources=["facebook"], wards=["Tan An"])

    assert result["total"] == 12
    assert result["new_recent_days_7"] == 2
    assert conn.closed is False
    assert len(conn.queries) == 1
    assert "FROM listings" in conn.queries[0][0]
    assert "latest_valuation" not in conn.queries[0][0]
    assert "listing_images" not in conn.queries[0][0]
    assert "LEFT JOIN LATERAL" not in conn.queries[0][0]


def test_load_dashboard_summary_uses_compact_read_model(monkeypatch):
    import services.market_data as market_data

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
                    {"property_type": "dat_vuon", "mean_ppm2": 12.0, "n_samples": 4},
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
        "Đất nền",
        "Đất vườn",
        "Nhà đất",
        "Nhà trọ",
        "Chung cư",
    ]
    assert result["trend_data"] == {}
    assert conn.closed is False
    assert len(conn.queries) == 5
    sql_text = "\n".join(sql for sql, _ in conn.queries)
    assert "SELECT * FROM listings" not in sql_text
    assert "listing_images" not in sql_text
    assert "LEFT JOIN LATERAL" not in sql_text


def test_api_dashboard_uses_fast_summary_loader(monkeypatch):
    import app as radar_app

    radar_app.clear_dashboard_cache()

    def fake_summary(*_args, **_kwargs):
        return {
            "stats": {"total": 20, "signals": 7, "hot": 2, "new_recent_days_7": 5, "price_drops": 3},
            "market": [],
            "trend_data": {},
            "all_wards": ["Tan An"],
            "all_sources": ["facebook"],
            "wards_by_city": {},
        }

    def fail_load_data(*_args, **_kwargs):
        raise AssertionError("api_dashboard should use load_dashboard_summary, not load_data")

    monkeypatch.setattr(radar_app, "load_dashboard_summary", fake_summary)
    monkeypatch.setattr(radar_app, "load_data", fail_load_data)
    monkeypatch.setattr(radar_app, "_get_signals_version", lambda _db_path: "test-version")

    response = radar_app.app.test_client().get("/api/dashboard?cache_refresh=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["stats"]["signals"] == 7
    assert payload["signals_version"] == "test-version"


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


def test_dashboard_cache_reuses_loader_until_ttl_expires():
    import app as radar_app

    radar_app.clear_dashboard_cache()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return {"stats": {"calls": calls["n"]}}

    first = radar_app._cached_dashboard_payload(("same", "filters"), loader, now=100.0, ttl_seconds=30)
    second = radar_app._cached_dashboard_payload(("same", "filters"), loader, now=120.0, ttl_seconds=30)
    expired = radar_app._cached_dashboard_payload(("same", "filters"), loader, now=131.0, ttl_seconds=30)

    assert first == {"stats": {"calls": 1}}
    assert second == first
    assert expired == {"stats": {"calls": 2}}
    assert calls["n"] == 2


def test_dashboard_cache_force_refresh_reloads_even_inside_ttl():
    import app as radar_app

    radar_app.clear_dashboard_cache()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return {"stats": {"calls": calls["n"]}}

    first = radar_app._cached_dashboard_payload(("same", "filters"), loader, now=100.0, ttl_seconds=120)
    refreshed = radar_app._cached_dashboard_payload(
        ("same", "filters"),
        loader,
        now=101.0,
        ttl_seconds=120,
        force_refresh=True,
    )

    assert first == {"stats": {"calls": 1}}
    assert refreshed == {"stats": {"calls": 2}}
    assert calls["n"] == 2


def test_schema_defines_feed_performance_indexes():
    from db.schema import SCHEMA_SQL

    assert "idx_valuation_signal_trust_score" in SCHEMA_SQL
    assert "trust_score DESC" in SCHEMA_SQL
    assert "signal_score DESC" in SCHEMA_SQL
    assert "idx_images_listing_legal_order" in SCHEMA_SQL


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

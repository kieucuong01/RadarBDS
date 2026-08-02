from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from services.listing_map import MapFilters


class _Cursor:
    def __init__(self, *, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class _MapConnection:
    def __init__(self):
        self.version = "v1"
        self.queries = []
        self.summary_calls = 0
        self.item_calls = 0

    def execute(self, sql, params=None):
        self.queries.append((sql, list(params or [])))
        if "FROM public_dataset_versions" in sql:
            version = int(self.version.removeprefix("v"))
            return _Cursor(rows=[
                {"dataset_name": "signals", "version": version},
                {"dataset_name": "listings", "version": version},
            ])
        if "AS data_version" in sql:
            return _Cursor(row={"data_version": self.version})
        if "GROUP BY ml.location_key" in sql:
            self.summary_calls += 1
            common = {
                "total_count": 6,
                "mapped_count": 4,
                "exact_count": 1,
                "road_count": 1,
                "landmark_count": 1,
                "nearby_count": 0,
                "ward_count": 1,
            }
            return _Cursor(rows=[
                {
                    **common,
                    "location_key": None,
                    "lat": None,
                    "lng": None,
                    "location_precision": None,
                    "location_label": None,
                    "accuracy_radius_m": None,
                    "relation": None,
                    "listing_count": 2,
                    "best_mos": None,
                },
                {
                    **common,
                    "location_key": "exact:1",
                    "lat": 10.99,
                    "lng": 106.67,
                    "location_precision": "exact",
                    "accuracy_radius_m": 0,
                    "relation": "on",
                    "location_label": "Vị trí chính xác từ tin rao",
                    "listing_count": 1,
                    "best_mos": 31.0,
                },
                {
                    **common,
                    "location_key": "road:thu-dau-mot:phu-loi:dx-43",
                    "lat": 10.981,
                    "lng": 106.689,
                    "location_precision": "road",
                    "accuracy_radius_m": 90,
                    "relation": "on",
                    "location_label": "Theo tên đường ĐX 43, Phú Lợi",
                    "listing_count": 1,
                    "best_mos": 24.0,
                },
                {
                    **common,
                    "location_key": "landmark:thu-dau-mot:phu-loi:tdc-a",
                    "lat": 10.982,
                    "lng": 106.690,
                    "location_precision": "landmark",
                    "location_label": "Theo địa danh TĐC A",
                    "accuracy_radius_m": 140,
                    "relation": "at",
                    "listing_count": 1,
                    "best_mos": 20.0,
                },
                {
                    **common,
                    "location_key": "ward:thu-dau-mot:phu-loi",
                    "lat": 10.984,
                    "lng": 106.684,
                    "location_precision": "ward",
                    "location_label": "Theo trung tâm Phú Lợi",
                    "accuracy_radius_m": None,
                    "relation": "",
                    "listing_count": 1,
                    "best_mos": 18.0,
                },
            ])
        if "ml.location_key = ?" in sql:
            self.item_calls += 1
            return _Cursor(rows=[{
                "total_count": 1,
                "id": 8,
                "title": "Lô đất Phú Lợi, gọi 0909 123 456",
                "price_ty": 1.8,
                "area_m2": 100,
                "property_type": "dat_nen",
                "ward": "Phú Lợi",
                "road_name": "ĐX 43",
                "posted_at": "2026-07-28T00:00:00",
                "crawled_at": "2026-07-29T00:00:00",
                "source": "facebook",
                "mos_pct": 22.5,
                "is_signal": 1,
                "primary_local_path": None,
                "primary_img_url": None,
            }])
        raise AssertionError(sql)


def _filters(**overrides):
    values = {
        "city": "THỦ DẦU MỘT",
        "wards": ("Phú Lợi",),
        "sources": ("facebook",),
        "prop_types": (),
        "only_drops": False,
        "mos_min": 10,
        "area_min": 0,
        "area_max": 0,
        "price_min": 0,
        "price_max": 0,
        "area_ranges": (),
        "price_ranges": (),
        "keyword": "",
        "date_range": "3m",
        "complete_only": False,
    }
    values.update(overrides)
    return MapFilters(**values)


def test_summary_invariants_and_compact_query(monkeypatch):
    import services.listing_map as listing_map

    connection = _MapConnection()

    @contextmanager
    def fake_get_conn():
        yield connection

    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)

    payload = listing_map.load_listing_map_summary(
        mode="signals",
        tier="guest",
        filters=_filters(),
    )

    summary = payload["summary"]
    assert summary["mapped"] + summary["unmapped_count"] == summary["total"]
    assert (
        summary["exact_count"]
        + summary["road_count"]
        + summary["landmark_count"]
        + summary["ward_count"]
        == summary["mapped"]
    )
    assert summary["nearby_count"] == 0
    assert sum(group["listing_count"] for group in payload["locations"]) == 4
    assert payload["locations"][0]["listing_count"] == 1
    assert {group["precision"] for group in payload["locations"]} <= {
        "exact",
        "road",
        "landmark",
        "ward",
    }
    summary_sql = next(
        sql for sql, _params in connection.queries
        if "GROUP BY ml.location_key" in sql
    ).lower()
    group_by_sql = summary_sql.split("group by", 1)[1].split(
        "order by",
        1,
    )[0]
    assert "ml.relation" not in group_by_sql
    for forbidden in (
        "description",
        "contact_phone",
        "seller_name",
        "l.url",
        "image_urls",
        "evidence_text",
        "source_url",
        "where ml.listing_id is not null",
    ):
        assert forbidden not in summary_sql
    assert "sum(count(ml.listing_id)) over()" in summary_sql


def test_signal_summary_uses_read_model_and_dataset_version(monkeypatch):
    import services.listing_map as listing_map

    connection = _MapConnection()

    @contextmanager
    def fake_get_conn():
        yield connection

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)

    listing_map.load_listing_map_summary(
        mode="signals",
        tier="guest",
        filters=_filters(),
    )

    sql_text = "\n".join(sql for sql, _params in connection.queries)
    summary_sql = next(
        sql for sql, _params in connection.queries
        if "GROUP BY ml.location_key" in sql
    )
    assert "FROM public_dataset_versions" in sql_text
    assert "FROM signal_card_read_model rm" in summary_sql
    assert "latest_valuation" not in summary_sql
    assert "latest_shadow_valuation" not in summary_sql
    assert "rm.is_actionable" in summary_sql


def test_all_map_uses_listing_read_model_and_durable_version(monkeypatch):
    import services.listing_map as listing_map

    connection = _MapConnection()

    @contextmanager
    def fake_get_conn():
        yield connection

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)

    listing_map.load_listing_map_summary(
        mode="all",
        tier="guest",
        filters=_filters(complete_only=True),
    )
    listing_map.load_listing_map_items(
        mode="all",
        tier="guest",
        filters=_filters(complete_only=True),
        location_key="road:thu-dau-mot:phu-loi:dx-43",
        page=1,
        limit=20,
    )

    sql_text = "\n".join(sql for sql, _params in connection.queries)
    summary_sql = next(
        sql for sql, _params in connection.queries
        if "GROUP BY ml.location_key" in sql
    )
    item_sql = next(
        sql for sql, _params in connection.queries
        if "ml.location_key = ?" in sql
    )
    assert "FROM public_dataset_versions" in sql_text
    assert "FROM signal_card_read_model rm" in summary_sql
    assert "latest_valuation" not in summary_sql
    assert "latest_shadow_valuation" not in summary_sql
    assert "rm.listing_is_signal" in summary_sql
    assert "NULLIF(TRIM(COALESCE(rm.ward, '')), '') IS NOT NULL" in summary_sql
    assert "LEFT JOIN LATERAL" not in item_sql
    assert "primary_img.id = f.primary_image_id" in item_sql


def test_all_map_rolls_back_when_listing_read_model_flag_is_disabled(monkeypatch):
    import services.listing_map as listing_map

    connection = _MapConnection()

    @contextmanager
    def fake_get_conn():
        yield connection

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "0")
    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)

    listing_map.load_listing_map_summary(
        mode="all", tier="guest", filters=_filters()
    )

    summary_sql = next(
        sql for sql, _params in connection.queries
        if "GROUP BY ml.location_key" in sql
    )
    assert "latest_valuation AS MATERIALIZED" in summary_sql
    assert "FROM signal_card_read_model rm" not in summary_sql


def test_all_map_rolls_back_when_durable_listing_version_is_zero(monkeypatch):
    import services.listing_map as listing_map

    connection = _MapConnection()
    connection.version = "v0"

    @contextmanager
    def fake_get_conn():
        yield connection

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)

    listing_map.load_listing_map_items(
        mode="all",
        tier="guest",
        filters=_filters(),
        location_key="road:thu-dau-mot:phu-loi:dx-43",
        page=1,
        limit=20,
    )

    item_sql = next(
        sql for sql, _params in connection.queries
        if "ml.location_key = ?" in sql
    )
    assert "latest_valuation AS MATERIALIZED" in item_sql
    assert "FROM signal_card_read_model rm" not in item_sql


def test_all_map_summary_single_flights_same_cache_key(monkeypatch):
    import services.listing_map as listing_map

    class _SlowMapConnection(_MapConnection):
        def execute(self, sql, params=None):
            if "GROUP BY ml.location_key" in sql:
                time.sleep(0.05)
            return super().execute(sql, params)

    connection = _SlowMapConnection()

    @contextmanager
    def fake_get_conn():
        yield connection

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)

    def load_summary(_index):
        return listing_map.load_listing_map_summary(
            mode="all",
            tier="guest",
            filters=_filters(),
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(load_summary, range(8)))

    assert connection.summary_calls == 1
    assert all(result == results[0] for result in results)


def test_all_map_summary_waiters_release_connections_before_slow_query(
    monkeypatch,
):
    import services.listing_map as listing_map

    worker_count = 8
    context_barrier = threading.Barrier(worker_count)
    state_lock = threading.Lock()
    pool_state = {"active": 0, "active_during_heavy": []}

    class _BoundedMapConnection(_MapConnection):
        def execute(self, sql, params=None):
            if "AS data_version" in sql:
                context_barrier.wait(timeout=2)
            if "GROUP BY ml.location_key" in sql:
                time.sleep(0.03)
                with state_lock:
                    pool_state["active_during_heavy"].append(
                        pool_state["active"]
                    )
                time.sleep(0.05)
            return super().execute(sql, params)

    connection = _BoundedMapConnection()

    @contextmanager
    def bounded_get_conn():
        with state_lock:
            pool_state["active"] += 1
        try:
            yield connection
        finally:
            with state_lock:
                pool_state["active"] -= 1

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", bounded_get_conn)

    def load_summary(_index):
        return listing_map.load_listing_map_summary(
            mode="all", tier="guest", filters=_filters()
        )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(load_summary, range(worker_count)))

    assert connection.summary_calls == 1
    assert pool_state["active_during_heavy"] == [1]
    assert all(result == results[0] for result in results)


def test_all_map_items_single_flight_same_cache_key(monkeypatch):
    import services.listing_map as listing_map

    class _SlowMapConnection(_MapConnection):
        def execute(self, sql, params=None):
            if "ml.location_key = ?" in sql:
                time.sleep(0.05)
            return super().execute(sql, params)

    connection = _SlowMapConnection()

    @contextmanager
    def fake_get_conn():
        yield connection

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)

    def load_items(_index):
        return listing_map.load_listing_map_items(
            mode="all",
            tier="guest",
            filters=_filters(),
            location_key="road:thu-dau-mot:phu-loi:dx-43",
            page=1,
            limit=20,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(load_items, range(8)))

    assert connection.item_calls == 1
    assert all(result == results[0] for result in results)


def test_summary_cache_uses_data_version_tier_mode_and_filters(monkeypatch):
    import services.listing_map as listing_map

    connection = _MapConnection()

    @contextmanager
    def fake_get_conn():
        yield connection

    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)

    first = listing_map.load_listing_map_summary(
        mode="signals", tier="guest", filters=_filters()
    )
    second = listing_map.load_listing_map_summary(
        mode="signals", tier="guest", filters=_filters()
    )
    assert first == second
    assert first is not second
    assert connection.summary_calls == 1

    connection.version = "v2"
    listing_map.load_listing_map_summary(
        mode="signals", tier="guest", filters=_filters()
    )
    listing_map.load_listing_map_summary(
        mode="all", tier="guest", filters=_filters()
    )
    listing_map.load_listing_map_summary(
        mode="all", tier="free", filters=_filters(keyword="DX 43")
    )
    assert connection.summary_calls == 4


def test_group_items_are_bounded_and_allowlisted(monkeypatch):
    import services.listing_map as listing_map

    connection = _MapConnection()

    @contextmanager
    def fake_get_conn():
        yield connection

    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)

    payload = listing_map.load_listing_map_items(
        mode="signals",
        tier="guest",
        filters=_filters(),
        location_key="road:thu-dau-mot:phu-loi:dx-43",
        page=1,
        limit=20,
    )

    assert payload["total"] == 1
    assert payload["items"][0]["id"] == 8
    assert payload["items"][0]["prop_type_label"]
    assert "0909 123 456" not in payload["items"][0]["title"]
    assert set(payload["items"][0]).isdisjoint(
        {"url", "phone", "contact_phone", "description", "seller_name"}
    )
    item_sql = next(
        sql for sql, _params in connection.queries
        if "ml.location_key = ?" in sql
    )
    assert "latest_valuation AS MATERIALIZED" in item_sql
    assert "LIMIT ? OFFSET ?" in item_sql

    admin_payload = listing_map.load_listing_map_items(
        mode="signals",
        tier="admin",
        filters=_filters(),
        location_key="road:thu-dau-mot:phu-loi:dx-43",
        page=1,
        limit=20,
    )
    assert admin_payload["items"][0]["title"].endswith("0909 123 456")


def test_signal_group_items_reuse_read_model_primary_image(monkeypatch):
    import services.listing_map as listing_map

    connection = _MapConnection()

    @contextmanager
    def fake_get_conn():
        yield connection

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    listing_map.clear_listing_map_cache()
    monkeypatch.setattr(listing_map, "get_conn", fake_get_conn)

    listing_map.load_listing_map_items(
        mode="signals",
        tier="guest",
        filters=_filters(),
        location_key="road:thu-dau-mot:phu-loi:dx-43",
        page=1,
        limit=20,
    )

    item_sql = next(
        sql for sql, _params in connection.queries
        if "ml.location_key = ?" in sql
    )
    assert "latest_valuation" not in item_sql
    assert "LEFT JOIN LATERAL" not in item_sql
    assert "primary_img.id = f.primary_image_id" in item_sql

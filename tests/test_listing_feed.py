import json

import pytest


def _listing_row(listing_id=7, *, total_count=1):
    return {
        "id": listing_id,
        "listing_id": listing_id,
        "total_count": total_count,
        "title": "Lô đất DX 43",
        "description": "Mặt tiền đường rộng 6m",
        "source": "facebook",
        "source_status": "active",
        "url": "https://example.test/listing/7",
        "ward": "Tan An",
        "property_type": "dat_nen",
        "area_m2": 100.0,
        "frontage_m": 5.0,
        "depth_m": 20.0,
        "price_ty": 2.0,
        "listing_price_per_m2": 20.0,
        "fair_ppm2": 25.0,
        "fair_ppm2_old": 25.0,
        "fair_ppm2_new": 24.0,
        "mos_pct": 20.0,
        "mos_pct_old": 20.0,
        "mos_pct_new": 16.7,
        "listing_is_signal": True,
        "actionable_signal": True,
        "is_hot": False,
        "possibly_duplicate": False,
        "price_dropped": False,
        "price_drop_pct": None,
        "price_first_ty": None,
        "suspicious_bait": False,
        "duplicate_of_id": None,
        "activity_at": "2026-08-01T00:00:00",
        "crawled_at": "2026-08-01T00:00:00",
        "posted_at": "2026-08-01T00:00:00",
        "first_seen_at": "2026-08-01T00:00:00",
        "price_updated_at": None,
        "road_name": "DX 43",
        "road_type": "named_road",
        "road_width_m": 6.0,
        "road_tier": 1,
        "tho_cu_m2": 100.0,
        "tho_cu_ratio": 1.0,
        "publisher_visible_public": True,
        "publisher_rank": 0,
        "is_fresh_locked": False,
    }


class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class RecordingListingConnection:
    def __init__(self, *, candidate_rows=None, image_rows=None):
        self.candidate_rows = list(candidate_rows or [])
        self.image_rows = list(image_rows or [])
        self.queries = []
        self.closed = False

    def execute(self, sql, params=None):
        bound = list(params) if isinstance(params, list) else params
        self.queries.append((sql, bound))
        if "FROM listing_images" in sql:
            return _Cursor(self.image_rows)
        if "WITH filtered AS MATERIALIZED" in sql:
            return _Cursor(self.candidate_rows)
        return _Cursor([])

    def close(self):
        self.closed = True


def test_listing_read_model_gate_requires_both_flags_and_positive_version(
    monkeypatch,
):
    from services.listing_feed import listing_read_model_enabled

    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    assert listing_read_model_enabled(1) is True
    assert listing_read_model_enabled(0) is False

    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "0")
    assert listing_read_model_enabled(1) is False

    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "0")
    assert listing_read_model_enabled(1) is False


def test_read_model_listing_query_is_bounded_and_has_no_valuation_cte(
    monkeypatch,
):
    from services import listing_feed

    conn = RecordingListingConnection(candidate_rows=[], image_rows=[])
    monkeypatch.setattr(
        listing_feed, "_open_read_conn", lambda _db_path=None: conn
    )
    monkeypatch.setenv("RADAR_SIGNAL_QUERY_TIMEOUT_MS", "2400")

    payload = listing_feed.load_listings_from_read_model(
        None,
        sources=["facebook"],
        wards=["Tan An"],
        page=99999,
        limit=999,
        tier="guest",
        date_range="3m",
    )

    assert conn.queries[0] == (
        "SELECT set_config('statement_timeout', ?, true)",
        ("2400ms",),
    )
    page_sql, page_params = conn.queries[1]
    assert "FROM signal_card_read_model rm" in page_sql
    assert "SELECT COUNT(*) AS total_count FROM filtered" in page_sql
    assert "LEFT JOIN page_ids" in page_sql
    assert "latest_valuation" not in page_sql.lower()
    assert "valuation_results" not in page_sql.lower()
    assert page_params[-2:] == [100, 199900]
    assert payload["page"] == 2000
    assert payload["limit"] == 100
    assert conn.closed is True


def test_read_model_enriches_only_selected_ids_in_legal_image_order(
    monkeypatch,
):
    from services import listing_feed

    conn = RecordingListingConnection(
        candidate_rows=[_listing_row()],
        image_rows=[
            {
                "listing_id": 7,
                "local_path": "data/images/so.jpg",
                "img_url": None,
            },
            {
                "listing_id": 7,
                "local_path": "data/images/land.jpg",
                "img_url": None,
            },
        ],
    )
    monkeypatch.setattr(
        listing_feed, "_open_read_conn", lambda _db_path=None: conn
    )
    monkeypatch.setattr(
        listing_feed,
        "resolve_image_url",
        lambda local, remote, prefer_thumb=False: local or remote,
    )

    payload = listing_feed.load_listings_from_read_model(
        None, tier="admin"
    )

    image_sql, image_params = conn.queries[2]
    assert "WHERE listing_id IN (?)" in image_sql
    assert "ORDER BY listing_id" in image_sql
    assert image_params == [7]
    assert payload["listings"][0]["imgs"] == [
        "data/images/so.jpg",
        "data/images/land.jpg",
    ]
    assert payload["listings"][0]["is_signal"] is True
    assert payload["listings"][0]["price_per_m2"] == 20.0


def test_out_of_range_page_keeps_exact_total_without_image_query(monkeypatch):
    from services import listing_feed

    conn = RecordingListingConnection(
        candidate_rows=[{"id": None, "total_count": 137}],
        image_rows=[],
    )
    monkeypatch.setattr(
        listing_feed, "_open_read_conn", lambda _db_path=None: conn
    )

    payload = listing_feed.load_listings_from_read_model(
        None, page=20, limit=50, tier="guest"
    )

    assert payload["listings"] == []
    assert payload["total"] == 137
    assert payload["pages"] == 3
    assert payload["has_more"] is False
    assert len(conn.queries) == 2


def test_listing_filters_preserve_public_complete_and_drop_semantics():
    from services.listing_feed import build_listing_read_model_filters

    normal_sql, normal_params = build_listing_read_model_filters(
        sources=["facebook"],
        wards=["Tan An"],
        prop_types=["dat_nen"],
        complete_only=True,
        area_min=60,
        area_max=200,
        price_min=1,
        price_max=5,
        date_range="3m",
    )
    drop_sql, _ = build_listing_read_model_filters(
        only_drops=True,
        allow_high_activity=True,
    )

    assert "rm.publisher_visible_public" in normal_sql
    assert "NOT rm.possibly_duplicate" in normal_sql
    assert "rm.is_actionable" not in normal_sql
    assert "COALESCE(rm.price_ty, 0) > 0" in normal_sql
    assert "COALESCE(rm.area_m2, 0) > 0" in normal_sql
    assert "rm.price_dropped" in drop_sql
    assert "rm.publisher_visible_public" not in drop_sql
    assert "facebook" in normal_params
    assert "Tan An" in normal_params
    assert "dat_nen" in normal_params
    assert -3 not in normal_params
    assert "-3 months" in normal_params


@pytest.mark.parametrize(
    ("sort_by", "sort_dir", "needle"),
    (
        ("area", "asc", "rm.area_m2 ASC NULLS LAST"),
        ("price", "desc", "rm.price_ty DESC NULLS LAST"),
        ("price_m2", "asc", "rm.listing_price_per_m2 ASC NULLS LAST"),
        ("fair", "desc", "rm.fair_ppm2 DESC NULLS LAST"),
        ("date", "desc", "rm.listing_id DESC"),
        ("ward", "asc", "rm.ward ASC NULLS LAST"),
        ("prop_type", "asc", "rm.property_type ASC NULLS LAST"),
    ),
)
def test_listing_sort_is_whitelisted_and_stable(sort_by, sort_dir, needle):
    from services.listing_feed import listing_sort_sql

    sql = listing_sort_sql(sort_by, sort_dir, "rm")

    assert sql.startswith("rm.publisher_rank ASC")
    assert needle in sql
    assert sql.endswith("rm.listing_id DESC")


def test_listing_feed_dispatches_only_when_projection_is_ready(monkeypatch):
    from services import listing_feed

    calls = []
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setattr(
        listing_feed,
        "load_listings_from_read_model",
        lambda *_args, **_kwargs: calls.append("read_model") or {},
    )
    monkeypatch.setattr(
        listing_feed,
        "_load_listing_feed_legacy",
        lambda *_args, **_kwargs: calls.append("legacy") or {},
    )

    listing_feed.load_listing_feed(None, listings_version=0)
    listing_feed.load_listing_feed(None, listings_version=1)

    assert calls == ["legacy", "read_model"]


def test_api_listings_delegates_database_work_to_listing_service(monkeypatch):
    import app as radar_app

    captured = []

    def fake_loader(*_args, **kwargs):
        captured.append(kwargs)
        return {
            "listings": [],
            "total": 0,
            "page": kwargs["page"],
            "limit": kwargs["limit"],
            "pages": 0,
            "has_more": False,
            "tier": kwargs["tier"],
        }

    def fail_inline_connection(*_args, **_kwargs):
        raise AssertionError("api_listings still opens its inline SQL connection")

    monkeypatch.setattr(
        radar_app, "load_listing_feed", fake_loader, raising=False
    )
    monkeypatch.setattr(
        radar_app,
        "_listing_dataset_versions",
        lambda: {"listings": 7},
    )
    monkeypatch.setattr(radar_app, "connect", fail_inline_connection)

    response = radar_app.app.test_client().get(
        "/api/listings?date_range=3m&page=1&limit=50"
    )

    assert response.status_code == 200
    assert len(captured) == 1
    assert captured[0]["date_range"] == "3m"
    assert captured[0]["listings_version"] == 7


def test_listing_compare_reports_only_safe_metadata(monkeypatch):
    from cli import system

    monkeypatch.setattr(
        system,
        "_collect_listing_page",
        lambda loader, **_kwargs: (
            {
                "rows": [
                    {
                        "id": 7,
                        "description": "private A",
                        "url": "https://a",
                    }
                ],
                "meta": {"total": 1, "page": 1},
            }
            if loader.__name__.endswith("legacy")
            else {
                "rows": [
                    {
                        "id": 8,
                        "description": "private B",
                        "url": "https://b",
                    }
                ],
                "meta": {"total": 1, "page": 1},
            }
        ),
    )

    report = system.compare_listing_read_model(limit=20)
    rendered = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "mismatch"
    assert "private A" not in rendered
    assert "private B" not in rendered
    assert "https://a" not in rendered
    assert "https://b" not in rendered
    assert "legacy_only_ids" in rendered
    assert "read_model_only_ids" in rendered


def test_listing_formatter_recomputes_drop_pct_from_effective_first_price():
    from services import listing_feed

    row = _listing_row()
    row.update(
        {
            "price_ty": 2.4,
            "price_first_ty": 3.1,
            "price_drop_pct": 4.0,
        }
    )

    listing = listing_feed._format_listing_row(row, [], tier="guest")

    assert listing["price_dropped"] is True
    assert listing["drop_pct"] == 22.58

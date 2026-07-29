from unittest import mock


class _Result:
    def __init__(self, *, one=None, rows=None):
        self._one = one
        self._rows = rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _DetailConnection:
    def __init__(self, listing):
        self.listing = listing
        self.detail_sql = ""

    def execute(self, sql, _params=None):
        if "FROM listings l" in sql:
            self.detail_sql = sql
            return _Result(one=self.listing)
        return _Result(rows=[])

    def close(self):
        return None


def _listing_row(**overrides):
    row = {
        "id": 42,
        "source": "facebook",
        "url": "https://source.example/listing",
        "title": "Mapped listing",
        "description": "Description",
        "ward": "Phú Lợi",
        "area_m2": 100.0,
        "frontage_m": 5.0,
        "depth_m": 20.0,
        "property_type": "dat_nen",
        "price_ty": 2.0,
        "price_per_m2": 20.0,
        "road_type": "duong_nhua",
        "road_tier": 2,
        "road_name": "ĐX 43",
        "has_so": 1,
        "price_dropped": 0,
        "price_drop_pct": None,
        "price_first_ty": None,
        "duplicate_of_id": None,
        "posted_at": "2026-07-29",
        "crawled_at": "2026-07-29",
        "is_signal": 1,
        "mos_pct": 33.3,
        "fair_ppm2": 30.0,
        "fair_ppm2_old": 30.0,
        "fair_ppm2_new": None,
        "mos_pct_old": 33.3,
        "mos_pct_new": None,
        "fair_ppm2_display": 30.0,
        "mos_pct_display": 33.3,
        "signal_model": "legacy",
        "signal_score": 70,
        "trust_tier": "candidate_signal",
        "trust_score": 0,
        "legal_status": "unverified",
        "legal_flags": "",
        "legal_verification_status": None,
        "legal_confidence_score": None,
        "legal_thua_so": None,
        "legal_to_ban_do": None,
        "legal_area_m2": None,
        "legal_residential_m2": None,
        "legal_address": None,
        "legal_ward": None,
        "legal_road_text": None,
        "legal_road_code": None,
        "road_match_status": None,
        "legal_conflict_flags": None,
        "is_fresh_locked": 0,
        "map_lat": 10.992,
        "map_lng": 106.676,
        "map_precision": "road",
        "map_label": "Theo tên đường ĐX 43, Phú Lợi",
        "map_resolver_version": "osm-2026-07-29-v1",
    }
    row.update(overrides)
    return row


def test_listing_detail_exposes_trusted_derived_map_location():
    from services import market_data

    conn = _DetailConnection(_listing_row())
    with mock.patch.object(market_data, "_open_read_conn", return_value=conn):
        detail = market_data.load_listing_detail(None, 42, tier="guest")

    assert "LEFT JOIN listing_map_locations ml ON ml.listing_id = l.id" in conn.detail_sql
    assert detail["map_location"] == {
        "lat": 10.992,
        "lng": 106.676,
        "precision": "road",
        "label": "Theo tên đường ĐX 43, Phú Lợi",
        "resolver_version": "osm-2026-07-29-v1",
    }


def test_listing_detail_without_derived_location_returns_none():
    from services import market_data

    conn = _DetailConnection(_listing_row(
        map_lat=None,
        map_lng=None,
        map_precision=None,
        map_label=None,
        map_resolver_version=None,
    ))
    with mock.patch.object(market_data, "_open_read_conn", return_value=conn):
        detail = market_data.load_listing_detail(None, 42, tier="guest")

    assert detail["map_location"] is None


def test_listing_detail_api_serializes_map_location():
    import app as app_module

    location = {
        "lat": 10.992,
        "lng": 106.676,
        "precision": "road",
        "label": "Theo tên đường ĐX 43, Phú Lợi",
        "resolver_version": "osm-2026-07-29-v1",
    }
    app_module.app.config.update(TESTING=True)
    with mock.patch.object(
        app_module,
        "load_listing_detail",
        return_value={
            "listing": _listing_row(),
            "images": [],
            "history": [],
            "legal_verification": {},
            "map_location": location,
            "tier": "guest",
        },
    ):
        response = app_module.app.test_client().get("/api/listing/42")

    assert response.status_code == 200
    assert response.get_json()["map_location"] == location

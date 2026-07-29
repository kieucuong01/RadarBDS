import json
from unittest import mock


def _client():
    import app as app_module

    app_module.app.config.update(TESTING=True)
    return app_module, app_module.app.test_client()


def _safe_summary(**_kwargs):
    return {
        "mode": "signals",
        "summary": {
            "total": 0,
            "mapped": 0,
            "unmapped_count": 0,
            "exact_count": 0,
            "road_count": 0,
            "ward_count": 0,
        },
        "locations": [],
    }


def test_map_summary_requires_known_mode():
    app_module, client = _client()

    with mock.patch.object(
        app_module,
        "load_listing_map_summary",
        side_effect=_safe_summary,
    ):
        assert client.get("/api/map-listings").status_code == 400
        assert client.get("/api/map-listings?mode=market").status_code == 400
        assert client.get("/api/map-listings?mode=signals").status_code == 200
        assert client.get("/api/map-listings?mode=all").status_code == 200


def test_map_endpoint_passes_normalized_filters_and_guest_source_policy():
    app_module, client = _client()
    captured = {}

    def loader(**kwargs):
        captured.update(kwargs)
        return _safe_summary()

    query = (
        "mode=all&city=THỦ+DẦU+MỘT&ward=Phú+Lợi"
        "&source=guland&prop_type=dat_nen&only_drops=1&mos_min=25"
        "&area_min=80&area_max=150&price_min=1&price_max=3"
        "&area_range=90:120&price_range=1.5:2.5"
        "&q=DX+43&date_range=1m&complete=1"
    )
    with mock.patch.object(
        app_module,
        "load_listing_map_summary",
        side_effect=loader,
    ):
        response = client.get(f"/api/map-listings?{query}")

    assert response.status_code == 200
    filters = captured["filters"]
    assert captured["mode"] == "all"
    assert captured["tier"] == "guest"
    assert filters.city == "THỦ DẦU MỘT"
    assert filters.wards == ("Phú Lợi",)
    assert filters.sources == ("facebook",)
    assert filters.prop_types == ("dat_nen",)
    assert filters.only_drops is False
    assert filters.mos_min == 10
    assert filters.area_min == 80
    assert filters.area_max == 150
    assert filters.price_min == 1
    assert filters.price_max == 3
    assert filters.area_ranges == ((90.0, 120.0),)
    assert filters.price_ranges == ((1.5, 2.5),)
    assert filters.keyword == "DX 43"
    assert filters.date_range == "1m"
    assert filters.complete_only is True


def test_map_items_validate_location_paging_and_strip_sensitive_fields():
    app_module, client = _client()

    unsafe = {
        "items": [{
            "id": 1,
            "title": "Tin",
            "url": "https://secret.test",
            "phone": "0909",
            "contact_phone": "0909",
            "description": "private",
            "seller_name": "Broker",
        }],
        "total": 1,
        "page": 1,
        "limit": 50,
    }
    with mock.patch.object(
        app_module,
        "load_listing_map_items",
        return_value=unsafe,
    ) as loader:
        assert client.get(
            "/api/map-listing-items?mode=signals"
        ).status_code == 400
        assert client.get(
            "/api/map-listing-items?mode=signals&location_key=bad:key"
        ).status_code == 400
        assert client.get(
            "/api/map-listing-items?mode=signals"
            "&location_key=ward:thu-dau-mot:phu-loi&page=0"
        ).status_code == 400
        response = client.get(
            "/api/map-listing-items?mode=signals"
            "&location_key=ward:thu-dau-mot:phu-loi&page=1&limit=500"
        )

    assert response.status_code == 200
    assert loader.call_args.kwargs["limit"] == 50
    text = json.dumps(response.get_json())
    for forbidden in (
        '"url"',
        '"phone"',
        '"contact_phone"',
        '"description"',
        '"seller_name"',
    ):
        assert forbidden not in text

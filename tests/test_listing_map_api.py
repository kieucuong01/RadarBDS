import json
from unittest import mock


LISTING_MAP_TRACK_ACTIONS = {
    "listing_map_opened",
    "listing_map_closed",
    "listing_map_base_layer_changed",
    "listing_map_group_selected",
    "listing_map_retry",
}


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
            "landmark_count": 0,
            "nearby_count": 0,
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
            "evidence_text": "private evidence",
            "source_url": "https://secret.test/source",
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
        assert client.get(
            "/api/map-listing-items?mode=signals"
            "&location_key=landmark:thu-dau-mot:phu-loi:tdc-a&page=1"
        ).status_code == 200
        assert client.get(
            "/api/map-listing-items?mode=signals"
            "&location_key=nearby:thu-dau-mot:phu-loi:dx-43:near&page=1"
        ).status_code == 400
        assert client.get(
            "/api/map-listing-items?mode=signals"
            "&location_key=unknown:thu-dau-mot&page=1"
        ).status_code == 400

    assert response.status_code == 200
    assert any(
        call.kwargs["limit"] == 50
        for call in loader.call_args_list
    )
    text = json.dumps(response.get_json())
    for forbidden in (
        '"url"',
        '"phone"',
        '"contact_phone"',
        '"description"',
        '"seller_name"',
        '"evidence_text"',
        '"source_url"',
    ):
        assert forbidden not in text


def test_listing_map_tracking_actions_are_allowlisted_and_privacy_bounded(
    monkeypatch,
):
    app_module, client = _client()
    recorded = []
    monkeypatch.setattr(
        app_module,
        "log_audit",
        lambda **payload: recorded.append(payload),
    )
    monkeypatch.setattr(app_module, "current_user", lambda: None)
    monkeypatch.setattr(app_module, "current_tier", lambda: "guest")

    for action in LISTING_MAP_TRACK_ACTIONS:
        assert action in app_module.ALLOWED_TRACK_ACTIONS
        response = client.post(
            "/api/track",
            json={
                "action": action,
                "listing_id": 42,
                "context": {
                    "mode": "signals",
                    "precision": "road",
                    "listing_count": 3.4,
                    "mapped_count": 8,
                    "unmapped_count": -2,
                    "group_count": 4,
                    "layer_ids": [
                        "street",
                        "planning-land-use",
                        "BAD VALUE",
                    ],
                    "base_layer_id": "satellite",
                    "close_reason": "browser_back",
                    "lat": 10.99,
                    "lng": 106.67,
                    "location_key": "road:secret",
                    "keyword": "secret",
                },
            },
        )
        assert response.status_code == 200

    expected_context = {
        "mode": "signals",
        "precision": "road",
        "listing_count": 3,
        "mapped_count": 8,
        "unmapped_count": 0,
        "group_count": 4,
        "layer_ids": ["street", "planning-land-use"],
        "base_layer_id": "satellite",
        "close_reason": "browser_back",
    }
    assert len(recorded) == len(LISTING_MAP_TRACK_ACTIONS)
    assert all(item["context"] == expected_context for item in recorded)
    assert all(item["listing_id"] is None for item in recorded)

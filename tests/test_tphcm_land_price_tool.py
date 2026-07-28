def test_tphcm_land_price_tool_page_and_nav():
    import app as radar_app

    html = radar_app.app.test_client().get("/bang-gia-dat-tphcm").get_data(as_text=True)

    assert "Tra cứu bảng giá đất TP.HCM mới 2026" in html
    assert 'data-nav="bang-gia-dat" aria-current="page"' in html
    assert "window.TPHCM_LAND_PRICE_AREAS" in html
    assert 'id="keywordSuggestions"' in html
    assert 'list="landPriceAreaOptions"' in html
    assert 'id="landPriceAreaOptions"' in html


def test_tphcm_land_price_tool_has_trust_and_accessible_result_controls():
    import app as radar_app

    html = radar_app.app.test_client().get("/bang-gia-dat-tphcm").get_data(as_text=True)

    assert 'href="https://congbao.hochiminhcity.gov.vn/' in html
    assert "Dữ liệu áp dụng từ 01/01/2026" in html
    assert '<label for="landPriceQuery">' in html
    assert 'role="combobox"' in html
    assert 'aria-autocomplete="list"' in html
    assert 'role="listbox"' in html
    assert 'id="landPriceCards"' in html
    assert 'id="landPriceEmpty"' in html
    assert 'id="landPricePagination"' in html


def test_tphcm_land_price_tool_has_ungated_contextual_next_steps():
    import app as radar_app

    html = radar_app.app.test_client().get("/bang-gia-dat-tphcm").get_data(as_text=True)

    assert 'id="landPriceActions"' in html
    assert 'id="landPriceSourceCta"' in html
    assert 'id="landPriceValuationCta"' in html
    assert 'href="/dinh-gia-bds"' in html
    assert "Đăng nhập để tra cứu" not in html


def test_tphcm_land_price_api_searches_pdf_data():
    import app as radar_app

    data = radar_app.app.test_client().get(
        "/api/tphcm-land-prices?q=nguyen%20hue&area=PH%C6%AF%E1%BB%9CNG%20S%C3%80I%20G%C3%92N"
    ).get_json()

    assert data["ok"] is True
    assert data["unit"] == "1.000 đồng/m²"
    assert data["items"][0]["street"] == "NGUYỄN HUỆ"
    assert data["items"][0]["match_type"] == "exact_street"
    assert data["items"][0]["residential"] == 687200
    assert data["total"] == 3


def test_tphcm_land_price_api_accepts_typable_area_filter_and_bad_limit():
    import app as radar_app

    client = radar_app.app.test_client()
    data = client.get("/api/tphcm-land-prices?q=nguyen%20hue&area=sai").get_json()
    bad_limit = client.get("/api/tphcm-land-prices?q=nguyen%20hue&limit=nope")

    assert data["ok"] is True
    assert any(item["street"] == "NGUYỄN HUỆ" and item["area"] == "PHƯỜNG SÀI GÒN" for item in data["items"])
    assert bad_limit.status_code == 200


def test_tphcm_land_price_api_reports_true_total_and_paginates():
    import app as radar_app

    data = radar_app.app.test_client().get(
        "/api/tphcm-land-prices?q=nguyen%20hue&limit=2&page=2"
    ).get_json()

    assert data["total"] > len(data["items"])
    assert data["page"] == 2
    assert data["limit"] == 2
    assert data["has_more"] is True


def test_tphcm_land_price_api_clamps_page_past_last_result():
    import app as radar_app

    data = radar_app.app.test_client().get(
        "/api/tphcm-land-prices?q=nguyen%20hue&area=PH%C6%AF%E1%BB%9CNG%20S%C3%80I%20G%C3%92N&limit=2&page=500"
    ).get_json()

    assert data["page"] == 2
    assert len(data["items"]) == 1
    assert data["has_more"] is False


def test_tphcm_land_price_api_rejects_unfiltered_search():
    import app as radar_app

    response = radar_app.app.test_client().get("/api/tphcm-land-prices")

    assert response.status_code == 400
    assert response.get_json()["error"] == "search_required"


def test_tphcm_land_price_api_deduplicates_identical_rows():
    import app as radar_app

    data = radar_app.app.test_client().get(
        "/api/tphcm-land-prices?q=duong%20noi%20bo%20lo%20gioi&area=tan%20my&limit=100"
    ).get_json()
    identities = [
        (
            item["area"],
            item["street"],
            item["from"],
            item["to"],
            item["residential"],
            item["commerce_service"],
            item["production_business"],
        )
        for item in data["items"]
    ]

    assert len(identities) == len(set(identities))


def test_tphcm_land_price_api_exposes_official_provenance():
    import app as radar_app

    data = radar_app.app.test_client().get(
        "/api/tphcm-land-prices?q=nguyen%20hue&limit=1"
    ).get_json()

    assert data["source_url"].startswith("https://congbao.hochiminhcity.gov.vn/")
    assert data["data_as_of"] == "2026-01-01"


def test_tphcm_land_price_tool_is_in_sitemap_and_llms():
    import app as radar_app

    sitemap = radar_app.app.test_client().get("/sitemap.xml").get_data(as_text=True)
    llms = radar_app.app.test_client().get("/llms.txt").get_data(as_text=True)

    assert "<loc>https://radarbds.vn/bang-gia-dat-tphcm</loc>" in sitemap
    assert "https://radarbds.vn/bang-gia-dat-tphcm" in llms


def test_tphcm_land_price_tool_tracks_non_sensitive_funnel_events():
    from pathlib import Path

    javascript = Path("static/js/tphcm_land_price_tool.js").read_text(encoding="utf-8")

    for event_name in (
        "land_price_search",
        "land_price_success",
        "land_price_no_result",
        "land_price_error",
        "land_price_source_open",
        "land_price_valuation_click",
    ):
        assert f"track('{event_name}'" in javascript
    assert "query_length_bucket" in javascript


def test_search_returns_unique_stable_row_keys():
    import app as radar_app

    client = radar_app.app.test_client()
    path = (
        "/api/tphcm-land-prices?q=nguyen%20hue"
        "&area=PH%C6%AF%E1%BB%9CNG%20S%C3%80I%20G%C3%92N"
    )
    first = client.get(path).get_json()
    second = client.get(path).get_json()

    first_keys = [item["row_key"] for item in first["items"]]
    assert first_keys == [item["row_key"] for item in second["items"]]
    assert len(first_keys) == len(set(first_keys))


def test_guest_calculation_uses_server_side_base_prices():
    import app as radar_app

    client = radar_app.app.test_client()
    row = client.get(
        "/api/tphcm-land-prices?q=nguyen%20hue"
        "&area=PH%C6%AF%E1%BB%9CNG%20S%C3%80I%20G%C3%92N&limit=1"
    ).get_json()["items"][0]

    response = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            "row_key": row["row_key"],
            "base_prices": {"residential": 1},
            "land_area_m2": 100,
            "frontage_m": 5,
            "depth_m": 20,
            "location": {"mode": "standard", "access": "frontage"},
        },
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["values"]["residential"]["base_unit_price"] == 687_200_000
    assert data["row"]["street"] == "NGUYỄN HUỆ"


def test_calculation_returns_field_errors_and_missing_row():
    import app as radar_app

    client = radar_app.app.test_client()
    missing = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            "row_key": "missing",
            "land_area_m2": 100,
            "frontage_m": 5,
            "depth_m": 20,
            "location": {"mode": "standard", "access": "frontage"},
        },
    )
    row_key = client.get(
        "/api/tphcm-land-prices?q=nguyen%20hue&limit=1"
    ).get_json()["items"][0]["row_key"]
    invalid = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            "row_key": row_key,
            "land_area_m2": 0,
            "frontage_m": 5,
            "depth_m": 20,
            "location": {"mode": "standard", "access": "frontage"},
        },
    )

    assert missing.status_code == 404
    assert missing.get_json()["error"] == "row_not_found"
    assert invalid.status_code == 400
    assert "land_area_m2" in invalid.get_json()["field_errors"]


def test_calculation_rejects_non_object_json_and_location():
    import app as radar_app

    client = radar_app.app.test_client()
    row_key = client.get(
        "/api/tphcm-land-prices?q=nguyen%20hue&limit=1"
    ).get_json()["items"][0]["row_key"]

    non_object = client.post(
        "/api/tphcm-land-prices/calculate",
        json=["not", "an", "object"],
    )
    invalid_location = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            "row_key": row_key,
            "land_area_m2": 100,
            "frontage_m": 5,
            "depth_m": 20,
            "location": ["frontage"],
        },
    )

    assert non_object.status_code == 400
    assert "request" in non_object.get_json()["field_errors"]
    assert invalid_location.status_code == 400
    assert "location" in invalid_location.get_json()["field_errors"]


def test_guest_mixed_calculation_uses_server_area_zone_and_base_price():
    import app as radar_app

    client = radar_app.app.test_client()
    row = client.get(
        "/api/tphcm-land-prices",
        query_string={
            "q": "nguyen hue",
            "area": "PHƯỜNG SÀI GÒN",
            "limit": 1,
        },
    ).get_json()["items"][0]
    response = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            "row_key": row["row_key"],
            "parcel_mode": "mixed",
            "land_area_m2": 500,
            "frontage_m": 10,
            "depth_m": 50,
            "residential_area_m2": 100,
            "agricultural_area_m2": 400,
            "residential_geometry": {"use_custom": False},
            "location": {"mode": "standard", "access": "frontage"},
            "agricultural": {
                "land_type": "perennial",
                "position": 1,
                "zone": 4,
                "base_price": 1,
            },
            "base_prices": {"residential": 1},
        },
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["parcel_mode"] == "mixed"
    assert data["mixed_use"]["agricultural"]["zone"] == 1
    assert data["mixed_use"]["agricultural"]["unit_price"] == 68_720_000
    assert data["mixed_use"]["residential"]["base_unit_price"] == 687_200_000
    assert data["mixed_use"]["total_value"] == 96_208_000_000


def test_commune_mixed_calculation_only_uses_article_5_8_when_confirmed():
    import app as radar_app

    client = radar_app.app.test_client()
    row = client.get(
        "/api/tphcm-land-prices",
        query_string={"area": "XÃ CỦ CHI", "limit": 1},
    ).get_json()["items"][0]
    base_payload = {
        "row_key": row["row_key"],
        "parcel_mode": "mixed",
        "land_area_m2": 100,
        "frontage_m": 5,
        "depth_m": 20,
        "residential_area_m2": 50,
        "agricultural_area_m2": 50,
        "residential_geometry": {"use_custom": False},
        "location": {"mode": "standard", "access": "frontage"},
        "agricultural": {
            "land_type": "perennial",
            "position": 1,
            "in_residential_area": False,
            "same_parcel_has_house": False,
        },
    }
    normal = client.post(
        "/api/tphcm-land-prices/calculate",
        json=base_payload,
    ).get_json()
    base_payload["agricultural"]["in_residential_area"] = True
    special = client.post(
        "/api/tphcm-land-prices/calculate",
        json=base_payload,
    ).get_json()

    assert normal["mixed_use"]["agricultural"]["pricing_mode"] == "normal_table"
    assert special["mixed_use"]["agricultural"]["pricing_mode"] == "article_5_8"
    assert normal["mixed_use"]["agricultural"]["special_unit_price"] is None
    assert special["mixed_use"]["agricultural"]["special_unit_price"] is not None
    assert (
        special["mixed_use"]["agricultural"]["unit_price"]
        >= normal["mixed_use"]["agricultural"]["unit_price"]
    )


def test_mixed_calculation_rejects_malformed_nested_objects_and_enum_values():
    import app as radar_app

    client = radar_app.app.test_client()
    row_key = client.get(
        "/api/tphcm-land-prices?q=nguyen%20hue&limit=1"
    ).get_json()["items"][0]["row_key"]
    common = {
        "row_key": row_key,
        "parcel_mode": "mixed",
        "land_area_m2": 100,
        "frontage_m": 5,
        "depth_m": 20,
        "residential_area_m2": 50,
        "agricultural_area_m2": 50,
        "location": {"mode": "standard", "access": "frontage"},
    }

    malformed_geometry = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            **common,
            "residential_geometry": ["not", "an", "object"],
            "agricultural": {"land_type": "annual", "position": 1},
        },
    )
    malformed_agricultural = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            **common,
            "residential_geometry": {"use_custom": False},
            "agricultural": ["not", "an", "object"],
        },
    )
    invalid_type = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            **common,
            "residential_geometry": {"use_custom": False},
            "agricultural": {"land_type": "forged", "position": 9},
        },
    )

    assert malformed_geometry.status_code == 400
    assert "residential_geometry" in malformed_geometry.get_json()["field_errors"]
    assert malformed_agricultural.status_code == 400
    assert "agricultural" in malformed_agricultural.get_json()["field_errors"]
    assert invalid_type.status_code == 400
    assert "agricultural.land_type" in invalid_type.get_json()["field_errors"]


def test_omitted_parcel_mode_keeps_the_single_parcel_contract():
    import app as radar_app

    client = radar_app.app.test_client()
    row_key = client.get(
        "/api/tphcm-land-prices?q=nguyen%20hue&limit=1"
    ).get_json()["items"][0]["row_key"]
    data = client.post(
        "/api/tphcm-land-prices/calculate",
        json={
            "row_key": row_key,
            "land_area_m2": 100,
            "frontage_m": 5,
            "depth_m": 20,
            "location": {"mode": "standard", "access": "frontage"},
        },
    ).get_json()

    assert "mixed_use" not in data
    assert data["values"]["residential"]["total_value"] > 0


def test_land_price_page_renders_accessible_position_calculator_shell():
    import app as radar_app

    html = radar_app.app.test_client().get(
        "/bang-gia-dat-tphcm"
    ).get_data(as_text=True)

    assert 'id="landPriceCalculator"' in html
    assert 'id="landPriceCalculatorForm"' in html
    assert 'id="landPriceCalculatorRowKey"' in html
    assert '<label for="landPriceLandArea">' in html
    assert '<label for="landPriceFrontage">' in html
    assert '<label for="landPriceDepth">' in html
    assert 'name="access"' in html
    assert 'id="landPriceAlleyFields"' in html
    assert '<details class="land-price-advanced">' in html
    assert 'id="landPriceCalculatorResult"' in html
    assert 'aria-live="polite"' in html
    assert "js/tphcm_land_price_calculator.js" in html


def test_land_price_page_renders_accessible_mixed_use_fields():
    import app as radar_app

    html = radar_app.app.test_client().get(
        "/bang-gia-dat-tphcm"
    ).get_data(as_text=True)

    assert 'id="landPriceMixedMode"' in html
    assert '<label for="landPriceMixedMode">' in html
    assert 'id="landPriceMixedFields"' in html
    assert '<label for="landPriceResidentialArea">' in html
    assert '<label for="landPriceAgriculturalArea">' in html
    assert '<label for="landPriceAgriculturalType">' in html
    assert 'name="agricultural_position"' in html
    assert 'id="landPriceAgriculturalSpecialContext"' in html
    assert 'for="landPriceInResidentialArea"' in html
    assert 'for="landPriceSameParcelHasHouse"' in html
    assert '<details class="land-price-residential-geometry"' in html
    assert 'id="landPriceResidentialCustomGeometry"' in html
    assert 'data-calculator-error="residential_area_m2"' in html
    assert 'data-calculator-error="agricultural_area_m2"' in html
    assert "tphcm-land-mixed-20260728" in html


def test_land_price_browser_calculator_has_row_actions_and_safe_analytics():
    import re
    from pathlib import Path

    lookup_javascript = Path(
        "static/js/tphcm_land_price_tool.js"
    ).read_text(encoding="utf-8")
    calculator_javascript = Path(
        "static/js/tphcm_land_price_calculator.js"
    ).read_text(encoding="utf-8")

    assert "data-calculate-row" in lookup_javascript
    assert 'data-row-key="${esc(row.row_key)}"' in lookup_javascript
    for event_name in (
        "land_price_calculator_open",
        "land_price_calculator_start",
        "land_price_calculator_success",
        "land_price_calculator_error",
        "land_price_calculator_advanced_open",
        "land_price_mixed_mode_toggle",
    ):
        assert f"track('{event_name}'" in calculator_javascript
    event_payloads = re.findall(
        r"track\('land_price_calculator_[^']+'(?:,\s*\{(.*?)\})?\);",
        calculator_javascript,
        flags=re.DOTALL,
    )
    for sensitive_name in (
        "landArea",
        "frontage",
        "depth",
        "street",
        "area",
        "rowKey",
    ):
        assert all(sensitive_name not in payload for payload in event_payloads)

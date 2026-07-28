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

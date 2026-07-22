def test_tphcm_land_price_tool_page_and_nav():
    import app as radar_app

    html = radar_app.app.test_client().get("/bang-gia-dat-tphcm").get_data(as_text=True)

    assert "Tra cứu bảng giá đất TP.HCM mới 2026" in html
    assert 'data-nav="bang-gia-dat" aria-current="page"' in html
    assert "tphcm-land-price-ux-20260722" in html
    assert "window.TPHCM_LAND_PRICE_AREAS" in html
    assert 'id="keywordSuggestions"' in html
    assert 'list="landPriceAreaOptions"' in html
    assert 'id="landPriceAreaOptions"' in html


def test_tphcm_land_price_api_searches_pdf_data():
    import app as radar_app

    data = radar_app.app.test_client().get(
        "/api/tphcm-land-prices?q=nguyen%20hue&area=PH%C6%AF%E1%BB%9CNG%20S%C3%80I%20G%C3%92N"
    ).get_json()

    assert data["ok"] is True
    assert data["unit"] == "1.000 đồng/m²"
    assert any(item["street"] == "NGUYỄN HUỆ" and item["residential"] == 687200 for item in data["items"])


def test_tphcm_land_price_api_accepts_typable_area_filter_and_bad_limit():
    import app as radar_app

    client = radar_app.app.test_client()
    data = client.get("/api/tphcm-land-prices?q=nguyen%20hue&area=sai").get_json()
    bad_limit = client.get("/api/tphcm-land-prices?q=nguyen%20hue&limit=nope")

    assert data["ok"] is True
    assert any(item["street"] == "NGUYỄN HUỆ" and item["area"] == "PHƯỜNG SÀI GÒN" for item in data["items"])
    assert bad_limit.status_code == 200


def test_tphcm_land_price_tool_is_in_sitemap_and_llms():
    import app as radar_app

    sitemap = radar_app.app.test_client().get("/sitemap.xml").get_data(as_text=True)
    llms = radar_app.app.test_client().get("/llms.txt").get_data(as_text=True)

    assert "<loc>https://radarbds.vn/bang-gia-dat-tphcm</loc>" in sitemap
    assert "https://radarbds.vn/bang-gia-dat-tphcm" in llms

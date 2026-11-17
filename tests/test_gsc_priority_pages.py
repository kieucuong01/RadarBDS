from urllib.parse import parse_qs, urlsplit

import pytest

from config.planning_pages import PLANNING_PAGES


@pytest.mark.parametrize("slug", ["thu-dau-mot", "ben-cat"])
def test_city_map_retains_canonical_and_opens_the_matching_planning_area(slug):
    import app as radar_app
    from config.city_map_products import get_city_map_page

    page = get_city_map_page(slug)
    response = radar_app.app.test_client().get(page["path"])
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert f'<link rel="canonical" href="https://radarbds.vn{page["path"]}">' in html
    assert "Xem QH sử dụng đất 2030" in html
    query = parse_qs(urlsplit(page["planning_href"]).query)
    assert query["city"] == [page["city_name"].upper()]
    assert query["planning"] == ["land_use_2030"]
    assert "Bản đồ hành chính" in html


def test_route_guide_distinguishes_illustration_from_parcel_planning():
    import app as radar_app

    path = "/quy-hoach-binh-duong/duong-my-phuoc-tan-van"
    response = radar_app.app.test_client().get(path)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
    assert "sơ đồ minh họa tuyến" in html
    assert 'href="#ban-do-tuyen"' in html
    assert html.index('id="ban-do-tuyen"') < html.index('planning-priority-proof')
    assert "Mở QHSDĐ 2030 tại Bến Cát" in html
    href = urlsplit(PLANNING_PAGES["duong-my-phuoc-tan-van"]["planning_href"])
    assert parse_qs(href.query)["city"] == ["BẾN CÁT"]
    state = parse_qs(href.fragment)
    assert state["planning"] == ["land_use_2030"]
    assert state["district"] == ["721"]
    assert state["listings"] == ["0"]
    assert "cach-tra-cuu-quy-hoach-theo-so-to-so-thua-toa-do" in html

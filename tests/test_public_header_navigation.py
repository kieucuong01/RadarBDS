from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import pytest


HEADER = Path("templates/partials/seo_header.html")
HEADER_JS = Path("static/js/seo_header.js")
SEO_CSS = Path("static/css/seo.css")
DASHBOARD = Path("templates/index.html")
DASHBOARD_JS = Path("static/js/main/core.js")
DASHBOARD_CSS = Path("static/css/main/layout.css")


def dashboard_markup():
    return DASHBOARD.read_text(encoding="utf-8").replace(
        '{% include "partials/product_mobile_nav.html" %}',
        Path("templates/partials/product_mobile_nav.html").read_text(encoding="utf-8"),
    )


def test_public_header_has_required_top_level_order():
    markup = HEADER.read_text(encoding="utf-8")
    labels = re.findall(
        r'(?:class="seo-nav-tab"[^>]*>|class="seo-nav-link[^"]*"[^>]*>)'
        r"\s*([^<]+)",
        markup,
    )

    assert [unescape(label) for label in labels] == [
        "Bản đồ quy hoạch",
        "Săn Deal BĐS",
        "Định giá đất",
        "Bảng giá đất",
        "Kiến thức & dữ liệu",
    ]


def test_planning_mega_menu_and_news_menu_use_canonical_registry_urls():
    import app as radar_app

    page = radar_app.app.test_client().get("/tin-tuc").get_data(as_text=True)
    markup = page.split('<header class="seo-header">', 1)[1].split(
        "</header>", 1
    )[0]
    required_paths = (
        "/ban-do-binh-duong",
        "/ban-do-thu-dau-mot",
        "/ban-do-di-an",
        "/ban-do-thuan-an",
        "/ban-do-ben-cat",
        "/quy-hoach-binh-duong/quy-hoach-su-dung-dat",
        "/quy-hoach-binh-duong/tuyen-duong",
        "/quy-hoach-binh-duong/quy-hoach-chi-tiet",
        "/quy-hoach-binh-duong/quy-hoach-phan-khu",
        "/tin-tuc/chu-de-nong",
        "/tin-tuc/du-lieu-radarbds",
        "/tin-tuc/quyet-dinh-van-ban",
    )

    assert 'class="seo-nav-menu seo-nav-mega"' in markup
    assert "Bản đồ địa giới" in markup
    assert "Bản đồ quy hoạch" in markup
    for path in required_paths:
        assert markup.count(f'href="{path}"') == 1
    expected_map_order = (
        "/ban-do-binh-duong",
        "/ban-do-thu-dau-mot",
        "/ban-do-di-an",
        "/ban-do-thuan-an",
        "/ban-do-ben-cat",
    )
    assert [markup.index(f'href="{path}"') for path in expected_map_order] == (
        sorted(markup.index(f'href="{path}"') for path in expected_map_order)
    )


def test_header_disclosures_have_accessible_state_and_interaction_guards():
    markup = HEADER.read_text(encoding="utf-8")
    script = HEADER_JS.read_text(encoding="utf-8")
    css = SEO_CSS.read_text(encoding="utf-8")

    assert markup.count('aria-expanded="false"') == 4
    assert markup.count('aria-controls="seoNav') == 3
    assert 'aria-controls="seoPrimaryNav"' in markup
    assert 'id="seoNavToggle"' in markup
    assert 'id="seoPrimaryNav"' in markup
    assert 'event.key !== "Escape"' in script
    assert 'menu.querySelectorAll("a")' in script
    assert "closeAll(null)" in script
    assert "public_header_menu_opened" in script
    assert "closeMobileNav(true)" in script
    assert "min-height: 44px" in css
    assert ".seo-nav-mega" in css


def test_dashboard_tools_link_to_new_public_hubs_without_replacing_task_tabs():
    markup = dashboard_markup()
    script = DASHBOARD_JS.read_text(encoding="utf-8")
    css = DASHBOARD_CSS.read_text(encoding="utf-8")

    assert 'data-tab-target="signals"' in markup
    assert 'data-tab-target="all"' in markup
    for path in (
        "/?tab=all&amp;map=1&amp;planning=land_use_2030",
        "/tin-tuc",
        "/bao-cao",
    ):
        assert markup.count(f'href="{path}"') >= 2
    assert 'class="tools-menu-panel" role="menu"' not in markup
    assert 'class="tools-menu-item" role="menuitem"' not in markup
    assert 'id="toolsSheetTrigger"' in markup
    assert 'aria-expanded="false"' in markup
    assert "dashboard_tool_" in script
    assert "closeButton.focus()" in script
    assert "trigger.focus()" in script
    assert re.search(
        r"\.tools-sheet-close\s*\{[^}]*width:\s*44px;[^}]*height:\s*44px;",
        css,
        re.S,
    )


def test_dashboard_task_tabs_and_signal_results_expose_agent_readable_state():
    markup = dashboard_markup()
    core_script = DASHBOARD_JS.read_text(encoding="utf-8")
    signal_script = Path("static/js/main/signals.js").read_text(
        encoding="utf-8"
    )

    for tab_id in ("signals", "all", "market", "insights"):
        assert markup.count(f'aria-controls="tab-{tab_id}"') == 2

    assert markup.count('data-tab-target="signals"') == 2
    assert markup.count(
        'data-tab-target="signals" aria-controls="tab-signals" '
        'aria-pressed="true"'
    ) == 2
    for tab_id in ("all", "market", "insights"):
        assert markup.count(
            f'data-tab-target="{tab_id}" aria-controls="tab-{tab_id}" '
            'aria-pressed="false"'
        ) == 2

    assert (
        'id="tab-signals" class="tab-content active" aria-hidden="false"'
        in markup
    )
    for tab_id in ("all", "market", "insights"):
        assert (
            f'id="tab-{tab_id}" class="tab-content" aria-hidden="true"'
            in markup
        )

    assert (
        'id="signalsGrid" role="region" '
        'aria-label="Danh sách signal phù hợp" aria-busy="true"'
    ) in markup
    assert "function syncDashboardTabState(tabId)" in core_script
    assert (
        "control.setAttribute('aria-pressed', isActive ? 'true' : 'false')"
        in core_script
    )
    assert (
        "panel.setAttribute('aria-hidden', isActive ? 'false' : 'true')"
        in core_script
    )
    assert "syncDashboardTabState(tabId);" in core_script
    assert "document.body.dataset.activeDashboardTab = tabId" in core_script
    assert 'role="status"' in signal_script


def test_listing_workspace_hides_promise_banners_on_desktop_card_tabs():
    markup = DASHBOARD.read_text(encoding="utf-8")
    layout_css = Path("static/css/main/layout.css").read_text(encoding="utf-8")
    cards_css = Path("static/css/main/cards.css").read_text(encoding="utf-8")

    assert 'data-active-dashboard-tab="signals"' in markup
    assert 'body[data-active-dashboard-tab="signals"] .dashboard-promise' in layout_css
    assert 'body[data-active-dashboard-tab="signals"] .traffic-priority-proof' in layout_css
    assert 'body[data-active-dashboard-tab="all"] .dashboard-promise' in layout_css
    assert 'body[data-active-dashboard-tab="all"] .traffic-priority-proof' in layout_css
    assert 'body[data-active-dashboard-tab="signals"] #signalsGrid' in cards_css
    assert 'body[data-active-dashboard-tab="all"] .listings-grid' in cards_css


def test_agent_readable_dashboard_assets_bust_immutable_browser_caches():
    markup = DASHBOARD.read_text(encoding="utf-8")
    detail_markup = Path("templates/listing_detail.html").read_text(
        encoding="utf-8"
    )
    shared_include = '{% include "partials/signal_card_script.html" %}'
    shared_script = Path("templates/partials/signal_card_script.html").read_text(encoding="utf-8")
    markup = markup.replace(shared_include, shared_script)
    detail_markup = detail_markup.replace(shared_include, shared_script)
    dashboard_assets = (
        "css/main/cards.css",
        "js/main/core.js",
        "js/main/signal_card.js",
        "js/main/signals.js",
    )

    for asset in dashboard_assets:
        matching_lines = [
            line for line in markup.splitlines() if asset in line
        ]
        assert len(matching_lines) == 1
        assert "?v=" in matching_lines[0]
        assert matching_lines[0].split("?v=", 1)[1].split("\"", 1)[0]

    for asset in ("css/main/cards.css", "js/main/signal_card.js"):
        matching_lines = [
            line for line in detail_markup.splitlines() if asset in line
        ]
        assert len(matching_lines) == 1
        assert "?v=" in matching_lines[0]
        assert matching_lines[0].split("?v=", 1)[1].split("\"", 1)[0]


def test_news_article_path_marks_news_navigation_active():
    import app as radar_app

    assert radar_app._active_public_nav("/tin-tuc/bai-phan-tich") == "tin-tuc"


@pytest.mark.parametrize("path", ["/", "/dinh-gia-bds", "/bang-gia-dat-tphcm", "/quy-hoach-binh-duong", "/tin-tuc", "/bao-cao"])
def test_four_product_entries_render_on_every_public_surface(path):
    import app as radar_app

    response = radar_app.app.test_client().get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    mobile = html.split('<nav class="mobile-bottom-nav product-mobile-nav"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r"<span>([^<]+)</span>", mobile) == [
        "Quy hoạch", "Săn Deal", "Định giá", "Bảng giá", "Thêm",
    ]
    for href in ("/?tab=all&amp;map=1&amp;planning=land_use_2030", "/dinh-gia-bds", "/bang-gia-dat-tphcm"):
        assert f'href="{href}"' in mobile

    class IdCollector(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = []

        def handle_starttag(self, tag, attrs):
            self.ids.extend(value for key, value in attrs if key == "id")

    parser = IdCollector()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids))
    if path == "/":
        assert '<details class="product-discovery" id="radarFunctions">' in html
        discovery_grid = html.split('class="product-discovery-grid"', 1)[1].split("</div>", 1)[0]
        assert discovery_grid.count("<a ") == 4
        assert '<button class="bottom-nav-item active" type="button" data-tab-target="signals"' in mobile
    else:
        assert 'href="/?tab=signals"' in mobile

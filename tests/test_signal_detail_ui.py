from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_modal_and_listing_detail_place_location_after_original_copy():
    modal = _read("templates/index.html")
    detail = _read("templates/listing_detail.html")

    for html in (modal, detail):
        description_at = html.index("NGUYÊN VĂN TIN RAO") if "NGUYÊN VĂN TIN RAO" in html else html.index("Nguyên văn tin rao")
        location_at = html.index("Vị trí BĐS")
        comparable_at = html.index("SO SÁNH LÔ TƯƠNG TỰ") if "SO SÁNH LÔ TƯƠNG TỰ" in html else html.index("Lô tương tự")
        assert description_at < location_at < comparable_at
        assert 'data-detail-location' in html
        assert 'data-location-map' in html
        assert 'data-location-copy' in html
        assert 'data-location-retry' in html
        assert "detail_location_map.js" in html


def test_detail_location_map_has_rendered_empty_and_retry_states():
    css = _read("static/css/main/modal.css")
    module = _read("static/js/main/detail_location_map.js")

    assert "Chưa xác định được vị trí đủ tin cậy" in module
    assert "Không tải được bản đồ vị trí" in module
    assert ".sm-location-map" in css
    assert ".sm-location-copy" in css


def test_signal_detail_assets_share_current_release_identity():
    modal = _read("templates/index.html")
    detail = _read("templates/listing_detail.html")
    release = "signal-detail-regression-20260729"

    for asset in (
        "detail_location_map.js",
        "signal_card.js",
        "comparable_carousel.js",
        "listing_detail_actions.js",
    ):
        needle = asset + "') }}?v=" + release
        assert needle in modal
        assert needle in detail

    assert "modal.js') }}?v=" + release in modal
    assert "modal.js') }}?v=favorite-listings-20260715" not in modal

    for html in (modal, detail):
        for asset in ("modal.css", "cards.css"):
            matching_lines = [line for line in html.splitlines() if asset in line]
            assert matching_lines
            assert any(release in line for line in matching_lines)


def test_modal_open_synchronizes_listing_state_and_uses_shared_adapters():
    module = _read("static/js/main/modal.js")

    assert "actions.dataset.listingId = listingId" in module
    assert "RadarDetailLocationMap.unmount" in module
    assert module.count("modal.dataset.listingId !== String(listingId)") >= 2
    assert "RadarComparableCarousel.mount" in module


def test_dashboard_feed_delegates_to_shared_signal_card_renderer():
    signals = _read("static/js/main/signals.js")
    index = _read("templates/index.html")
    detail = _read("templates/listing_detail.html")

    assert "RadarSignalCard.render" in signals
    assert "signal_card.js" in index
    assert "signal_card.js" in detail


def test_shared_signal_cards_have_resilient_media_and_no_link_underline():
    renderer = _read("static/js/main/signal_card.js")
    cards = _read("static/css/main/cards.css")

    assert "RadarSignalCard.useFallbackImage(this)" in renderer
    assert 'data-default-image="' in renderer
    assert ".scard,\n.scard:visited,\n.scard:hover" in cards
    assert "text-decoration: none" in cards
    assert ".scard:focus-visible" in cards


def test_comparable_controls_and_history_source_links_stay_legible():
    carousel = _read("static/js/main/comparable_carousel.js")
    modal_css = _read("static/css/main/modal.css")

    assert "Trang ${clampPage(page, count) + 1} / ${count}" in carousel
    controls_rule = modal_css[modal_css.index(".sm-comparable-controls button {"):]
    assert "min-width: 44px" in controls_rule
    assert "min-height: 44px" in controls_rule
    lot_link_rule = modal_css[modal_css.index(".sm-price-history .ph-lot-link {"):]
    assert "min-width: max-content" in lot_link_rule
    assert "white-space: nowrap" in lot_link_rule


def test_comparables_are_full_width_after_both_detail_columns():
    modal = _read("templates/index.html")
    detail = _read("templates/listing_detail.html")
    css = _read("static/css/main/modal.css")

    for html in (modal, detail):
        left_at = html.index('class="sm-left"')
        right_at = html.index('class="sm-right"')
        comparable_at = html.index('class="sm-section sm-comparable-section"')
        assert left_at < right_at < comparable_at
        assert 'data-comparable-carousel' in html
        assert "comparable_carousel.js" in html
    assert "grid-template-columns: minmax(0, 3fr) minmax(0, 2fr)" in css
    assert ".sm-comparable-section" in css
    assert "grid-column: 1 / -1" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    assert 'data-sm-tab="comps"' not in modal


def test_share_controls_are_available_on_both_detail_surfaces():
    modal = _read("templates/index.html")
    detail = _read("templates/listing_detail.html")

    for html in (modal, detail):
        assert "listing_detail_actions.js" in html
        assert "data-listing-actions" in html
        assert "data-listing-share-trigger" in html
        assert "data-listing-share-menu" in html
        assert "data-share-copy" in html
        assert "data-share-facebook" in html


def test_bad_listing_report_dialog_is_available_on_both_surfaces():
    modal = _read("templates/index.html")
    detail = _read("templates/listing_detail.html")
    expected_reasons = {
        "sold_or_unavailable",
        "wrong_price_or_area",
        "duplicate",
        "wrong_location",
        "spam_or_scam",
        "other",
    }

    for html in (modal, detail):
        assert "Báo xấu tin đăng" in html
        assert "data-listing-report-trigger" in html
        assert "data-listing-report-dialog" in html
        assert "data-listing-report-form" in html
        assert 'maxlength="500"' in html
        found = {
            reason
            for reason in expected_reasons
            if f'value="{reason}"' in html
        }
        assert found == expected_reasons

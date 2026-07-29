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


def test_dashboard_feed_delegates_to_shared_signal_card_renderer():
    signals = _read("static/js/main/signals.js")
    index = _read("templates/index.html")
    detail = _read("templates/listing_detail.html")

    assert "RadarSignalCard.render" in signals
    assert "signal_card.js" in index
    assert "signal_card.js" in detail


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

import pytest

from crawler.guland_pw import (
    GulandCrawler,
    _JS_BATCH_DETAIL,
    classify_detail_result,
)
from services.guland_reconciliation import ExistingGulandSnapshot


@pytest.mark.parametrize(
    ("detail", "outcome"),
    [
        ({"http_status": 200, "page_status": "live"}, "active"),
        ({"http_status": 404, "page_status": "removed"}, "removed"),
        ({"http_status": 503, "page_status": "unreachable"}, "unreachable"),
        ({"error": "timeout"}, "unreachable"),
    ],
)
def test_detail_result_classification(detail, outcome):
    assert classify_detail_result(detail).outcome == outcome


def test_cloudflare_and_blank_html_are_never_removed():
    assert classify_detail_result(
        {"http_status": 403, "page_status": "unreachable"}
    ).outcome == "unreachable"
    assert classify_detail_result(
        {"http_status": 200, "page_status": "unreachable"}
    ).outcome == "unreachable"


def test_removed_classification_preserves_explicit_page_reason():
    result = classify_detail_result(
        {
            "http_status": 200,
            "page_status": "removed",
            "page_reason": "not_found_path",
        }
    )

    assert result.outcome == "removed"
    assert result.reason == "not_found_path"


def test_detail_fetch_does_not_match_removed_words_across_entire_live_page():
    assert "tin.*(?:đã|bị).*(?:gỡ|xóa)" not in _JS_BATCH_DETAIL
    assert "tin.*không.*tồn tại" not in _JS_BATCH_DETAIL


def test_stale_verifier_records_each_explicit_outcome(monkeypatch):
    crawler = GulandCrawler()
    snapshots = [
        ExistingGulandSnapshot(
            1, 11, "https://guland.vn/post/live-1", "1", 2.5, None, "unknown"
        ),
        ExistingGulandSnapshot(
            2, 12, "https://guland.vn/post/removed-2", "2", 2.5, None, "unknown"
        ),
        ExistingGulandSnapshot(
            3, 13, "https://guland.vn/post/blocked-3", "3", 2.5, None, "unknown"
        ),
    ]
    details = {
        snapshots[0].url: {
            "url": snapshots[0].url,
            "http_status": 200,
            "page_status": "live",
            "detail_price_raw": "2,5 tỷ",
        },
        snapshots[1].url: {
            "url": snapshots[1].url,
            "http_status": 404,
            "page_status": "removed",
        },
        snapshots[2].url: {
            "url": snapshots[2].url,
            "http_status": 503,
            "page_status": "unreachable",
        },
    }
    recorded = []
    monkeypatch.setattr(
        crawler,
        "_load_verification_candidates",
        lambda limit: snapshots[:limit],
    )
    monkeypatch.setattr(
        crawler,
        "_fetch_details_batch",
        lambda page, urls: {url: details[url] for url in urls},
    )
    monkeypatch.setattr(
        crawler,
        "_record_source_outcome",
        lambda snapshot, outcome, reason: recorded.append(
            (snapshot.listing_id, outcome)
        ),
    )

    stats = crawler._verify_stale_listings(page=object(), limit=3)

    assert stats["active"] == 1
    assert stats["removed"] == 1
    assert stats["unreachable"] == 1
    assert recorded == [(11, "active"), (12, "removed"), (13, "unreachable")]


def test_after_targets_clamps_verification_limit(monkeypatch):
    crawler = GulandCrawler()
    captured = {}
    monkeypatch.setenv("GULAND_STATUS_VERIFY_LIMIT", "500")
    monkeypatch.setattr(
        crawler,
        "_verify_stale_listings",
        lambda page, limit: captured.setdefault("limit", limit) or {},
    )

    crawler.after_targets(page=object(), run_id=1)

    assert captured["limit"] == 200

from unittest import mock
import signal

import pytest


def test_quota_preflight_detects_fragmented_budget():
    from crawler.facebook_apify import FacebookApifyCrawler

    crawler = object.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = True
    with mock.patch("crawler.apify_token_pool.list_tokens_public", return_value=[
        {"active": True, "remaining": 14},
        {"active": True, "remaining": 14},
        {"active": False, "remaining": 900},
    ]):
        assert crawler.quota_preflight([{"tier": 15}, {"tier": 5}]) == {
            "required_posts": 20, "uncovered_profiles": 1,
        }


def test_unattempted_profile_is_recorded_as_error():
    from cli.crawlers import _record_facebook_profile_runs

    with mock.patch("db.crawl_runs.mark_url_error") as mark:
        _record_facebook_profile_runs(12, {
            "unattempted_profile_urls": ["https://www.facebook.com/skipped"],
        })
    assert mark.call_args.args[:2] == (12, "https://www.facebook.com/skipped")


def test_workflow_keeps_partial_and_stage_timings(tmp_path, monkeypatch):
    from services import crawl_workflow as workflow

    monkeypatch.setattr(workflow, "STATUS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "_alert", mock.Mock())
    with workflow.crawl_workflow("facebook"):
        with workflow.timed_stage("crawl_facebook"):
            workflow.mark_partial("one profile skipped")
    state = workflow.load_workflow_status("facebook")
    assert state["status"] == "partial"
    assert state["timings"][0]["stage"] == "crawl_facebook"
    assert state["finished_at"]
    workflow._alert.assert_called_once()


@pytest.mark.parametrize("terminated", [False, True])
def test_workflow_failure_or_sigterm_retains_failed_stage(tmp_path, monkeypatch, terminated):
    from services import crawl_workflow as workflow

    monkeypatch.setattr(workflow, "STATUS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "_alert", mock.Mock())
    original = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit if terminated else RuntimeError):
        with workflow.crawl_workflow("facebook"):
            with workflow.timed_stage("reprocess"):
                with workflow.timed_stage("dedup"):
                    if terminated:
                        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                    raise RuntimeError("test failure")
    state = workflow.load_workflow_status("facebook")
    assert state["status"] == "error"
    assert state["stage"] == "dedup"
    assert signal.getsignal(signal.SIGTERM) == original


def test_service_failure_catches_unhandled_kill(tmp_path, monkeypatch):
    from services import crawl_workflow as workflow

    monkeypatch.setattr(workflow, "STATUS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "_alert", mock.Mock())
    workflow._save({"source": "guland", "status": "running", "stage": "images"})
    workflow.record_service_result("guland", "oom-kill")
    assert workflow.load_workflow_status("guland")["service_result"] == "oom-kill"
    workflow._alert.assert_called_once()


def test_image_budget_defers_without_marking_images_missing(monkeypatch):
    from cleansing import download_images as images

    row = {"id": 1, "listing_id": 2, "img_url": "https://example.test/a.jpg", "img_order": 0}
    conn = mock.MagicMock()
    conn.__enter__.return_value.execute.return_value.fetchall.return_value = [row]
    monkeypatch.setattr(images, "get_conn", lambda: conn)
    monkeypatch.setattr(images.time, "monotonic", mock.Mock(side_effect=[0, 181]))
    fetch = mock.Mock()
    monkeypatch.setattr(images, "_fetch_validated_image", fetch)
    assert images._download_images(limit=5, max_seconds=180) == 0
    fetch.assert_not_called()
    assert conn.__enter__.return_value.execute.call_count == 1


def test_public_publication_failure_cannot_finish_workflow_successfully(monkeypatch):
    from cleansing import reprocess
    from analytics import market_trend, lifecycle
    from cleansing import dedup

    monkeypatch.setattr(reprocess, "get_conn", mock.MagicMock())
    monkeypatch.setattr(reprocess, "reprocess_listings", lambda **kw: {"processed_ids": [17]})
    monkeypatch.setattr(reprocess, "populate_content_hashes", lambda c: 0)
    monkeypatch.setattr(dedup, "flag_duplicates_in_db", lambda c: {})
    monkeypatch.setattr(lifecycle, "backfill_first_seen", lambda c: None)
    monkeypatch.setattr(lifecycle, "sweep_delisted", lambda c: [])
    for name in ("compute_weekly_trend", "compute_monthly_trend", "compute_daily_trend", "detect_price_drops"):
        monkeypatch.setattr(market_trend, name, lambda c: 0)
    valuation = mock.Mock(return_value={})
    monkeypatch.setattr(reprocess, "reprocess_valuation", valuation)
    monkeypatch.setattr(reprocess, "_run_listing_map_backfill", lambda *a, **kw: {})
    monkeypatch.setattr(reprocess, "publish_public_data", lambda **kw: {"status": "error"})
    with pytest.raises(RuntimeError, match="Public read-model publication failed"):
        reprocess._run_full_reprocess()
    valuation.assert_called_once_with(incremental_ids=[17])

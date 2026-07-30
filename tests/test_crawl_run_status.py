from contextlib import nullcontext
import uuid
from unittest import mock

import pytest

from crawler.base_crawler import BaseCrawler
from db.connection import get_conn
from db.crawl_runs import derive_crawl_status, mark_url_error
from db.schema import init_schema


@pytest.mark.parametrize(
    ("stats", "fatal", "expected"),
    [
        ({"fetched": 10, "errors": 0}, False, "done"),
        ({"fetched": 10, "errors": 1}, False, "partial"),
        ({"fetched": 0, "errors": 1}, True, "error"),
    ],
)
def test_derive_crawl_status(stats, fatal, expected):
    assert derive_crawl_status(stats, fatal=fatal) == expected


def test_mark_url_error_records_bounded_target_failure():
    init_schema()
    token = uuid.uuid4().hex
    with get_conn() as conn:
        run_id = conn.execute(
            "INSERT INTO crawl_runs (source, area) VALUES ('guland', ?)",
            (f"status-test-{token}",),
        ).lastrowid

    try:
        mark_url_error(run_id, "https://guland.vn/status-test", "x" * 700)
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT status, error_msg, completed_at
                FROM crawl_run_progress
                WHERE run_id=? AND target_url=?
                """,
                (run_id, "https://guland.vn/status-test"),
            ).fetchone()
        assert row["status"] == "error"
        assert len(row["error_msg"]) == 500
        assert row["completed_at"]
    finally:
        with get_conn() as conn:
            conn.execute("DELETE FROM crawl_run_progress WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM crawl_runs WHERE id=?", (run_id,))


class _CrawlerForStatusTest(BaseCrawler):
    SOURCE_NAME = "status-test"
    TARGET_URLS = ["https://example.test/fails", "https://example.test/ok"]

    def crawl_full(self, page, base_url):
        return self.crawl_incremental(page, base_url)

    def crawl_incremental(self, page, base_url):
        if base_url.endswith("/fails"):
            raise RuntimeError("target failed")
        self._stats["fetched"] += 1
        return 1


class _FakePage:
    def set_default_timeout(self, _timeout):
        return None


class _FakeContext:
    def new_page(self):
        return _FakePage()


class _FakeBrowser:
    def close(self):
        return None


def test_base_crawler_finishes_partial_once_after_target_failure(monkeypatch):
    crawler = _CrawlerForStatusTest()
    monkeypatch.setattr(
        crawler,
        "_launch",
        lambda _pw, headless=True: (_FakeBrowser(), _FakeContext()),
    )

    with mock.patch(
        "playwright.sync_api.sync_playwright",
        return_value=nullcontext(object()),
    ), mock.patch(
        "db.crawl_runs.get_incomplete_run",
        return_value=None,
    ), mock.patch(
        "db.crawl_runs.start_crawl_run",
        return_value=321,
    ), mock.patch(
        "db.crawl_runs.mark_url_done",
    ) as mark_done, mock.patch(
        "db.crawl_runs.mark_url_error",
    ) as mark_error, mock.patch(
        "db.crawl_runs.finish_crawl_run",
    ) as finish:
        stats = crawler.run(mode="incremental")

    assert stats["errors"] == 1
    mark_done.assert_called_once_with(321, "https://example.test/ok", 1)
    mark_error.assert_called_once()
    finish.assert_called_once()
    assert finish.call_args.kwargs["status"] == "partial"


def test_base_crawler_finishes_error_once_when_browser_setup_fails(monkeypatch):
    crawler = _CrawlerForStatusTest()
    monkeypatch.setattr(
        crawler,
        "_launch",
        mock.Mock(side_effect=RuntimeError("browser unavailable")),
    )

    with mock.patch(
        "playwright.sync_api.sync_playwright",
        return_value=nullcontext(object()),
    ), mock.patch(
        "db.crawl_runs.get_incomplete_run",
        return_value=None,
    ), mock.patch(
        "db.crawl_runs.start_crawl_run",
        return_value=322,
    ), mock.patch(
        "db.crawl_runs.finish_crawl_run",
    ) as finish:
        with pytest.raises(RuntimeError, match="browser unavailable"):
            crawler.run(mode="incremental")

    finish.assert_called_once()
    assert finish.call_args.kwargs["status"] == "error"


def test_base_crawler_runs_after_targets_hook_once(monkeypatch):
    crawler = _CrawlerForStatusTest()
    crawler.TARGET_URLS = ["https://example.test/ok"]
    after_targets = mock.Mock()
    monkeypatch.setattr(crawler, "after_targets", after_targets, raising=False)
    monkeypatch.setattr(
        crawler,
        "_launch",
        lambda _pw, headless=True: (_FakeBrowser(), _FakeContext()),
    )

    with mock.patch(
        "playwright.sync_api.sync_playwright",
        return_value=nullcontext(object()),
    ), mock.patch(
        "db.crawl_runs.get_incomplete_run",
        return_value=None,
    ), mock.patch(
        "db.crawl_runs.start_crawl_run",
        return_value=323,
    ), mock.patch(
        "db.crawl_runs.mark_url_done",
    ), mock.patch(
        "db.crawl_runs.finish_crawl_run",
    ):
        crawler.run(mode="incremental")

    after_targets.assert_called_once()
    assert after_targets.call_args.args[1] == 323

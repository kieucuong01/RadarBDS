from types import SimpleNamespace
from unittest import mock

import cli.crawlers as crawlers


class _FakeDbContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return ["2026-06-02 21:00:00"]


class _FakeCrawler:
    SOURCE_NAME = "fake"

    def run(self, mode, headless=True):
        return {"new": 0, "skipped": 0, "errors": 0}


def test_daily_facebook_crawl_uses_profile_daily_limits():
    captured = {}

    def fake_facebook_crawl_to_raw(**kwargs):
        captured.update(kwargs)
        return {
            "fetched": 1,
            "inserted": 1,
            "skipped": 0,
            "irrelevant": 0,
            "out_of_area": 0,
            "refreshed_images": 0,
        }

    args = SimpleNamespace(
        source=None,
        visible=False,
        no_reprocess=True,
        no_alert=True,
        no_groq=True,
    )

    with mock.patch.object(crawlers, "init_schema"), \
         mock.patch.object(crawlers, "get_conn", return_value=_FakeDbContext()), \
         mock.patch.object(crawlers, "_get_crawlers", return_value=[_FakeCrawler()]), \
         mock.patch.object(crawlers, "_facebook_crawl_to_raw", side_effect=fake_facebook_crawl_to_raw), \
         mock.patch.object(crawlers, "cmd_export_raw"), \
         mock.patch.object(crawlers, "_maybe_send_ops_alert"):
        crawlers._cmd_crawl(args, mode="incremental")

    assert captured["mode"] == "incremental"
    assert captured.get("limit_override") is None

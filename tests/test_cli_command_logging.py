import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_crawl_daily_installs_dedicated_command_log_name():
    import radar

    assert radar._command_log_name(["radar.py", "crawl-daily"]) == "crawl-daily.log"
    assert radar._command_log_name(["radar.py", "crawl-facebook"]) == ""


def test_crawl_daily_ignores_removed_no_flags_for_stale_schedules():
    import radar

    parser = radar.build_parser()
    args = radar._parse_args(
        parser,
        ["crawl-daily", "--source", "guland", "--no-alert", "--no-retired-provider"],
    )

    assert args.cmd == "crawl-daily"
    assert args.source == "guland"
    assert args.no_alert is True


def test_crawl_daily_rejects_disabled_sources():
    import pytest
    import radar

    parser = radar.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["crawl-daily", "--source", "batdongsan"])

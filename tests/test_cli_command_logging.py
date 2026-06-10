import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_crawl_daily_installs_dedicated_command_log_name():
    import radar

    assert radar._command_log_name(["radar.py", "crawl-daily"]) == "crawl-daily.log"
    assert radar._command_log_name(["radar.py", "crawl-facebook"]) == ""


def test_crawl_daily_accepts_legacy_no_groq_flag():
    import radar

    parser = radar.build_parser()
    args = parser.parse_args(["crawl-daily", "--source", "guland", "--no-alert", "--no-groq"])

    assert args.cmd == "crawl-daily"
    assert args.source == "guland"
    assert args.no_alert is True
    assert args.no_groq is True

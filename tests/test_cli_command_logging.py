import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_crawl_daily_installs_dedicated_command_log_name():
    import radar

    assert radar._command_log_name(["radar.py", "crawl-daily"]) == "crawl-daily.log"
    assert radar._command_log_name(["radar.py", "crawl-facebook"]) == ""

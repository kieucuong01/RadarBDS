import os

from crawler.base_crawler import _normalize_playwright_browser_path_env


def test_normalize_playwright_browser_path_env_strips_crlf(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/radar-bds/ms-playwright\r")

    _normalize_playwright_browser_path_env()

    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "/opt/radar-bds/ms-playwright"

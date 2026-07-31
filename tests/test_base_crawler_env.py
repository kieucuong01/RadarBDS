import os

from crawler.base_crawler import (
    _configured_playwright_executable,
    _normalize_playwright_browser_path_env,
)


def test_normalize_playwright_browser_path_env_strips_crlf(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/radar-bds/ms-playwright\r")

    _normalize_playwright_browser_path_env()

    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "/opt/radar-bds/ms-playwright"


def test_configured_playwright_executable_accepts_existing_file(
    monkeypatch,
    tmp_path,
):
    executable = tmp_path / "chrome.exe"
    executable.touch()
    monkeypatch.setenv("PLAYWRIGHT_EXECUTABLE_PATH", str(executable))

    assert _configured_playwright_executable() == str(executable)


def test_configured_playwright_executable_ignores_missing_explicit_path(
    monkeypatch,
):
    monkeypatch.setenv(
        "PLAYWRIGHT_EXECUTABLE_PATH",
        "Z:/definitely-missing/chrome.exe",
    )
    monkeypatch.setattr("crawler.base_crawler.sys.platform", "linux")

    assert _configured_playwright_executable() is None

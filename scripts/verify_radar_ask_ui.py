"""Local-only rendered Radar Ask release proof with seeded fake-provider users."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (ROOT / "artifacts" / "radar-ask").resolve()
VIEWPORTS = (
    ("desktop", 1440, 900),
    ("mobile", 390, 844),
)
APP_CONSOLE_ALLOWLIST = (
    "analytics.google.com",
    "stats.g.doubleclick.net",
    "www.google.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
)
QA_CAPABILITY_PATH = "/api/radar-ask/qa-capabilities"
QA_CAPABILITY_HEADER = "X-Radar-Ask-QA-Provider"


class VerificationError(RuntimeError):
    """A release-critical rendered contract did not hold."""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Radar Ask desktop/mobile UX against a seeded local fake-provider app.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--output", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    return parser.parse_args()


def _validated_config(args: argparse.Namespace) -> tuple[str, Path, str, str]:
    parsed = urlparse(str(args.base_url).strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise VerificationError("--base-url must be a loopback HTTP(S) test server")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise VerificationError("--base-url must not contain credentials, query, or fragment")
    output = args.output.resolve()
    try:
        output.relative_to(ARTIFACT_ROOT)
    except ValueError as exc:
        raise VerificationError("--output must stay under ignored artifacts/radar-ask/") from exc
    identifier = os.getenv("RADAR_ASK_TEST_IDENTIFIER", "").strip()
    password = os.getenv("RADAR_ASK_TEST_PASSWORD", "")
    if not identifier or not password:
        raise VerificationError(
            "RADAR_ASK_TEST_IDENTIFIER and RADAR_ASK_TEST_PASSWORD are required"
        )
    if os.getenv("RADAR_ASK_FAKE_PROVIDER", "").strip() != "1":
        raise VerificationError("RADAR_ASK_FAKE_PROVIDER=1 is required; live providers are forbidden")
    return str(args.base_url).rstrip("/"), output, identifier, password


def _private_response(response: Any) -> bool:
    cache_control = (response.headers.get("cache-control") or "").lower()
    return (
        "private" in cache_control
        and "no-store" in cache_control
        and not response.headers.get("x-radar-public-cache")
    )


def _valid_qa_capability(payload: object, headers: Any) -> bool:
    """Require server-owned proof that this target cannot reach a paid provider."""
    if not isinstance(payload, dict):
        return False
    header_value = ""
    if headers is not None:
        header_value = str(headers.get(QA_CAPABILITY_HEADER, "")).strip().lower()
    return (
        header_value == "fake"
        and payload.get("mode") == "radar_ask_test"
        and payload.get("provider") == "fake"
        and payload.get("database") == "radar_bds_test"
        and payload.get("backend_pipeline") == "real"
        and payload.get("live_provider_allowed") is False
    )


def _verify_server_capability(base_url: str, timeout_ms: int) -> dict[str, Any]:
    """Fail before login/question transmission unless the QA server proves isolation."""
    try:
        response = requests.get(
            f"{base_url}{QA_CAPABILITY_PATH}",
            headers={"Accept": "application/json"},
            timeout=max(0.1, min(timeout_ms / 1_000, 5.0)),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise VerificationError(
            "server did not prove fake-provider/test-database isolation"
        ) from exc
    if not _private_response(response) or not _valid_qa_capability(payload, response.headers):
        raise VerificationError(
            "server did not prove fake-provider/test-database isolation"
        )
    return {
        "mode": "radar_ask_test",
        "provider": "fake",
        "database": "radar_bds_test",
        "backend_pipeline": "real",
    }


def _application_console_errors(messages: list[str]) -> list[str]:
    return [
        message[:500]
        for message in messages
        if not any(marker in message for marker in APP_CONSOLE_ALLOWLIST)
    ]


def _submit(page: Any, *, depth: str, question: str, timeout_ms: int) -> tuple[dict[str, Any], float]:
    page.locator(f'[data-depth="{depth}"]').click()
    composer = page.locator("[data-composer]")
    composer.fill(question)
    started = time.perf_counter()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlparse(response.url).path == "/api/radar-ask/questions",
        timeout=timeout_ms,
    ) as response_info:
        page.locator("[data-composer-form]").evaluate("form => form.requestSubmit()")
    response = response_info.value
    duration_ms = (time.perf_counter() - started) * 1_000
    if response.status not in {200, 202}:
        raise VerificationError(f"question request returned HTTP {response.status}")
    if not _private_response(response):
        raise VerificationError("question response was not private/no-store")
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("run_id") or not payload.get("session_id"):
        raise VerificationError("question response omitted run/session IDs")
    return payload, duration_ms


def _open_sources(page: Any, timeout_ms: int) -> None:
    source_button = page.locator("[data-open-evidence]").last
    source_button.wait_for(state="visible", timeout=timeout_ms)
    source_button.click()
    page.locator("[data-evidence-sheet]").wait_for(state="visible", timeout=timeout_ms)
    page.locator("[data-evidence-close]").click()


def _open_history(page: Any, mobile: bool, timeout_ms: int) -> None:
    if mobile:
        page.locator("[data-history-open]").first.click()
    page.locator("[data-history-list]").wait_for(state="visible", timeout=timeout_ms)


def _delete_session(page: Any, session_id: str, timeout_ms: int) -> None:
    row = page.locator(f'[data-session-row="{session_id}"]')
    row.wait_for(state="visible", timeout=timeout_ms)
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlparse(response.url).path.endswith(f"/sessions/{session_id}"),
        timeout=timeout_ms,
    ) as response_info:
        row.locator("[data-delete-session]").click()
        page.locator("[data-delete-confirm]").click()
    response = response_info.value
    if response.status != 204 or not _private_response(response):
        raise VerificationError("delete flow did not return a private HTTP 204")
    row.wait_for(state="detached", timeout=timeout_ms)


def _layout_metrics(page: Any, mobile: bool) -> dict[str, Any]:
    metrics = page.evaluate(
        """
        () => {
          const doc = document.documentElement;
          const scroll = document.scrollingElement;
          const composer = document.querySelector('[data-composer]');
          const form = document.querySelector('[data-composer-form]');
          const conversation = document.querySelector('[data-conversation]');
          const rect = form.getBoundingClientRect();
          return {
            inner_width: window.innerWidth,
            scroll_width: doc.scrollWidth,
            page_scroll_height: scroll.scrollHeight,
            page_client_height: scroll.clientHeight,
            page_scroll_top: scroll.scrollTop,
            conversation_scroll_top: conversation.scrollTop,
            composer_font_px: Number.parseFloat(getComputedStyle(composer).fontSize),
            composer_visible: rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight,
            composer_focused: document.activeElement === composer,
          };
        }
        """
    )
    if metrics["scroll_width"] > metrics["inner_width"]:
        raise VerificationError("horizontal overflow detected")
    if mobile and metrics["composer_font_px"] < 16:
        raise VerificationError("mobile composer font is below 16px")
    if not metrics["composer_visible"] or not metrics["composer_focused"]:
        raise VerificationError("composer is not visible and focused")

    metrics["page_scroll_changed"] = None
    metrics["conversation_scroll_unchanged"] = None
    if mobile:
        before = page.evaluate(
            """() => ({
              page: document.scrollingElement.scrollTop,
              feed: document.querySelector('[data-conversation]').scrollTop,
            })"""
        )
        page.evaluate("window.scrollBy(0, Math.min(240, document.scrollingElement.scrollHeight))")
        page.wait_for_timeout(100)
        after = page.evaluate(
            """() => ({
              page: document.scrollingElement.scrollTop,
              feed: document.querySelector('[data-conversation]').scrollTop,
            })"""
        )
        metrics["page_scroll_changed"] = after["page"] > before["page"]
        metrics["conversation_scroll_unchanged"] = after["feed"] == before["feed"]
        if not metrics["page_scroll_changed"] or not metrics["conversation_scroll_unchanged"]:
            raise VerificationError("mobile scroll is trapped in the nested conversation feed")
    return metrics


def _verify_viewport(
    browser: Any,
    *,
    name: str,
    width: int,
    height: int,
    base_url: str,
    output: Path,
    identifier: str,
    password: str,
    timeout_ms: int,
) -> dict[str, Any]:
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    console_errors: list[str] = []
    page_errors: list[str] = []
    private_contracts: list[bool] = []
    request_counts = {"question": 0, "poll": 0, "history": 0, "delete": 0}
    poll_observations: list[dict[str, Any]] = []

    def on_console(message: Any) -> None:
        if message.type == "error":
            console_errors.append(message.text)

    def on_response(response: Any) -> None:
        path = urlparse(response.url).path
        if not path.startswith("/api/radar-ask/"):
            return
        private_contracts.append(_private_response(response))
        if path == "/api/radar-ask/questions":
            request_counts["question"] += 1
        elif "/runs/" in path:
            request_counts["poll"] += 1
            try:
                body = response.json()
            except Exception:
                body = None
            poll_observations.append(
                {
                    "path": path,
                    "http_status": response.status,
                    "run_id": body.get("run_id") if isinstance(body, dict) else None,
                    "status": body.get("status") if isinstance(body, dict) else None,
                    "private": _private_response(response),
                }
            )
        elif "/sessions" in path and response.request.method == "DELETE":
            request_counts["delete"] += 1
        elif "/sessions" in path:
            request_counts["history"] += 1

    page.on("console", on_console)
    page.on("pageerror", lambda error: page_errors.append(str(error)[:500]))
    page.on("response", on_response)

    page.goto(base_url, wait_until="domcontentloaded")
    login = context.request.post(
        f"{base_url}/api/auth/login",
        data={"identifier": identifier, "password": password},
        headers={"Origin": base_url},
    )
    if login.status != 200:
        raise VerificationError(f"seeded login failed with HTTP {login.status}")
    login_payload = login.json()
    login_user = login_payload.get("user") if isinstance(login_payload, dict) else None
    if not isinstance(login_user, dict) or login_user.get("tier") != "admin":
        raise VerificationError("seeded rendered user must be Admin for the four-question flow")
    page.goto(f"{base_url}/hoi-radar-bds", wait_until="networkidle")
    composer = page.locator("[data-composer]")
    composer.wait_for(state="visible")
    composer.focus()

    fast, fast_ms = _submit(
        page,
        depth="fast",
        question="Hôm nay khu vực nào có nhiều tin giảm giá?",
        timeout_ms=timeout_ms,
    )
    page.locator(f'[data-run-id="{fast["run_id"]}"]').wait_for(state="visible", timeout=timeout_ms)
    _open_sources(page, timeout_ms)
    page.locator("[data-new-conversation]").click()

    deep, deep_enqueue_ms = _submit(
        page,
        depth="deep",
        question="Nghiên cứu sâu lô 123 bằng dữ liệu giả kiểm thử.",
        timeout_ms=timeout_ms,
    )
    if deep.get("status") not in {"queued", "created", "running"}:
        raise VerificationError("Deep submit did not return a queued state")
    page.locator(f'[data-run-id="{deep["run_id"]}"] [data-answer]').wait_for(
        state="visible",
        timeout=timeout_ms,
    )
    matching_polls = [
        observation
        for observation in poll_observations
        if observation["path"] == f'/api/radar-ask/runs/{deep["run_id"]}'
        and observation["http_status"] == 200
        and observation["run_id"] == deep["run_id"]
        and observation["status"] in {"completed", "clarifying", "insufficient"}
        and observation["private"]
    ]
    if not matching_polls:
        raise VerificationError("Deep poll did not return a private terminal response for the submitted run")

    _open_history(page, name == "mobile", timeout_ms)
    _delete_session(page, str(fast["session_id"]), timeout_ms)
    if name == "mobile" and page.locator("[data-history-close]").is_visible():
        page.locator("[data-history-close]").click()
    composer.focus()
    layout = _layout_metrics(page, name == "mobile")

    relevant_console = _application_console_errors(console_errors)
    if relevant_console or page_errors:
        raise VerificationError("relevant console/page errors were observed")
    if not private_contracts or not all(private_contracts):
        raise VerificationError("a Radar Ask response missed private/no-store headers")
    if request_counts["question"] != 2 or request_counts["poll"] < 1:
        raise VerificationError("submit/poll request count contract failed")

    screenshot = output / f"{name}.png"
    page.screenshot(path=str(screenshot), full_page=True)
    result = {
        "viewport": {"width": width, "height": height},
        "fast_ms": round(fast_ms, 3),
        "deep_enqueue_ms": round(deep_enqueue_ms, 3),
        "request_counts": request_counts,
        "deep_terminal_poll_count": len(matching_polls),
        "private_response_count": len(private_contracts),
        "relevant_console_errors": relevant_console,
        "page_errors": page_errors,
        "layout": layout,
        "screenshot": screenshot.name,
    }
    context.close()
    return result


def main() -> int:
    args = _arguments()
    try:
        base_url, output, identifier, password = _validated_config(args)
    except VerificationError as exc:
        print(f"configuration_error={exc}", file=sys.stderr)
        return 2
    if args.check_config:
        print("configuration=ok local_fake_provider=required artifacts=ignored")
        return 0

    try:
        capability = _verify_server_capability(base_url, args.timeout_ms)
    except VerificationError as exc:
        print(f"configuration_error={exc}", file=sys.stderr)
        return 2

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "tool_blocker=python_playwright_unavailable; install is intentionally not attempted",
            file=sys.stderr,
        )
        return 3

    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 1,
        "target": "loopback_fake_provider",
        "server_capability": capability,
        "viewports": {},
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not args.headed)
            for name, width, height in VIEWPORTS:
                report["viewports"][name] = _verify_viewport(
                    browser,
                    name=name,
                    width=width,
                    height=height,
                    base_url=base_url,
                    output=output,
                    identifier=identifier,
                    password=password,
                    timeout_ms=args.timeout_ms,
                )
            browser.close()
    except (VerificationError, PlaywrightError, TimeoutError) as exc:
        print(f"verification_failed={type(exc).__name__}: {exc}", file=sys.stderr)
        return 4

    (output / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "ok", "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

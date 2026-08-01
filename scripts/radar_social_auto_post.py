#!/usr/bin/env python3
"""Auto-post the latest Radar BDS social queue item to the Facebook Page.

Cron-safe wrapper:
1. Ensure the dedicated browser-use Chrome/CDP worker is reachable.
2. Create a `radar_social_queue.v1` JSON for the latest `/tin-tuc` article.
3. Publish to the Radar BDS Facebook Page via `scripts/browser_use_page_post.py`.
4. Record a lightweight posted-state key to avoid duplicate reposts.

No passwords, cookies, or Facebook credentials are read or written here. The
script relies on the already-authenticated Chrome profile at
`/home/hermesops/.browser-profiles/radar-social/chrome-profile`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path("/opt/radar-bds/current")
QUEUE_SCRIPT = REPO / "scripts/radar_social_queue.py"
POST_SCRIPT = REPO / "scripts/browser_use_page_post.py"
START_BROWSER = Path("/home/hermesops/radar-browser-use/start-radar-social-browser.sh")
CDP_URL = "http://127.0.0.1:9224"
STATE_PATH = Path("/opt/radar-bds/var/social_queue/posted_slugs.json")
# Use a dedicated Hermes-owned queue dir for auto-posting. The SEO publisher can
# create same-day queue files in /opt/radar-bds/var/social_queue as the `radar`
# user; overwriting those from Hermes cron causes PermissionError.
QUEUE_DIR = Path("/opt/radar-bds/var/social_queue/autopost")
RUN_DIR = Path("/opt/radar-bds/var/browser_use_runs")


def log(message: str) -> None:
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def cdp_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=4) as resp:  # noqa: S310 - localhost only
            return resp.status == 200
    except Exception:
        return False


def ensure_browser() -> None:
    if cdp_ready():
        log("Chrome CDP already reachable at 127.0.0.1:9224")
        return
    if not START_BROWSER.exists():
        raise SystemExit(f"Browser start script missing: {START_BROWSER}")
    log("Starting dedicated Radar Social Chrome worker")
    subprocess.Popen(
        [str(START_BROWSER)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(REPO),
    )
    for _ in range(30):
        time.sleep(1)
        if cdp_ready():
            log("Chrome CDP is ready")
            return
    raise SystemExit("Chrome CDP did not become ready within 30s")


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"posted": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"posted": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


def valid_facebook_permalink(url: str) -> bool:
    return bool(
        isinstance(url, str)
        and url.startswith("https://www.facebook.com/")
        and ("/posts/" in url or "/permalink.php" in url or "story_fbid=" in url)
    )


def posted_today(posted: dict, *, today: dt.date | None = None) -> tuple[bool, dict]:
    today = today or dt.datetime.now().astimezone().date()
    for item in posted.values():
        if not isinstance(item, dict):
            continue
        post_url = item.get("post_url") or ((item.get("browser_result") or {}).get("permalink"))
        if not valid_facebook_permalink(str(post_url or "")):
            continue
        posted_at = str(item.get("posted_at") or "")[:10]
        if posted_at == today.isoformat():
            return True, item
    return False, {}


def parse_post_wrapper_stdout(stdout: str) -> dict:
    try:
        data = json.loads((stdout or "").strip())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Publish wrapper returned 0 but stdout was not JSON: {exc}") from exc
    browser_result = data.get("browser_result") if isinstance(data, dict) else None
    if not isinstance(browser_result, dict) or not valid_facebook_permalink(str(browser_result.get("permalink") or "")):
        raise SystemExit(f"Publish wrapper missing verified permalink: {str(stdout)[-1000:]}")
    return data


def article_candidates() -> list[tuple[str, str]]:
    """Newest /tin-tuc article slugs with their publish/modified dates."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from config.seo_articles import SEO_ARTICLES  # pylint: disable=import-error

    candidates: list[tuple[str, str]] = []
    for slug, page in SEO_ARTICLES.items():
        if not isinstance(page, dict) or not str(page.get("path", "")).startswith("/tin-tuc/"):
            continue
        article = page.get("article") or {}
        article_date = str(article.get("modified_at") or article.get("published_at") or "unknown-date")
        candidates.append((article_date, str(slug)))
    return sorted(candidates, reverse=True)


def create_queue(slug: str = "latest") -> Path:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [str(QUEUE_SCRIPT), "--slug", slug, "--mode", "publish", "--out-dir", str(QUEUE_DIR)]
    proc = subprocess.run(cmd, cwd=str(REPO), text=True, capture_output=True, timeout=60, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"Queue creation failed for slug={slug}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    first = (proc.stdout.strip().splitlines() or [""])[0]
    path = Path(first)
    if not path.exists():
        raise SystemExit(f"Queue script did not return an existing file. Output:\n{proc.stdout}")
    log(f"Queue created: {path}")
    return path


def create_unposted_queue(posted: dict) -> Path:
    """Create queue for newest article not already recorded as posted.

    This avoids reposting the same latest article when Page Care is manually
    rerun, while still regenerating caption/visual metadata from current code.
    """
    for article_date, slug in article_candidates():
        key = f"{slug}:{article_date}"
        if key in posted:
            log(f"Skip already posted candidate: {key}")
            continue
        return create_queue(slug)
    raise SystemExit("No unposted /tin-tuc article candidate found for Page Care")


def queue_key(queue_path: Path) -> tuple[str, str, str]:
    data = json.loads(queue_path.read_text(encoding="utf-8"))
    source = data.get("source", {})
    slug = str(source.get("slug") or queue_path.stem)
    article_date = str(source.get("article_date") or "unknown-date")
    key = f"{slug}:{article_date}"
    url = str(source.get("url") or "")
    return key, slug, url


def publish(queue_path: Path) -> dict:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    # Visual uploads + Facebook async publish can exceed 4 minutes. Keep the
    # wrapper timeout above the browser worker timeout so the worker can return
    # verification output instead of being killed after a successful post.
    cmd = [str(POST_SCRIPT), "--queue", str(queue_path), "--mode", "publish", "--yes", "--timeout", "420"]
    proc = subprocess.run(cmd, cwd=str(REPO), text=True, capture_output=True, timeout=500, check=False)
    record = {
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-3000:],
        "stderr_tail": proc.stderr[-3000:],
    }
    if proc.returncode != 0:
        raise SystemExit(
            "Facebook Page publish failed\n"
            f"STDOUT:\n{proc.stdout[-3000:]}\nSTDERR:\n{proc.stderr[-3000:]}"
        )
    wrapper_record = parse_post_wrapper_stdout(proc.stdout)
    browser_result = wrapper_record["browser_result"]
    record["post_url"] = browser_result["permalink"]
    record["browser_result"] = browser_result
    record["screenshot"] = wrapper_record.get("screenshot")
    return record


def main() -> int:
    os.chdir(REPO)
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    ensure_browser()
    state = load_state()
    posted = state.setdefault("posted", {})
    already_done, done_item = posted_today(posted)
    if already_done:
        post_url = done_item.get("post_url") or ((done_item.get("browser_result") or {}).get("permalink"))
        print("## @rb Daily Facebook Page Care")
        print("- KPI hôm nay: ĐẠT")
        print(f"- Published Page post: already posted today: {post_url}")
        if done_item.get("queue"):
            print(f"- Source queue/article: {done_item.get('queue')}")
        if done_item.get("visual"):
            print(f"- Visual: {done_item.get('visual')}")
        print(f"- Verification: posted_slugs.json has today's valid Facebook permalink")
        return 0
    queue_path = create_unposted_queue(posted)
    key, slug, url = queue_key(queue_path)
    if key in posted:
        raise SystemExit(f"Internal dedupe error: selected already-posted queue {key}")
    log(f"Publishing social item: {key}")
    result = publish(queue_path)
    posted[key] = {
        "slug": slug,
        "url": url,
        "queue": str(queue_path),
        "posted_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "post_url": result.get("post_url"),
        "screenshot": result.get("screenshot"),
        "browser_result": result.get("browser_result"),
        "result": result,
    }
    save_state(state)
    data = json.loads(queue_path.read_text(encoding="utf-8"))
    content = data.get("content") or {}
    print("## @rb Daily Facebook Page Care")
    print("- KPI hôm nay: ĐẠT")
    print(f"- Published Page post: {result.get('post_url')}")
    print(f"- Source queue/article: {queue_path} → {url}")
    print(f"- Visual: {content.get('visual_path') or content.get('image_path') or ''} · {content.get('visual_style') or 'legacy'}")
    print(f"- Caption angle: {str(content.get('message') or '').splitlines()[0][:160]}")
    print("- Self-comment/pin: not attempted by deterministic KPI autopost")
    print("- Verification: browser_result ok=true + verified_text=true + valid Facebook permalink")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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


def create_queue() -> Path:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [str(QUEUE_SCRIPT), "--slug", "latest", "--mode", "publish", "--out-dir", str(QUEUE_DIR)]
    proc = subprocess.run(cmd, cwd=str(REPO), text=True, capture_output=True, timeout=60, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"Queue creation failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    first = (proc.stdout.strip().splitlines() or [""])[0]
    path = Path(first)
    if not path.exists():
        raise SystemExit(f"Queue script did not return an existing file. Output:\n{proc.stdout}")
    log(f"Queue created: {path}")
    return path


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
    cmd = [str(POST_SCRIPT), "--queue", str(queue_path), "--mode", "publish", "--yes", "--timeout", "240"]
    proc = subprocess.run(cmd, cwd=str(REPO), text=True, capture_output=True, timeout=300, check=False)
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
    return record


def main() -> int:
    os.chdir(REPO)
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    ensure_browser()
    queue_path = create_queue()
    key, slug, url = queue_key(queue_path)
    state = load_state()
    posted = state.setdefault("posted", {})
    if key in posted:
        log(f"SKIP: already auto-posted {key} at {posted[key].get('posted_at')}")
        print(f"@rb social auto-post skipped: already posted `{slug}` ({url})")
        return 0
    log(f"Publishing latest social item: {key}")
    result = publish(queue_path)
    posted[key] = {
        "slug": slug,
        "url": url,
        "queue": str(queue_path),
        "posted_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "result": result,
    }
    save_state(state)
    print("@rb social auto-post OK")
    print(f"Slug: {slug}")
    print(f"URL: {url}")
    print(f"Queue: {queue_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

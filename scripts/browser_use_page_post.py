#!/usr/bin/env python3
"""Post or prepare a Radar BDS Facebook Page post via browser-use.

This wrapper keeps LLM token use low: it reads one social queue JSON and sends a
small deterministic browser-use program to the browser harness. It is intended
for the already-authenticated Radar Social Chrome profile documented in
`docs/browser-use-social-ops.md`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

BROWSER_USE = Path("/home/hermesops/radar-browser-use/.venv/bin/browser-use")
DEFAULT_CDP_URL = "http://127.0.0.1:9224"
DEFAULT_ARTIFACT_DIR = Path("/home/hermesops/radar-browser-use/artifacts")
DEFAULT_RUN_DIR = Path("/opt/radar-bds/var/browser_use_runs")


def _load_queue(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "radar_social_queue.v1":
        raise SystemExit(f"Unsupported queue schema in {path}: {data.get('schema')}")
    msg = data.get("content", {}).get("message")
    if not msg:
        raise SystemExit(f"Queue item has no content.message: {path}")
    return data


def _program(queue: dict, mode: str, screenshot_path: str) -> str:
    page_url = queue.get("target", {}).get("page_url") or "https://www.facebook.com/radarbdsvn/"
    message = queue["content"]["message"]
    # The code below runs inside browser-use CLI, where helper functions are pre-imported.
    return f"""
import json, time
page_url = {page_url!r}
message = {message!r}
mode = {mode!r}
screenshot_path = {screenshot_path!r}

new_tab(page_url)
wait_for_load()
js('window.scrollTo(0, 0)')
time.sleep(2)

def ax_nodes():
    return cdp('Accessibility.getFullAXTree').get('nodes', [])

def props(node):
    return {{p.get('name'): (p.get('value') or {{}}).get('value') for p in node.get('properties', [])}}

def center(backend_id):
    box = cdp('DOM.getBoxModel', backendNodeId=backend_id)['model']['content']
    return sum(box[0::2]) / 4, sum(box[1::2]) / 4

def click_backend(backend_id):
    x, y = center(backend_id)
    click_at_xy(x, y)
    time.sleep(1.5)

# Open composer. Facebook may label this in English on the profile.
composer = None
for n in ax_nodes():
    role = (n.get('role') or {{}}).get('value', '')
    name = (n.get('name') or {{}}).get('value', '')
    if role == 'button' and ("What's on your mind" in name or 'on your mind' in name or 'Bạn đang nghĩ' in name):
        composer = n.get('backendDOMNodeId')
        break
if not composer:
    raise RuntimeError('Composer button not found. Stop before taking any account action.')
click_backend(composer)

# Find composer textbox and type message.
textbox = None
for n in ax_nodes():
    role = (n.get('role') or {{}}).get('value', '')
    name = (n.get('name') or {{}}).get('value', '')
    p = props(n)
    if role == 'textbox' and p.get('editable') == 'richtext':
        textbox = n.get('backendDOMNodeId')
        break
if not textbox:
    raise RuntimeError('Post textbox not found after opening composer.')
click_backend(textbox)
type_text(message)
time.sleep(5)

# Screenshot after content/link preview loads.
capture_screenshot(path=screenshot_path, full=False, max_dim=1800)

if mode == 'prepare':
    print(json.dumps({{'ok': True, 'mode': mode, 'prepared': True, 'screenshot': screenshot_path}}, ensure_ascii=False))
    raise SystemExit(0)

if mode != 'publish':
    raise RuntimeError(f'Unsupported mode: {{mode}}')

# Some Page composer flows require Next before the final Post button.
for n in ax_nodes():
    role = (n.get('role') or {{}}).get('value', '')
    name = (n.get('name') or {{}}).get('value', '')
    p = props(n)
    if role == 'button' and name == 'Next' and not p.get('disabled'):
        click_backend(n.get('backendDOMNodeId'))
        break

time.sleep(2)
post_button = None
for n in ax_nodes():
    role = (n.get('role') or {{}}).get('value', '')
    name = (n.get('name') or {{}}).get('value', '')
    p = props(n)
    if role == 'button' and name in ('Post', 'Đăng') and not p.get('disabled'):
        post_button = n.get('backendDOMNodeId')
        break
if not post_button:
    raise RuntimeError('Final Post button not found or disabled.')
click_backend(post_button)
for _ in range(12):
    time.sleep(1)

# Verify a distinctive text prefix appears on the page.
js('window.scrollTo(0, 0)')
time.sleep(2)
needle = message.split('\n', 1)[0][:60]
found = False
for n in ax_nodes():
    name = (n.get('name') or {{}}).get('value', '')
    if needle and needle in name:
        found = True
        break
capture_screenshot(path=screenshot_path, full=False, max_dim=1800)
print(json.dumps({{'ok': found, 'mode': mode, 'verified_text': found, 'needle': needle, 'screenshot': screenshot_path, 'page_info': page_info()}}, ensure_ascii=False))
if not found:
    raise RuntimeError('Post action attempted but verification text was not found.')
"""


def run(args: argparse.Namespace) -> dict:
    queue_path = Path(args.queue).resolve()
    queue = _load_queue(queue_path)
    if args.mode == "dry-run":
        result = {
            "ok": True,
            "mode": "dry-run",
            "queue": str(queue_path),
            "page_url": queue.get("target", {}).get("page_url"),
            "message_preview": queue.get("content", {}).get("message", "")[:500],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    if args.mode == "publish" and not args.yes:
        raise SystemExit("Refusing to publish without --yes. Use --mode prepare for review mode.")
    if not BROWSER_USE.exists():
        raise SystemExit(f"browser-use CLI not found: {BROWSER_USE}")

    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    screenshot_path = str(artifact_dir / f"{stamp}-{queue_path.stem}-{args.mode}.png")
    program = _program(queue, args.mode, screenshot_path)
    env = os.environ.copy()
    env["BU_CDP_URL"] = args.cdp_url
    proc = subprocess.run(
        [str(BROWSER_USE)],
        input=program,
        text=True,
        capture_output=True,
        env=env,
        timeout=args.timeout,
        check=False,
    )
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / f"{stamp}-{queue_path.stem}-{args.mode}.json"
    record = {
        "queue": str(queue_path),
        "mode": args.mode,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "screenshot": screenshot_path,
    }
    log_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish/prepare Radar BDS social queue item via browser-use.")
    parser.add_argument("--queue", required=True, help="Path to radar_social_queue.v1 JSON file")
    parser.add_argument("--mode", default="dry-run", choices=["dry-run", "prepare", "publish"])
    parser.add_argument("--yes", action="store_true", help="Required for --mode publish")
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--timeout", type=int, default=180)
    run(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

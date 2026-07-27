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
    content = queue.get("content", {})
    message = content["message"]
    image = str(content.get("visual_path") or content.get("image") or "").strip()
    if image and not Path(image).exists():
        raise SystemExit(f"Queue visual/image file missing: {image}")
    needle = message.split("\n", 1)[0][:70]
    # The code below runs inside browser-use CLI, where helper functions are pre-imported.
    return f"""
import json, time
page_url = {page_url!r}
message = {message!r}
image = {image!r}
needle = {needle!r}
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
time.sleep(3)

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

if image:
    # Upload only through the file input inside the one composer that already contains our caption.
    caption_dialogs = js("[...document.querySelectorAll('[role=dialog]')].filter(d => (d.innerText||'').includes(" + json.dumps(needle) + ")).length")
    if caption_dialogs != 1:
        raise RuntimeError('Expected exactly one caption composer, found ' + str(caption_dialogs))
    doc = cdp('DOM.getDocument', depth=1)['root']['nodeId']
    ids = cdp('DOM.querySelectorAll', nodeId=doc, selector='[role="dialog"] input[type="file"]')['nodeIds']
    if len(ids) != 1:
        raise RuntimeError('Expected one composer file input, found ' + str(len(ids)))
    cdp('DOM.setFileInputFiles', nodeId=ids[0], files=[image])
    time.sleep(8)
    caption_dialogs = js("[...document.querySelectorAll('[role=dialog]')].filter(d => (d.innerText||'').includes(" + json.dumps(needle) + ") && d.querySelector('img')).length")
    if caption_dialogs != 1:
        raise RuntimeError('Caption and visual are not in the same composer')

# Screenshot after content/link preview loads. Only dismiss hashtag suggestions
# when hashtags are present; pressing Escape on plain native posts can close the
# composer and leave an unpublished inline draft.
if '#' in message:
    try:
        press_key('Escape')
        time.sleep(1)
    except Exception:
        pass
capture_screenshot(path=screenshot_path, full=False, max_dim=1800)

if mode == 'prepare':
    print(json.dumps({{'ok': True, 'mode': mode, 'prepared': True, 'screenshot': screenshot_path}}, ensure_ascii=False))
    raise SystemExit(0)

if mode != 'publish':
    raise RuntimeError(f'Unsupported mode: {{mode}}')

def verified_on_page():
    needle = message.split('\\n', 1)[0][:60]
    # New Page posts can appear lower than the hero/profile cards after publish,
    # especially when a visual is attached. Scan the rendered timeline before
    # declaring a false negative.
    for y in (0, 900, 1800, 3200, 5200, 7600):
        js('window.scrollTo(0, ' + str(y) + ')')
        time.sleep(1.5)
        nodes = ax_nodes()
        has_dialog = any(
            (n.get('role') or {{}}).get('value', '') == 'dialog'
            and 'Create post' in (((n.get('name') or {{}}).get('value', '')) or '')
            for n in nodes
        )
        found_article = False
        for n in nodes:
            role = (n.get('role') or {{}}).get('value', '')
            name = (n.get('name') or {{}}).get('value', '')
            if role == 'article' and needle and needle in name:
                found_article = True
                break
        if found_article and not has_dialog:
            return True, needle
    return False, needle

# Current Page UI is normally: composer -> Next -> Post settings -> Post.
# Some variants publish/close after Next; verify before looking for final Post.
for n in ax_nodes():
    role = (n.get('role') or {{}}).get('value', '')
    name = (n.get('name') or {{}}).get('value', '')
    p = props(n)
    if role == 'button' and name in ('Next', 'Tiếp') and not p.get('disabled'):
        click_backend(n.get('backendDOMNodeId'))
        break

time.sleep(5)
found, needle = verified_on_page()
if found:
    capture_screenshot(path=screenshot_path, full=False, max_dim=1800)
    print(json.dumps({{'ok': True, 'mode': mode, 'verified_text': True, 'needle': needle, 'screenshot': screenshot_path, 'page_info': page_info(), 'flow': 'next_published'}}, ensure_ascii=False))
    raise SystemExit(0)

post_button = None
for n in ax_nodes():
    role = (n.get('role') or {{}}).get('value', '')
    name = (n.get('name') or {{}}).get('value', '')
    p = props(n)
    if role == 'button' and name in ('Post', 'Đăng') and not p.get('disabled'):
        post_button = n.get('backendDOMNodeId')
        break
if not post_button:
    raise RuntimeError('Final Post button not found or disabled, and Next did not verify as published.')
click_backend(post_button)
time.sleep(3)
# Facebook Page may ask whether to add a CTA button (e.g. Call Now) after Post.
# For organic care posts, choose Not now; this completes publishing in current UI.
for n in ax_nodes():
    role = (n.get('role') or {{}}).get('value', '')
    name = (n.get('name') or {{}}).get('value', '')
    p = props(n)
    if role == 'button' and name in ('Not now', 'Không phải bây giờ') and not p.get('disabled'):
        click_backend(n.get('backendDOMNodeId'))
        break
found, needle = False, message.split('\\n', 1)[0][:60]
# Native Page posts can take a little longer to appear in the feed after the
# CTA modal is dismissed. Poll before failing so cron does not report false negatives.
for _ in range(25):
    found, needle = verified_on_page()
    if found:
        break
    time.sleep(2)
capture_screenshot(path=screenshot_path, full=False, max_dim=1800)
print(json.dumps({{'ok': found, 'mode': mode, 'verified_text': found, 'needle': needle, 'screenshot': screenshot_path, 'page_info': page_info(), 'flow': 'post_button'}}, ensure_ascii=False))
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

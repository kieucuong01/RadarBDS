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
BROWSER_USE_CWD = Path("/home/hermesops/radar-browser-use")
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


def _extract_browser_result(stdout: str) -> dict:
    """Return the last JSON status object printed by the browser-use program."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "ok" in data:
            return data
    return {}


def _is_valid_facebook_permalink(url: str) -> bool:
    return bool(
        isinstance(url, str)
        and url.startswith("https://www.facebook.com/")
        and ("/posts/" in url or "/permalink.php" in url or "story_fbid=" in url)
    )


def _is_valid_facebook_photo_permalink(url: str) -> bool:
    return bool(
        isinstance(url, str)
        and url.startswith("https://www.facebook.com/")
        and ("/photo/" in url or "/photo.php" in url)
    )


def _validate_publish_success(record: dict, *, require_visual: bool = False, require_comment: bool = False) -> dict:
    """Hard gate for cron KPI: success requires a real post permalink."""
    browser_result = _extract_browser_result(str(record.get("stdout") or ""))
    if not browser_result:
        raise SystemExit("Publish returned 0 but no browser verification JSON was found")
    if not browser_result.get("ok") or not browser_result.get("verified_text"):
        raise SystemExit(f"Publish did not verify as a real Page article: {browser_result}")
    permalink = browser_result.get("permalink") or ""
    if not _is_valid_facebook_permalink(permalink):
        raise SystemExit(f"Publish verification missing valid Facebook permalink: {browser_result}")
    if require_visual:
        photo_permalink = browser_result.get("photo_permalink") or ""
        if not browser_result.get("verified_visual") or not _is_valid_facebook_photo_permalink(photo_permalink):
            raise SystemExit(f"Publish verification missing native visual/photo permalink: {browser_result}")
    if require_comment and not browser_result.get("verified_comment"):
        raise SystemExit(f"Publish verification missing required Radar BDS self-comment: {browser_result}")
    return browser_result


def _program(queue: dict, mode: str, screenshot_path: str) -> str:
    page_url = queue.get("target", {}).get("page_url") or "https://www.facebook.com/radarbdsvn/"
    content = queue.get("content", {})
    message = content["message"]
    self_comment = str(content.get("self_comment") or "").strip()
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
self_comment = {self_comment!r}
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

# Open composer. Facebook may label this in English on the profile. Dismiss
# non-composer overlays first; stale notification popovers can intercept the
# first composer click.
try:
    press_key('Escape')
    time.sleep(1)
except Exception:
    pass
composer = None
for n in ax_nodes():
    role = (n.get('role') or {{}}).get('value', '')
    name = (n.get('name') or {{}}).get('value', '')
    if role == 'button' and ("What's on your mind" in name or 'on your mind' in name or 'Bạn đang nghĩ' in name):
        composer = n.get('backendDOMNodeId')
        break
if not composer:
    # A previous failed run can leave Facebook showing the draft as an inline
    # composer button. Re-open that draft instead of failing or typing a duplicate.
    inline_draft = js('''(() => {{
        const needle = %s;
        for (const el of [...document.querySelectorAll('[role="button"]')]) {{
            const text = el.innerText || el.textContent || '';
            const r = el.getBoundingClientRect();
            if (text.includes(needle) && r.width > 20 && r.height > 20) {{
                return {{found: true, x: r.x + r.width / 2, y: r.y + r.height / 2}};
            }}
        }}
        return {{found: false}};
    }})()''' % json.dumps(needle)) or {{'found': False}}
    if inline_draft.get('found'):
        click_at_xy(inline_draft['x'], inline_draft['y'])
        time.sleep(3)
    else:
        raise RuntimeError('Composer button not found. Stop before taking any account action.')
else:
    click_backend(composer)
    time.sleep(3)

# Find composer textbox. If Facebook expanded the draft inline first, click the
# draft button once more to open the real Create Post dialog.
def find_textbox_backend():
    for node in ax_nodes():
        role = (node.get('role') or {{}}).get('value', '')
        p = props(node)
        if role == 'textbox' and p.get('editable') == 'richtext':
            return node.get('backendDOMNodeId')
    return None

textbox = None
for _ in range(12):
    textbox = find_textbox_backend()
    if textbox:
        break
    time.sleep(1)
if not textbox:
    inline_draft = js('''(() => {{
        const needle = %s;
        for (const el of [...document.querySelectorAll('[role="button"]')]) {{
            const text = el.innerText || el.textContent || '';
            const r = el.getBoundingClientRect();
            if (text.includes(needle) && r.width > 20 && r.height > 20) {{
                return {{found: true, x: r.x + r.width / 2, y: r.y + r.height / 2}};
            }}
        }}
        return {{found: false}};
    }})()''' % json.dumps(needle)) or {{'found': False}}
    if inline_draft.get('found'):
        click_at_xy(inline_draft['x'], inline_draft['y'])
        for _ in range(12):
            time.sleep(1)
            textbox = find_textbox_backend()
            if textbox:
                break
textbox_point = {{'found': False}}
if not textbox:
    # Facebook occasionally exposes the contenteditable composer in the DOM
    # before Accessibility.getFullAXTree receives its richtext node.
    textbox_point = js('''(() => {{
        for (const el of [...document.querySelectorAll('[role="dialog"] [role="textbox"], [role="dialog"] [contenteditable="true"]')]) {{
            const r = el.getBoundingClientRect();
            if (r.width > 20 && r.height > 15) {{
                return {{found: true, x: r.x + r.width / 2, y: r.y + r.height / 2}};
            }}
        }}
        return {{found: false}};
    }})()''') or {{'found': False}}
if textbox:
    click_backend(textbox)
elif textbox_point.get('found'):
    click_at_xy(textbox_point['x'], textbox_point['y'])
    time.sleep(1)
else:
    raise RuntimeError('Post textbox not found after waiting for composer or inline draft.')
caption_already_present = js('''(() => {{
    const needle = %s;
    return [...document.querySelectorAll('[role="dialog"] [role="textbox"], [role="dialog"] [contenteditable="true"], [role="dialog"] textarea')]
        .some(el => ((el.innerText || el.value || el.textContent || '').includes(needle)));
}})()''' % json.dumps(needle))
if not caption_already_present:
    type_text(message)
time.sleep(5)

if image:
    # Link previews, avatars and Page logos are normal <img> elements. A native
    # composer upload is represented by a blob: image; only that counts.
    caption_has_native_visual = js('''[...document.querySelectorAll('[role=dialog]')].some(d => (d.innerText||'').includes(%s) && d.querySelector('img[src^="blob:"]'))''' % json.dumps(needle))
    if not caption_has_native_visual:
        doc = cdp('DOM.getDocument', depth=1)['root']['nodeId']
        ids = cdp('DOM.querySelectorAll', nodeId=doc, selector='[role="dialog"] input[type="file"]')['nodeIds']
        candidates = []
        for node_id in ids:
            raw = cdp('DOM.getAttributes', nodeId=node_id).get('attributes', [])
            attrs = dict(zip(raw[0::2], raw[1::2]))
            accept = attrs.get('accept', '').lower()
            if 'image' in accept:
                candidates.append((node_id, 'video' not in accept))
        image_only = [node_id for node_id, only in candidates if only]
        selected = image_only[0] if image_only else (candidates[0][0] if candidates else None)
        if not selected:
            raise RuntimeError('No image-capable composer file input found')
        obj = cdp('DOM.resolveNode', nodeId=selected)['object']['objectId']
        cdp('DOM.setFileInputFiles', objectId=obj, files=[image])
        for _ in range(20):
            time.sleep(1)
            caption_has_native_visual = js('''[...document.querySelectorAll('[role=dialog]')].some(d => (d.innerText||'').includes(%s) && d.querySelector('img[src^="blob:"]'))''' % json.dumps(needle))
            if caption_has_native_visual:
                break
    if not caption_has_native_visual:
        raise RuntimeError('Queue visual upload produced no native blob preview in the caption composer')

# Do not press Escape after typing. In current Facebook Page UI, Escape closes
# the whole composer into an inline draft even when no hashtag suggestion is
# visible. Next/Post controls remain usable with harmless suggestions present.
capture_screenshot(path=screenshot_path, full=False, max_dim=1800)

if mode == 'prepare':
    print(json.dumps({{'ok': True, 'mode': mode, 'prepared': True, 'screenshot': screenshot_path}}, ensure_ascii=False))
    raise SystemExit(0)

if mode != 'publish':
    raise RuntimeError(f'Unsupported mode: {{mode}}')

def verified_on_page():
    needle = message.split('\\n', 1)[0][:60]
    # New Page posts can appear lower than the hero/profile cards after publish,
    # especially when a visual is attached. Success must be a real timeline
    # article with a persistent Facebook permalink; composer/body text is not enough.
    for y in (0, 900, 1800, 3200, 5200, 7600):
        js('window.scrollTo(0, ' + str(y) + ')')
        time.sleep(1.5)
        nodes = ax_nodes()
        has_dialog = any(
            (n.get('role') or {{}}).get('value', '') == 'dialog'
            and 'Create post' in (((n.get('name') or {{}}).get('value', '')) or '')
            for n in nodes
        )
        post = {{'found': False, 'permalink': '', 'photo_permalink': '', 'article_text': ''}}
        try:
            post = js('''(() => {{
                const needle = %s;
                const validPermalink = href => !!href && (
                    href.includes('/posts/') || href.includes('/permalink.php') || href.includes('story_fbid=')
                );
                for (const article of [...document.querySelectorAll('[role="article"]')]) {{
                    const text = article.innerText || '';
                    if (!text.includes(needle)) continue;
                    const draftHasNeedle = [...article.querySelectorAll('[contenteditable="true"], textarea, [role="textbox"]')]
                        .some(el => ((el.innerText || el.value || el.textContent || '').includes(needle)));
                    if (draftHasNeedle) continue;
                    const links = [...article.querySelectorAll('a')].map(a => a.href || '').filter(Boolean);
                    const permalink = links.find(validPermalink) || '';
                    if (!permalink) continue;
                    const photo_permalink = links.find(href => href.includes('/photo/') || href.includes('/photo.php')) || '';
                    return {{found: true, permalink, photo_permalink, article_text: text.slice(0, 500)}};
                }}
                return {{found: false, permalink: '', photo_permalink: '', article_text: ''}};
            }})()''' % json.dumps(needle)) or {{'found': False, 'permalink': '', 'photo_permalink': '', 'article_text': ''}}
        except Exception:
            post = {{'found': False, 'permalink': '', 'photo_permalink': '', 'article_text': ''}}
        if post.get('found') and not has_dialog:
            photo_permalink = post.get('photo_permalink') or ''
            if image and not photo_permalink:
                continue
            return True, needle, post.get('permalink') or '', photo_permalink
    return False, needle, '', ''

def add_self_comment(permalink):
    if not self_comment:
        return True, ''
    comment_needle = self_comment.split('\\n', 1)[0][:80]
    new_tab(permalink)
    wait_for_load()
    time.sleep(4)
    focused = False
    for y in (0, 650, 1300, 2200):
        js('window.scrollTo(0, ' + str(y) + ')')
        time.sleep(1.2)
        target = js('''(() => {{
            const labels = /write a comment|comment as|viết bình luận|bình luận dưới tên/i;
            const selectors = '[role="textbox"], [contenteditable="true"], [aria-label]';
            for (const el of [...document.querySelectorAll(selectors)]) {{
                const label = (el.getAttribute('aria-label') || el.innerText || el.textContent || '').trim();
                const r = el.getBoundingClientRect();
                if (labels.test(label) && r.width > 40 && r.height > 18) {{
                    return {{found: true, x: r.x + r.width / 2, y: r.y + r.height / 2, label}};
                }}
            }}
            return {{found: false}};
        }})()''') or {{'found': False}}
        if target.get('found'):
            click_at_xy(target['x'], target['y'])
            time.sleep(1)
            focused = True
            break
    if not focused:
        return False, comment_needle
    type_text(self_comment)
    time.sleep(2)
    clicked = False
    for _ in range(8):
        target = js('''(() => {{
            const labels = /^(comment|bình luận|post|đăng)$/i;
            for (const el of [...document.querySelectorAll('[role="button"], button')]) {{
                const text = (el.innerText || el.ariaLabel || el.getAttribute('aria-label') || el.textContent || '').trim();
                const disabled = el.getAttribute('aria-disabled') === 'true' || el.disabled;
                const r = el.getBoundingClientRect();
                if (labels.test(text) && !disabled && r.width > 18 && r.height > 18) {{
                    return {{found: true, x: r.x + r.width / 2, y: r.y + r.height / 2, text}};
                }}
            }}
            return {{found: false}};
        }})()''') or {{'found': False}}
        if target.get('found'):
            click_at_xy(target['x'], target['y'])
            clicked = True
            break
        time.sleep(1)
    if not clicked:
        return False, comment_needle
    for _ in range(18):
        time.sleep(2)
        ok = js('''(() => {{
            const needle = %s;
            const linkNeedle = 'radarbds.vn';
            for (const article of [...document.querySelectorAll('[role="article"]')]) {{
                const text = article.innerText || '';
                if (!text.includes(needle) || !text.includes(linkNeedle)) continue;
                const draftHit = [...article.querySelectorAll('[contenteditable="true"], textarea, [role="textbox"]')]
                    .some(el => ((el.innerText || el.value || el.textContent || '').includes(needle)));
                if (!draftHit) return true;
            }}
            return false;
        }})()''' % json.dumps(comment_needle))
        if ok:
            return True, comment_needle
    return False, comment_needle

# Current Page UI is normally: composer -> Next -> Post settings -> Post.
# Click exact buttons inside the expected dialog so we do not confuse
# `Post audience` with the final `Post` button.
def click_exact_dom_button(label, dialog_regex=''):
    target = js('''(() => {{
        const label = %s;
        const patternSource = %s;
        const pattern = patternSource ? new RegExp(patternSource, 'i') : null;
        const dialogs = [...document.querySelectorAll('[role="dialog"]')];
        for (const dialog of dialogs) {{
            const dialogText = dialog.innerText || '';
            if (pattern && !pattern.test(dialogText)) continue;
            for (const el of [...dialog.querySelectorAll('[role="button"], button')]) {{
                const text = (el.innerText || el.ariaLabel || el.getAttribute('aria-label') || el.textContent || '').trim();
                const disabled = el.getAttribute('aria-disabled') === 'true' || el.disabled;
                const r = el.getBoundingClientRect();
                if (text === label && !disabled && r.width > 20 && r.height > 20) {{
                    return {{found: true, x: r.x + r.width / 2, y: r.y + r.height / 2, text}};
                }}
            }}
        }}
        return {{found: false}};
    }})()''' % (json.dumps(label), json.dumps(dialog_regex))) or {{'found': False}}
    if target.get('found'):
        click_at_xy(target['x'], target['y'])
        time.sleep(2)
        return True
    return False

flow = 'unknown'
clicked_next = click_exact_dom_button('Next', 'Create post') or click_exact_dom_button('Tiếp', 'Create post')
if clicked_next:
    flow = 'next_then_post_settings'
    time.sleep(5)
    clicked_post = click_exact_dom_button('Post', 'Post settings|Scheduling options|Publish now') or click_exact_dom_button('Đăng', 'Post settings|Scheduling options|Publish now')
    if not clicked_post:
        # Rare variant: Next itself publishes. Verify briefly before failing.
        for _ in range(10):
            found, needle, permalink, photo_permalink = verified_on_page()
            if found:
                capture_screenshot(path=screenshot_path, full=False, max_dim=1800)
                print(json.dumps({{'ok': True, 'mode': mode, 'verified_text': True, 'verified_visual': bool(photo_permalink), 'needle': needle, 'permalink': permalink, 'photo_permalink': photo_permalink, 'screenshot': screenshot_path, 'page_info': page_info(), 'flow': 'next_async_published'}}, ensure_ascii=False))
                raise SystemExit(0)
            time.sleep(2)
        raise RuntimeError('Final exact Post button not found in Post settings dialog.')
else:
    clicked_post = click_exact_dom_button('Post', 'Create post') or click_exact_dom_button('Đăng', 'Create post')
    if not clicked_post:
        raise RuntimeError('Neither Next nor exact Post button found in Create post dialog.')
    flow = 'direct_post_button'

time.sleep(3)
# Facebook Page may ask whether to add a CTA button (e.g. Call Now) after Post.
# For organic care posts, choose Not now; this completes publishing in current UI.
click_exact_dom_button('Not now') or click_exact_dom_button('Không phải bây giờ')
# Facebook may show post-publish upsell dialogs such as Product Tagging. Close
# them before verification so browser-use can finish cleanly instead of timing out.
try:
    closed_upsell = js('''(() => {{
        for (const dialog of [...document.querySelectorAll('[role="dialog"]')]) {{
            const text = dialog.innerText || '';
            if (!/Product Tagging|Add Product Tags|Explore Product/i.test(text)) continue;
            const close = dialog.querySelector('[aria-label="Close"], [aria-label="Đóng"], [role="button"][aria-label]');
            if (close) {{ close.click(); return true; }}
        }}
        return false;
    }})()''')
    if closed_upsell:
        time.sleep(2)
except Exception:
    pass
found, needle, permalink, photo_permalink = False, message.split('\\n', 1)[0][:60], '', ''
# Native Page posts can take a little longer to appear in the feed after the
# CTA modal is dismissed. Poll before failing so cron does not report false negatives.
for _ in range(25):
    found, needle, permalink, photo_permalink = verified_on_page()
    if found:
        break
    time.sleep(2)
comment_ok, comment_needle = (False, '')
if found:
    comment_ok, comment_needle = add_self_comment(permalink)
if self_comment and not comment_ok:
    found = False
capture_screenshot(path=screenshot_path, full=False, max_dim=1800)
print(json.dumps({{'ok': found, 'mode': mode, 'verified_text': found, 'verified_visual': bool(photo_permalink), 'verified_comment': comment_ok, 'comment_needle': comment_needle, 'needle': needle, 'permalink': permalink, 'photo_permalink': photo_permalink, 'screenshot': screenshot_path, 'page_info': page_info(), 'flow': flow}}, ensure_ascii=False))
if not found:
    if self_comment and not comment_ok:
        raise RuntimeError('Post was attempted but required Radar BDS self-comment was not verified.')
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

    if args.mode == "publish":
        if not args.yes:
            raise SystemExit("Refusing to publish without --yes. Use --mode prepare for review mode.")
        content = queue.get("content") or {}
        visual_path = str(content.get("visual_path") or content.get("image") or "").strip()
        if not visual_path:
            raise SystemExit("Page publish requires a native visual path in content.visual_path or content.image")
        if not Path(visual_path).is_file():
            raise SystemExit(f"Queue visual/image file missing: {visual_path}")
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
        cwd=str(BROWSER_USE_CWD),
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
    if proc.returncode == 0 and args.mode == "publish":
        try:
            record["browser_result"] = _validate_publish_success(record, require_visual=True, require_comment=bool(content.get("self_comment")))
        except SystemExit as exc:
            record["validation_error"] = str(exc)
            log_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(record, ensure_ascii=False, indent=2))
            raise
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

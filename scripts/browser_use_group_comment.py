#!/usr/bin/env python3
"""Prepare or publish one allowlisted, value-first Facebook group comment."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path

BROWSER_USE = Path('/home/hermesops/radar-browser-use/.venv/bin/browser-use')
DEFAULT_CDP_URL = 'http://127.0.0.1:9224'
DEFAULT_TARGETS = Path('/opt/radar-bds/current/config/social_group_comment_targets.json')
DEFAULT_ARTIFACT_DIR = Path('/home/hermesops/radar-browser-use/artifacts/group-comment-seeding')
DEFAULT_RUN_DIR = Path('/opt/radar-bds/var/browser_use_runs/group-comment-seeding')


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def norm_url(value: str) -> str:
    return str(value or '').split('?', 1)[0].rstrip('/') + '/'


def facebook_group_id_from_url(value: str) -> str:
    match = re.search(r'https://www\.facebook\.com/groups/([^/?#]+)/', norm_url(value), flags=re.I)
    return match.group(1) if match else ''


def contains_link(text: str) -> bool:
    label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    tld = r'(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})'
    domain = rf'(?:{label}\.)+{tld}'
    return bool(re.search(rf'https?://\S+|\bwww\.\S+|\b{domain}\b(?:/\S*)?', str(text or ''), flags=re.I))


def allowlisted(queue: dict, config: dict) -> dict:
    target = queue.get('target') or {}
    if target.get('surface') != 'group_comment':
        raise SystemExit('Refusing: queue target.surface must be group_comment')
    url = norm_url(target.get('page_url') or '')
    for item in config.get('targets', []):
        if item.get('comment_enabled') and norm_url(item.get('url') or '') == url:
            group_id = str(item.get('group_id') or '').strip()
            if not group_id:
                raise SystemExit(f'Refusing: allowlisted target lacks explicit group_id: {item.get("id")}')
            post_group_id = facebook_group_id_from_url((queue.get('source') or {}).get('post_url') or '')
            if post_group_id != group_id:
                raise SystemExit(f'Refusing: source.post_url group {post_group_id or "<missing>"} does not match allowlisted group_id {group_id}')
            return item
    raise SystemExit(f'Refusing: target is not comment-enabled in allowlist: {url}')


def validate_comment(text: str, target: dict) -> str:
    raw = str(text or '')
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise SystemExit('Refusing: comment contains newline, tab, or control characters')
    text = raw.strip()
    if not text:
        raise SystemExit('Refusing: empty comment')
    if len(text) > 700:
        raise SystemExit('Refusing: comment exceeds 700 characters')
    if not text.startswith('Radar BDS'):
        raise SystemExit('Refusing: comment must disclose Radar BDS identity')
    urls = contains_link(text)
    if urls and not target.get('comment_allow_link'):
        raise SystemExit('Refusing: target disallows links in comments')
    forbidden = ('cam kết lợi nhuận', 'giá thật 100%', 'pháp lý chuẩn 100%', 'chốt nhanh', 'cơ hội vàng')
    hits = [x for x in forbidden if x in text.casefold()]
    if hits:
        raise SystemExit('Refusing promotional claim: ' + ', '.join(hits))
    return text


def program(queue: dict, mode: str, screenshot: str, target: dict) -> str:
    source = queue.get('source') or {}
    content = queue.get('content') or {}
    guards = queue.get('guards') or {}
    post_url = str(source.get('post_url') or '').split('?', 1)[0]
    expected_group_id = str(target.get('group_id') or '').strip()
    post_group_id = facebook_group_id_from_url(post_url)
    post_needle = str(source.get('post_needle') or '').strip()[:120]
    expected_author = str(source.get('author') or '').strip()
    comment = validate_comment(content.get('comment') or '', target)
    comment_needle = comment[:90]
    permalink_expr = """(() => {
 const needle=%s;
 const anchors=[...document.querySelectorAll('a[href*="comment_id"],a[href*="reply_comment_id"]')];
 for(const a of anchors) { let p=a; for(let i=0;i<8&&p;i++,p=p.parentElement) { if((p.innerText||'').includes(needle)) return a.href; } }
 return '';
})()""" % json.dumps(comment_needle)
    if not post_url.startswith('https://www.facebook.com/groups/') or '/posts/' not in post_url:
        raise SystemExit('Refusing: invalid Facebook group post URL')
    if not expected_group_id:
        raise SystemExit('Refusing: allowlisted target lacks explicit group_id')
    if post_group_id != expected_group_id:
        raise SystemExit(f'Refusing: source.post_url group {post_group_id or "<missing>"} does not match allowlisted group_id {expected_group_id}')
    if not post_needle:
        raise SystemExit('Refusing: source.post_needle is required')
    if mode == 'publish' and not guards.get('relevance_gate_passed'):
        raise SystemExit('Refusing publish: relevance gate evidence missing')

    return f"""
import json,time
post_url={post_url!r}
expected_group={target['name']!r}
expected_author={expected_author!r}
post_needle={post_needle!r}
comment={comment!r}
comment_needle={comment_needle!r}
mode={mode!r}
screenshot={screenshot!r}

def body_text(): return js("document.body.innerText || ''") or ''
def rendered_comment_count():
    return js("(() => {{ const needle=%s; return [...document.querySelectorAll('[role=article]')].filter(e => !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length) && (e.innerText||'').includes(needle) && (e.innerText||'').includes('Radar BDS')).length; }})()" % json.dumps(comment_needle))
def stop_guard(stage):
    text=body_text().casefold()
    bad=['checkpoint','captcha','temporarily blocked','tạm thời bị chặn','account restricted','tài khoản bị hạn chế','we limit how often','chúng tôi giới hạn tần suất','identity confirmation','xác nhận danh tính']
    hits=[x for x in bad if x in text]
    if hits: raise RuntimeError(f'STOP_GUARD {{stage}}: '+','.join(hits))

def editor_count():
    return js("[...document.querySelectorAll('[contenteditable=true][role=textbox]')].filter(e => (e.getAttribute('aria-label')||'').includes('Radar BDS') && !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)).length")

def focus_editor():
    return js("(() => {{ const es=[...document.querySelectorAll('[contenteditable=true][role=textbox]')].filter(e => (e.getAttribute('aria-label')||'').includes('Radar BDS') && !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)); if(es.length!==1) return es.length; es[0].focus(); return 1; }})()")

new_tab(post_url); wait_for_load(); time.sleep(5); stop_guard('post_load')
text=body_text()
if expected_group not in text: raise RuntimeError('Expected group name not found on direct post')
if expected_author and expected_author not in text: raise RuntimeError('Expected author not found on direct post')
if post_needle not in text: raise RuntimeError('Target post needle not found')
low=text.casefold()
if 'commenting has been turned off' in low or 'đã tắt tính năng bình luận' in low:
    raise RuntimeError('Commenting is turned off for target post')
count=editor_count()
if count != 1: raise RuntimeError(f'Expected exactly one visible Radar BDS comment editor, found {{count}}')
if focus_editor() != 1: raise RuntimeError('Could not focus Radar BDS comment editor')
before_comment_count=rendered_comment_count()
type_text(comment); time.sleep(2); stop_guard('comment_prepared')
capture_screenshot(path=screenshot,full=False,max_dim=1800)
if mode=='prepare':
    press_key('a',modifiers=2); press_key('Backspace'); time.sleep(1)
    editor_after_clear=js("(() => {{ const es=[...document.querySelectorAll('[contenteditable=true][role=textbox]')].filter(e => (e.getAttribute('aria-label')||'').includes('Radar BDS') && !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)); return es.length===1 ? (es[0].innerText||'').trim() : '__EDITOR_COUNT_ERROR__'; }})()")
    if editor_after_clear: raise RuntimeError('Prepare cleanup failed: editor is not empty')
    print(json.dumps({{'ok':True,'status':'prepared_and_cleared','group':expected_group,'post_url':post_url,'comment':comment,'screenshot':screenshot}},ensure_ascii=False)); raise SystemExit(0)
if mode!='publish': raise RuntimeError('Unsupported mode')
press_key('ENTER'); time.sleep(7); stop_guard('after_comment')
editor_text=js("(() => {{ const es=[...document.querySelectorAll('[contenteditable=true][role=textbox]')].filter(e => (e.getAttribute('aria-label')||'').includes('Radar BDS') && !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)); return es.length===1 ? (es[0].innerText||'').trim() : ''; }})()")
text=body_text()
after_comment_count=rendered_comment_count()
if comment_needle not in text or comment_needle in (editor_text or '') or after_comment_count <= before_comment_count:
    raise RuntimeError('Comment submit attempted but a new persistent rendered Radar BDS comment was not verified')
permalink=js({permalink_expr!r})
if not permalink or ('comment_id=' not in permalink and 'reply_comment_id=' not in permalink):
    raise RuntimeError('Comment submit verified but no comment_id/reply_comment_id permalink was found')
capture_screenshot(path=screenshot,full=False,max_dim=1800)
print(json.dumps({{'ok':True,'status':'published','group':expected_group,'post_url':post_url,'comment_permalink':permalink,'comment':comment,'screenshot':screenshot}},ensure_ascii=False))
"""


def run(args: argparse.Namespace) -> dict:
    qpath = Path(args.queue).resolve()
    queue = load_json(qpath)
    config = load_json(Path(args.targets))
    target = allowlisted(queue, config)
    validate_comment((queue.get('content') or {}).get('comment') or '', target)
    if args.mode == 'publish' and not args.yes:
        raise SystemExit('Refusing publish without --yes')
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    artifact_dir = Path(args.artifact_dir)
    run_dir = Path(args.run_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshot = str(artifact_dir / f'{stamp}-{target["id"]}-{args.mode}.png')
    env = os.environ.copy()
    env['BU_CDP_URL'] = args.cdp_url
    proc = subprocess.run(
        [str(BROWSER_USE)],
        input=program(queue, args.mode, screenshot, target),
        text=True,
        capture_output=True,
        env=env,
        timeout=args.timeout,
        check=False,
    )
    record = {
        'queue': str(qpath),
        'mode': args.mode,
        'target': target['id'],
        'post_url': (queue.get('source') or {}).get('post_url'),
        'returncode': proc.returncode,
        'stdout': proc.stdout[-6000:],
        'stderr': proc.stderr[-6000:],
        'screenshot': screenshot,
    }
    log = run_dir / f'{stamp}-{target["id"]}-{args.mode}.json'
    log.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False, indent=2))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return record


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--queue', required=True)
    p.add_argument('--mode', choices=['prepare', 'publish'], default='prepare')
    p.add_argument('--yes', action='store_true')
    p.add_argument('--targets', default=str(DEFAULT_TARGETS))
    p.add_argument('--cdp-url', default=DEFAULT_CDP_URL)
    p.add_argument('--artifact-dir', default=str(DEFAULT_ARTIFACT_DIR))
    p.add_argument('--run-dir', default=str(DEFAULT_RUN_DIR))
    p.add_argument('--timeout', type=int, default=300)
    run(p.parse_args())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Publish/prepare one allowlisted Radar BDS Facebook group post via browser-use."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
from pathlib import Path

BROWSER_USE = Path('/home/hermesops/radar-browser-use/.venv/bin/browser-use')
DEFAULT_CDP_URL = 'http://127.0.0.1:9224'
DEFAULT_TARGETS = Path('/opt/radar-bds/current/config/social_group_targets.json')
DEFAULT_ARTIFACT_DIR = Path('/home/hermesops/radar-browser-use/artifacts/group-marketing')
DEFAULT_RUN_DIR = Path('/opt/radar-bds/var/browser_use_runs/group-marketing')


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def allowlisted(queue: dict, config: dict) -> dict:
    target = queue.get('target') or {}
    if target.get('surface') != 'group':
        raise SystemExit('Refusing: queue target.surface must be group')
    url = str(target.get('page_url') or '').rstrip('/') + '/'
    for item in config.get('targets', []):
        if item.get('enabled') and str(item.get('url') or '').rstrip('/') + '/' == url:
            return item
    raise SystemExit(f'Refusing: target is not enabled in group allowlist: {url}')


def program(queue: dict, mode: str, screenshot: str, target: dict) -> str:
    message = str((queue.get('content') or {}).get('message') or '').strip()
    image = str((queue.get('content') or {}).get('image') or '').strip()
    if not message:
        raise SystemExit('Queue has no content.message')
    if image and not Path(image).exists():
        raise SystemExit(f'Queue image missing: {image}')
    needle = message.split('\n', 1)[0][:70]
    return f"""
import json,time
page_url={target['url']!r}
expected_group={target['name']!r}
message={message!r}
image={image!r}
mode={mode!r}
screenshot={screenshot!r}
needle={needle!r}

def ax(): return cdp('Accessibility.getFullAXTree').get('nodes',[])
def props(n): return {{p.get('name'):(p.get('value') or {{}}).get('value') for p in n.get('properties',[])}}
def center(bid):
    b=cdp('DOM.getBoxModel',backendNodeId=bid)['model']['content']; return sum(b[0::2])/4,sum(b[1::2])/4
def click_node(n):
    click_at_xy(*center(n['backendDOMNodeId'])); time.sleep(1.5)
def body_text(): return js("document.body.innerText || ''") or ''
def stop_guard(stage):
    text=body_text().casefold()
    bad=['checkpoint','captcha','temporarily blocked','tạm thời bị chặn','account restricted','tài khoản bị hạn chế','we limit how often','chúng tôi giới hạn tần suất']
    hits=[x for x in bad if x in text]
    if hits: raise RuntimeError(f'STOP_GUARD {{stage}}: '+','.join(hits))

new_tab(page_url); wait_for_load(); time.sleep(4); stop_guard('group_load')
# A posting run must start from a clean tab. Refuse if Facebook restored a stale composer.
stale=js("[...document.querySelectorAll('[role=dialog]')].filter(d => (d.innerText||'').includes('Create post') || (d.innerText||'').includes('Tạo bài viết')).length")
if stale: raise RuntimeError('Stale composer restored in clean tab; stop before action')
text=body_text()
if expected_group not in text: raise RuntimeError('Expected group name not found')
if 'Joined' not in text and 'Đã tham gia' not in text: raise RuntimeError('Account is not visibly joined to group')
composer=None
for n in ax():
    role=(n.get('role') or {{}}).get('value',''); name=(n.get('name') or {{}}).get('value','')
    if role=='button' and ('Write something' in name or 'Viết gì' in name or 'Bạn viết gì' in name): composer=n; break
if not composer: raise RuntimeError('Group composer not found')
click_node(composer); stop_guard('composer_open')
textbox=None
for n in ax():
    role=(n.get('role') or {{}}).get('value',''); name=(n.get('name') or {{}}).get('value',''); p=props(n)
    if role=='textbox' and (p.get('editable')=='richtext' or 'public post' in name.casefold() or 'bài viết công khai' in name.casefold()): textbox=n; break
if not textbox: raise RuntimeError('Group post textbox not found')
click_node(textbox); type_text(message); time.sleep(3)
if image:
    # Upload only through the file input inside the one composer that already contains our caption.
    caption_dialogs=js("[...document.querySelectorAll('[role=dialog]')].filter(d => (d.innerText||'').includes("+json.dumps(needle)+")).length")
    if caption_dialogs != 1: raise RuntimeError(f'Expected exactly one caption composer, found {{caption_dialogs}}')
    doc=cdp('DOM.getDocument',depth=1)['root']['nodeId']
    ids=cdp('DOM.querySelectorAll',nodeId=doc,selector='[role="dialog"] input[type="file"]')['nodeIds']
    if len(ids) != 1: raise RuntimeError(f'Expected one composer file input, found {{len(ids)}}')
    cdp('DOM.setFileInputFiles',nodeId=ids[0],files=[image])
    caption_has_native_visual=False
    blob_selector='img[src^="blob:"]'
    for _ in range(20):
        caption_visuals=js("[...document.querySelectorAll('[role=dialog]')].filter(d => (d.innerText||'').includes("+json.dumps(needle)+") && d.querySelector("+json.dumps(blob_selector)+")).length")
        if caption_visuals == 1:
            caption_has_native_visual=True
            break
        time.sleep(1)
    if not caption_has_native_visual:
        raise RuntimeError('Caption and native blob visual are not in the same composer after 20s')
capture_screenshot(path=screenshot,full=False,max_dim=1800)
if mode=='prepare':
    print(json.dumps({{'ok':True,'status':'prepared','group':expected_group,'screenshot':screenshot}},ensure_ascii=False)); raise SystemExit(0)
if mode!='publish': raise RuntimeError('Unsupported mode')
post=None
for n in ax():
    role=(n.get('role') or {{}}).get('value',''); name=(n.get('name') or {{}}).get('value',''); p=props(n)
    if role=='button' and name in ('Post','Đăng') and not p.get('disabled'): post=n; break
if not post: raise RuntimeError('Enabled Post button not found')
click_node(post); time.sleep(6); stop_guard('after_post')
status='unverified'; permalink=''
for _ in range(30):
    text=body_text()
    low=text.casefold()
    if 'pending' in low and ('admin' in low or 'approval' in low or 'phê duyệt' in low): status='pending_review'; break
    result=js("(() => {{ const needle="+json.dumps(needle)+"; for (const a of document.querySelectorAll('[role=article]')) {{ if ((a.innerText||'').includes(needle)) {{ const links=[...a.querySelectorAll('a[href*=\\\"/groups/\\\"][href*=\\\"/posts/\\\"]')]; if (links.length) return links[0].href.split('?')[0]; return 'FOUND_NO_LINK'; }} }} return ''; }})()")
    if result:
        status='published'; permalink='' if result=='FOUND_NO_LINK' else result; break
    time.sleep(2)
capture_screenshot(path=screenshot,full=False,max_dim=1800)
# A pending group post can appear in the author's feed immediately while its
# permalink remains unavailable. Confirm the permalink; if unavailable, require
# explicit "Pending admin approval" evidence from the group's Your posts page.
if status=='published' and permalink:
    new_tab(permalink); wait_for_load(); time.sleep(4)
    direct=body_text()
    if needle not in direct:
        new_tab(page_url.rstrip('/')+'/yourposts/'); wait_for_load(); time.sleep(4)
        pending_text=body_text()
        if 'Pending admin approval' in pending_text or 'Đang chờ quản trị viên phê duyệt' in pending_text:
            status='pending_review'
        else:
            raise RuntimeError('Tentative permalink unavailable and no pending-approval evidence found')
if status=='unverified': raise RuntimeError('Post action attempted but no published/pending evidence found')
print(json.dumps({{'ok':True,'status':status,'group':expected_group,'group_url':page_url,'permalink':permalink,'needle':needle,'screenshot':screenshot}},ensure_ascii=False))
"""


def run(args: argparse.Namespace) -> dict:
    qpath = Path(args.queue).resolve()
    queue = load_json(qpath)
    config = load_json(Path(args.targets))
    target = allowlisted(queue, config)
    if args.mode == 'publish' and not args.yes:
        raise SystemExit('Refusing publish without --yes')
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    artifact_dir = Path(args.artifact_dir); artifact_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(args.run_dir); run_dir.mkdir(parents=True, exist_ok=True)
    screenshot = str(artifact_dir / f'{stamp}-{target["id"]}-{args.mode}.png')
    env = os.environ.copy(); env['BU_CDP_URL'] = args.cdp_url
    proc = subprocess.run([str(BROWSER_USE)], input=program(queue,args.mode,screenshot,target), text=True, capture_output=True, env=env, timeout=args.timeout, check=False)
    record = {'queue':str(qpath),'mode':args.mode,'target':target['id'],'returncode':proc.returncode,'stdout':proc.stdout[-5000:],'stderr':proc.stderr[-5000:],'screenshot':screenshot}
    log = run_dir / f'{stamp}-{target["id"]}-{args.mode}.json'; log.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False,indent=2))
    if proc.returncode != 0: raise SystemExit(proc.returncode)
    return record


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--queue',required=True); p.add_argument('--mode',choices=['prepare','publish'],default='prepare'); p.add_argument('--yes',action='store_true')
    p.add_argument('--targets',default=str(DEFAULT_TARGETS)); p.add_argument('--cdp-url',default=DEFAULT_CDP_URL)
    p.add_argument('--artifact-dir',default=str(DEFAULT_ARTIFACT_DIR)); p.add_argument('--run-dir',default=str(DEFAULT_RUN_DIR)); p.add_argument('--timeout',type=int,default=300)
    run(p.parse_args()); return 0

if __name__=='__main__': raise SystemExit(main())

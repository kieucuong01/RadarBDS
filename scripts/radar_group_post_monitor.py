#!/usr/bin/env python3
"""Monitor Radar BDS Facebook group posts that are pending admin approval."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import urllib.request
from pathlib import Path

BROWSER_USE=Path('/home/hermesops/radar-browser-use/.venv/bin/browser-use')
START_BROWSER=Path('/home/hermesops/radar-browser-use/start-radar-social-browser.sh')
CDP='http://127.0.0.1:9224'
STATE=Path('/opt/radar-bds/var/social_queue/group-autopost/state.json')
TARGETS=Path('/opt/radar-bds/current/config/social_group_targets.json')
RUN_DIR=Path('/opt/radar-bds/var/browser_use_runs/group-marketing-monitor')


def load(path: Path, default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception: return default


def cdp_ready() -> bool:
    try:
        with urllib.request.urlopen(CDP+'/json/version',timeout=3) as r: return r.status==200
    except Exception: return False


def ensure_browser() -> None:
    if cdp_ready(): return
    subprocess.Popen([str(START_BROWSER)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    import time
    for _ in range(30):
        time.sleep(1)
        if cdp_ready(): return
    raise RuntimeError('Radar Social Chrome CDP unavailable')


def needle(action: dict) -> str:
    q=load(Path(str(action.get('queue',''))),{})
    msg=str((q.get('content') or {}).get('message') or '')
    return msg.split('\n',1)[0][:70]


def inspect(permalink: str, group_url: str, text_needle: str) -> dict:
    program=f"""
import json,time
permalink={permalink!r}; group_url={group_url!r}; needle={text_needle!r}
new_tab(permalink); wait_for_load(); time.sleep(4)
body=js("document.body.innerText||''") or ''
if needle and needle in body:
    print(json.dumps({{'status':'published','permalink':permalink}},ensure_ascii=False)); raise SystemExit(0)
new_tab(group_url.rstrip('/')+'/yourposts/'); wait_for_load(); time.sleep(4)
body=js("document.body.innerText||''") or ''
if 'Pending admin approval' in body or 'Đang chờ quản trị viên phê duyệt' in body:
    status='pending_review'
else:
    status='unavailable_after_pending'
print(json.dumps({{'status':status,'permalink':permalink}},ensure_ascii=False))
"""
    env=os.environ.copy(); env['BU_CDP_URL']=CDP
    proc=subprocess.run([str(BROWSER_USE)],input=program,text=True,capture_output=True,env=env,timeout=180,check=False)
    if proc.returncode!=0: raise RuntimeError(proc.stderr[-3000:] or proc.stdout[-3000:])
    lines=[x for x in proc.stdout.splitlines() if x.strip()]
    return json.loads(lines[-1])


def main() -> int:
    state=load(STATE,{'schema':'radar_group_auto_state.v1','actions':[]})
    targets={x.get('id'):x for x in load(TARGETS,{}).get('targets',[])}
    pending=[x for x in state.get('actions',[]) if x.get('status')=='pending_review' and x.get('permalink')]
    if not pending: return 0
    ensure_browser(); now=dt.datetime.now().astimezone(); changed=[]
    RUN_DIR.mkdir(parents=True,exist_ok=True)
    for action in pending:
        target=targets.get(action.get('target_id')) or {}
        result=inspect(str(action['permalink']),str(target.get('url') or ''),needle(action))
        status=result['status']
        if status=='published':
            action['status']='published'; action['approved_at']=now.isoformat(timespec='seconds'); changed.append(('published',action.copy()))
        elif status=='unavailable_after_pending':
            try: age=(now-dt.datetime.fromisoformat(str(action.get('at')))).total_seconds()
            except Exception: age=0
            if age>=6*3600:
                action['status']='unavailable_after_pending'; action['checked_at']=now.isoformat(timespec='seconds'); changed.append(('unavailable',action.copy()))
    if changed:
        tmp=STATE.with_suffix('.tmp'); tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); tmp.replace(STATE)
    log=RUN_DIR/f'{now.strftime("%Y%m%d-%H%M%S")}.json'; log.write_text(json.dumps({'checked':len(pending),'changed':changed},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for kind,a in changed:
        if kind=='published':
            print('@rb GROUP POST ĐÃ ĐƯỢC DUYỆT')
            print(f"Bài: {a.get('source_url')}")
            print(f"Group: {a.get('group')}")
            print(f"Facebook: {a.get('permalink')}")
        else:
            print('@rb GROUP POST KHÔNG CÒN TRONG HÀNG DUYỆT')
            print(f"Bài: {a.get('source_url')}")
            print(f"Group: {a.get('group')}")
            print('Permalink vẫn không mở được; khả năng bài đã bị từ chối/xóa. Auto-post vào group này sẽ vẫn bị giới hạn bởi frequency cap.')
    return 0

if __name__=='__main__': raise SystemExit(main())

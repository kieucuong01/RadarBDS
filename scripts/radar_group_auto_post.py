#!/usr/bin/env python3
"""Low-volume, allowlisted Facebook group marketing for Radar BDS."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import textwrap
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

REPO=Path('/opt/radar-bds/current')
TARGETS=REPO/'config/social_group_targets.json'
EXECUTOR=REPO/'scripts/browser_use_group_post.py'
START_BROWSER=Path('/home/hermesops/radar-browser-use/start-radar-social-browser.sh')
CDP='http://127.0.0.1:9224'
STATE=Path('/opt/radar-bds/var/social_queue/group-autopost/state.json')
QUEUE_DIR=Path('/opt/radar-bds/var/social_queue/group-autopost/queue')
ASSET_DIR=Path('/opt/radar-bds/var/social_queue/group-assets')
SITE='https://radarbds.vn'

sys.path.insert(0,str(REPO))


def load_json(path: Path, default: Any) -> Any:
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception: return default


def article_date(page: dict) -> str:
    a=page.get('article') or {}; return str(a.get('modified_at') or a.get('published_at') or '')


def candidates() -> list[tuple[str,dict]]:
    from config.seo_articles import SEO_ARTICLES
    rows=[(k,v) for k,v in SEO_ARTICLES.items() if isinstance(v,dict) and str(v.get('path','')).startswith('/tin-tuc/')]
    return sorted(rows,key=lambda kv:(article_date(kv[1]),kv[0]),reverse=True)


def utm(url: str, slug: str) -> str:
    p=urllib.parse.urlsplit(url); q=dict(urllib.parse.parse_qsl(p.query,keep_blank_values=True))
    q.update({'utm_source':'facebook','utm_medium':'group_post','utm_campaign':'community_education','utm_content':slug})
    return urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(q)))


def clean(s: Any) -> str: return re.sub(r'\s+',' ',str(s or '')).strip()


def build_message(slug: str, page: dict) -> str:
    title=clean(page.get('hero_title') or page.get('title')).replace(' | Radar BDS','')
    insight=clean(page.get('hero_text') or page.get('description'))
    if len(insight)>330: insight=insight[:327].rsplit(' ',1)[0]+'…'
    url=utm(SITE+str(page.get('path')),slug)
    question='Anh/chị khi xem BĐS Bình Dương thường lọc loại hình trước, hay nhìn tổng giá trước?'
    body=f"""{title}

{insight}

Radar BDS tổng hợp dữ liệu giá rao để giúp người mua lọc ban đầu. Nội dung không thay thẩm định pháp lý, quy hoạch hoặc kiểm tra thực tế.

Xem phần giải thích và bảng đối chiếu:
{url}

{question}"""
    forbidden=['cam kết lợi nhuận','cơ hội vàng','rẻ nhất','giá thật 100%','pháp lý chuẩn 100%']
    low=body.casefold(); hits=[x for x in forbidden if x in low]
    if hits: raise ValueError('Forbidden claim: '+','.join(hits))
    return body


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words=text.split(); lines=[]; cur=''
    for w in words:
        test=(cur+' '+w).strip()
        if draw.textbbox((0,0),test,font=font)[2] <= max_width: cur=test
        else:
            if cur: lines.append(cur)
            cur=w
    if cur: lines.append(cur)
    return lines


def make_visual(slug: str, page: dict) -> Path:
    special=ASSET_DIR/'2026-07-25-dat-nen-vs-nha-dat.png'
    if slug=='vi-sao-khong-nen-so-nha-dat-chung-voi-dat-nen' and special.exists(): return special
    ASSET_DIR.mkdir(parents=True,exist_ok=True)
    out=ASSET_DIR/f'{dt.date.today().isoformat()}-{slug}.png'
    title=clean(page.get('hero_title') or page.get('title')).replace(' | Radar BDS','')
    insight=clean(page.get('hero_text') or page.get('description'))
    W=H=1080; im=Image.new('RGB',(W,H),(8,28,50)); d=ImageDraw.Draw(im)
    for y in range(H):
        c=(8+int(10*y/H),28+int(35*y/H),50+int(48*y/H)); d.line((0,y,W,y),fill=c)
    font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'; bold='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    def f(n,b=False): return ImageFont.truetype(bold if b else font,n)
    d.rounded_rectangle((70,64,350,128),24,fill=(8,45,72),outline=(84,190,231),width=2); d.ellipse((92,81,123,112),fill=(29,214,157)); d.text((140,78),'RADAR BĐS',font=f(30,True),fill='white')
    d.text((72,180),'ĐỌC NHANH THỊ TRƯỜNG',font=f(28,True),fill=(104,218,255))
    y=245
    title_font=f(57,True)
    for line in wrap(d,title,title_font,920)[:5]: d.text((72,y),line,font=title_font,fill='white'); y+=72
    y+=25; d.rounded_rectangle((70,y,1010,min(900,y+260)),30,fill=(245,249,252))
    yy=y+38; insight_font=f(27)
    for line in wrap(d,insight,insight_font,850)[:6]: d.text((112,yy),line,font=insight_font,fill=(42,58,76)); yy+=42
    d.rounded_rectangle((70,934,1010,1010),24,fill=(7,45,71),outline=(80,190,231),width=2)
    d.text((103,957),'Giá rao để lọc ban đầu • Cần kiểm tra thực tế và pháp lý',font=f(23,True),fill=(210,232,244))
    im.save(out,quality=94,optimize=True); return out


def healthy(url: str) -> bool:
    try:
        req=urllib.request.Request(url,method='HEAD',headers={'User-Agent':'RadarBDS-GroupMarketing/1.0'})
        with urllib.request.urlopen(req,timeout=15) as r: return r.status<400
    except Exception: return False


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


def parse_time(s: str) -> dt.datetime | None:
    try: return dt.datetime.fromisoformat(s)
    except Exception: return None


def choose_target(config: dict, state: dict, now: dt.datetime) -> dict | None:
    actions=state.get('actions',[])
    if any(str(x.get('at','')).startswith(now.date().isoformat()) for x in actions): return None
    for t in config.get('targets',[]):
        if not t.get('enabled') or t.get('requires_review'): continue
        past=[x for x in actions if x.get('target_id')==t.get('id') and x.get('status') in ('published','pending_review')]
        week=[x for x in past if (parse_time(x.get('at','')) and (now-parse_time(x['at'])).total_seconds()<7*86400)]
        if len(week)>=int(t.get('max_posts_per_week',1)): continue
        if past:
            last=max(filter(None,(parse_time(x.get('at','')) for x in past)))
            if (now-last).total_seconds()<int(t.get('min_gap_hours',120))*3600: continue
        return t
    return None


def choose_article(state: dict, target: dict, force_slug: str|None=None) -> tuple[str,dict]|None:
    posted={(x.get('target_id'),x.get('slug')) for x in state.get('actions',[]) if x.get('status') in ('published','pending_review')}
    now=dt.date.today()
    for slug,page in candidates():
        if force_slug and slug!=force_slug: continue
        if (target['id'],slug) in posted: continue
        try: age=(now-dt.date.fromisoformat(article_date(page))).days
        except Exception: age=999
        if force_slug or 0<=age<=4: return slug,page
    return None


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--publish',action='store_true'); ap.add_argument('--dry-run',action='store_true'); ap.add_argument('--force-slug')
    args=ap.parse_args(); now=dt.datetime.now().astimezone()
    config=load_json(TARGETS,{}); state=load_json(STATE,{'schema':'radar_group_auto_state.v1','actions':[]})
    target=choose_target(config,state,now)
    if not target:
        if args.dry_run: print(json.dumps({'ok':True,'skip':'frequency_cap'},ensure_ascii=False))
        return 0
    picked=choose_article(state,target,args.force_slug)
    if not picked:
        if args.dry_run: print(json.dumps({'ok':True,'skip':'no_recent_unposted_article'},ensure_ascii=False))
        return 0
    slug,page=picked; source=SITE+str(page.get('path'))
    if not healthy(source): raise SystemExit(f'Source URL unhealthy: {source}')
    image=make_visual(slug,page); message=build_message(slug,page)
    QUEUE_DIR.mkdir(parents=True,exist_ok=True); STATE.parent.mkdir(parents=True,exist_ok=True)
    queue={'schema':'radar_social_queue.v1','created_at':now.isoformat(timespec='seconds'),'source':{'slug':slug,'url':source,'title':clean(page.get('hero_title') or page.get('title')),'article_date':article_date(page)},'target':{'platform':'facebook','surface':'group','page_url':target['url'],'mode':'publish' if args.publish else 'review'},'content':{'message':message,'link':utm(source,slug),'image':str(image)},'guards':{'allowlist':True,'daily_cap':1,'weekly_target_cap':target.get('max_posts_per_week',1),'stop_on_checkpoint':True,'no_duplicate':True}}
    qpath=QUEUE_DIR/f'{now.date()}-{target["id"]}-{slug}.json'; qpath.write_text(json.dumps(queue,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.dry_run or not args.publish:
        print(json.dumps({'ok':True,'queue':str(qpath),'target':target,'message':message,'image':str(image)},ensure_ascii=False,indent=2)); return 0
    ensure_browser()
    proc=subprocess.run([str(EXECUTOR),'--queue',str(qpath),'--mode','publish','--yes'],text=True,capture_output=True,timeout=360,check=False)
    if proc.returncode!=0: raise SystemExit('Group publish failed\n'+proc.stdout[-4000:]+'\n'+proc.stderr[-4000:])
    try:
        record=json.loads(proc.stdout)
        inner_lines=[line for line in str(record.get('stdout','')).splitlines() if line.strip()]
        result=json.loads(inner_lines[-1])
    except Exception as exc:
        raise SystemExit(f'Could not parse verified executor result: {exc}\n{proc.stdout[-4000:]}')
    status=str(result.get('status') or '')
    if status not in ('published','pending_review'):
        raise SystemExit(f'Executor returned unsupported status: {status}')
    permalink=str(result.get('permalink') or '')
    screenshot=str(result.get('screenshot') or record.get('screenshot') or '')
    action={'at':now.isoformat(timespec='seconds'),'target_id':target['id'],'group':target['name'],'slug':slug,'source_url':source,'status':status,'permalink':permalink,'queue':str(qpath),'image':str(image),'screenshot':screenshot}
    state.setdefault('actions',[]).append(action); state['actions']=state['actions'][-200:]
    tmp=STATE.with_suffix('.tmp'); tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); tmp.replace(STATE)
    print('@rb GROUP MARKETING AUTO-POST OK')
    print(f'Đã đăng: {clean(page.get("hero_title") or page.get("title"))}')
    print(f'Group: {target["name"]} — {target["url"]}')
    print(f'Trạng thái: {status}')
    print(f'Bài nguồn: {source}')
    if permalink: print(f'Facebook: {permalink}')
    print(f'Visual: {image}')
    print('Caption:\n'+message)
    return 0

if __name__=='__main__': raise SystemExit(main())

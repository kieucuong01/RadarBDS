#!/usr/bin/env python3
"""Rewrite pending Page artifacts locally. Never publish or alter posted proofs.

Default is inventory-only. --apply requires --backup-dir outside the live queue.
All regenerated artifacts return to review: a file's old 'publish' permission is
not editorial approval of newly written copy. Source dates are never freshened.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys

REPO=Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path: sys.path.insert(0,str(REPO))
DEFAULT_ROOT=Path('/opt/radar-bds/var/social_queue')


def load(path):
    data=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data,dict): raise ValueError(f'Expected JSON object: {path}')
    return data


def inventory(root: Path):
    slugs=set();proofs=set();keys=set()
    for f in (root/'posted_slugs.json',root/'page_care/posted_native.json'):
        if not f.exists(): continue
        for key,entry in load(f).get('posted',{}).items():
            keys.add(key)
            if not isinstance(entry,dict): raise ValueError(f'Invalid posted proof: {f} {key}')
            slugs.add(entry.get('slug') or key.rsplit(':',1)[0]);proofs.add(entry.get('queue',''))
    rows=[]
    for directory in (root,root/'autopost',root/'page_care'):
        for path in sorted(directory.glob('*.json')):
            data=load(path)
            if data.get('schema')!='radar_social_queue.v1':continue
            if (data.get('target') or {}).get('surface','page')!='page':continue
            src=data.get('source') or {};slug=src.get('slug','')
            posted=(slug in slugs or str(path) in proofs or f"{slug}:{src.get('article_date')}" in keys
                    or data.get('status') in {'posted','published'} or bool(data.get('post_url')))
            rows.append({'path':str(path),'slug':slug,'source_date':src.get('article_date'),
                         'action':'preserve_posted' if posted else 'regenerate',
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return rows


def _backup(path, directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(str(path).encode()).hexdigest()[:12]
    dest=directory/(digest+'-'+path.name)
    original=path.read_bytes()
    if dest.exists() and dest.read_bytes()!=original:
        raise ValueError(f'Backup already exists for another revision: {dest}')
    if not dest.exists(): dest.write_bytes(original)
    return dest


def _write(path,data):
    st=path.stat();tmp=path.with_suffix(path.suffix+'.editorial.tmp')
    try:
        with tmp.open('x',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(tmp,st.st_mode & 0o777)
        if os.geteuid()==0:os.chown(tmp,st.st_uid,st.st_gid)
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()


def replace_pending(path,new,*,backup_dir):
    old=load(path);backup=_backup(path,backup_dir)
    new=dict(new)
    new['created_at']=old.get('created_at')
    target=dict(new.get('target') or old.get('target') or {})
    target.update(mode='review',requires_review=True);new['target']=target
    new['regeneration']={'at':dt.datetime.now().astimezone().isoformat(),
        'original_source_date':(old.get('source') or {}).get('article_date'),
        'original_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'backup':str(backup)}
    _write(path,new)
    return {'path':str(path),'action':'regenerated','backup':str(backup),'status':new.get('status')}


def block_pending(path,reason,*,backup_dir):
    data=load(path);backup=_backup(path,backup_dir)
    data['status']='blocked';data.setdefault('target',{}).update(mode='review',requires_review=True)
    data['content']={'message':'','self_comment':'','visual_path':''}
    data['regeneration']={'at':dt.datetime.now().astimezone().isoformat(),'blocked_reason':reason,
        'original_source_date':(data.get('source') or {}).get('article_date'),'backup':str(backup)}
    _write(path,data)
    return {'path':str(path),'action':'blocked','reason':reason,'backup':str(backup)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--backup-dir',type=Path)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    plan=inventory(args.root)
    result={'plan':plan,'results':[]}
    if args.apply:
        if not args.backup_dir:parser.error('--apply requires --backup-dir')
        if args.backup_dir.resolve().is_relative_to(args.root.resolve()):parser.error('Backup must be outside queue root')
        from scripts import radar_social_queue as q
        for row in plan:
            path=Path(row['path'])
            if row['action']=='preserve_posted':continue
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError(f'Concurrent queue edit: {path}')
            old=load(path)
            try:
                # Rebuild from the true source, never the defective old caption.
                ns=argparse.Namespace(slug=row['slug'],platform='facebook',surface='page',
                    page_url=(old.get('target') or {}).get('page_url') or 'https://www.facebook.com/radarbdsvn/',
                    mode='review',style='data_post',skip_verify=False)
                new=q.create(ns)
                if (new.get('source') or {}).get('http_status')!=200:
                    raise ValueError('source_not_verified_200')
                result['results'].append(replace_pending(path,new,backup_dir=args.backup_dir))
            except (ValueError,SystemExit) as e:
                result['results'].append(block_pending(path,str(e),backup_dir=args.backup_dir))
        for row in plan:
            if row['action']=='preserve_posted' and hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()!=row['sha256']:
                raise RuntimeError(f'Posted artifact changed: {row["path"]}')
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())

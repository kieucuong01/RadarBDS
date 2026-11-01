"""Root-only, backed-up Nginx Maps cache installation; never changes listing cache."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not args.apply:
        parser.error('Review docs/planning_sources/maps-performance.md, then use --apply as root')
    if not hasattr(os,'geteuid') or os.geteuid()!=0:
        parser.error('Run with sudo/root; the deploy account cannot edit Nginx')
    repo=Path(__file__).resolve().parents[1]
    site=Path('/etc/nginx/sites-available/radar-bds.conf')
    zone=Path('/etc/nginx/conf.d/radar-maps-cache.conf')
    snippet=Path('/etc/nginx/snippets/radar-maps-cache-location.inc')
    env=Path('/etc/radar-bds/radar.env')
    include='    include /etc/nginx/snippets/radar-maps-cache-location.inc;\n'
    text=site.read_text();env_text=env.read_text()
    if 'include /etc/nginx/snippets/radar-maps-cache-location' not in text:
        marker='    location / {'
        if text.count(marker)!=1:
            raise SystemExit('Unexpected site configuration; review insertion point manually')
        text=text.replace(marker,include+'\n'+marker,1)
    key='RADAR_PLANNING_GATEWAY_FIRST'
    env_text=re.sub(r'^'+key+r'=.*$',key+'=1',env_text,flags=re.M) if re.search(r'^'+key+r'=',env_text,re.M) else env_text.rstrip()+'\n'+key+'=1\n'
    backup=Path('/var/backups/radar-bds/maps-cache-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True,mode=0o700)
    files=(site,zone,snippet,env)
    for index,path in enumerate(files):
        if path.exists():shutil.copy2(path,backup/str(index))
    try:
        cache_dir=Path('/var/cache/nginx/radar-maps')
        cache_dir.mkdir(parents=True,exist_ok=True)
        shutil.chown(cache_dir,user='www-data',group='www-data')
        cache_dir.chmod(0o750)
        zone.write_text((repo/'deployment/ubuntu24/nginx-radar-maps-cache.conf').read_text())
        snippet.write_text((repo/'deployment/ubuntu24/nginx-radar-maps-cache-location.inc').read_text())
        site.write_text(text)
        subprocess.run(['nginx','-t'],check=True)
        subprocess.run(['systemctl','reload','nginx'],check=True)
        env.write_text(env_text)
        subprocess.run(['systemctl','restart','radar-bds.service'],check=True)
        subprocess.run(['systemctl','is-active','radar-bds.service'],check=True)
    except Exception:
        for index,path in enumerate(files):
            saved=backup/str(index)
            if saved.exists():shutil.copy2(saved,path)
            elif path in (zone,snippet):path.unlink(missing_ok=True)
        subprocess.run(['nginx','-t'],check=False)
        subprocess.run(['systemctl','reload','nginx'],check=False)
        subprocess.run(['systemctl','restart','radar-bds.service'],check=False)
        raise
    print('Maps origin cache installed. Private rollback backup:',backup)


if __name__=='__main__':main()

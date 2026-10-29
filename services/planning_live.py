"""Opt-in public GIS routes backed by a separately verified, read-only parcel asset."""
from collections import OrderedDict
from hashlib import file_digest
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time

from services.planning_assets import release_id


def validate_assets(site, verify_hashes=False):
    site=Path(site).resolve()
    config=json.loads((site/'config/planning_live_release.json').read_text(encoding='utf8'))
    version,files=config['release'],config['files']
    expected={'parcels.sqlite',*(f'metadata/{name}.json' for name in (
        'partition','urban_general','partition_supplement','urban_general_supplement'))}
    if (not isinstance(version,str) or not re.fullmatch(r'[a-f0-9]{16}',version)
            or not isinstance(files,dict) or set(files)!=expected or release_id(files)!=version):
        raise ValueError('Invalid live planning release')
    root=site/'data/planning'/version
    for name,entry in files.items():
        path=root/name
        if (not path.resolve().is_relative_to(root.resolve()) or path.is_symlink()
                or not re.fullmatch(r'[a-f0-9]{64}',entry['sha256'])
                or path.stat().st_size!=entry['bytes']):
            raise ValueError('Planning asset size/path mismatch')
        # Large SQLite hash is verified before activation; small grid hashes on each startup.
        if verify_hashes or name!='parcels.sqlite':
            with path.open('rb') as stream:
                if file_digest(stream,'sha256').hexdigest()!=entry['sha256']:
                    raise ValueError('Planning asset hash mismatch')
    from config.planning_parcels import PARCEL_AREAS
    from services.planning_parcel_catalog import ParcelCatalog
    from services.planning_tiles import validate_grid
    for name in expected-{'parcels.sqlite'}:
        validate_grid(json.loads((root/name).read_text(encoding='utf8')))
    catalog=ParcelCatalog(root/'parcels.sqlite')
    actual={a['area_id']:(a['ward'],a['city']) for a in catalog.areas}
    if actual!={a['code']:(a['ward'],a['city']) for a in PARCEL_AREAS}:
        raise ValueError('Planning asset must cover exactly historic Binh Duong')
    if config['areas']!=91 or sum(a['count'] for a in catalog.areas)!=config['count']:
        raise ValueError('Planning asset totals mismatch')
    if verify_hashes:
        with catalog.connect() as conn:
            counts=[conn.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('parcels','bounds')]
            if counts!=[config['count']]*2 or conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise ValueError('Planning index integrity mismatch')
    return root,config


class PlanningLimiter:
    """Bounded per-worker request budget without DB writes on tile/pan paths."""
    def __init__(self,max_keys=4096):
        self.entries=OrderedDict();self.lock=threading.Lock();self.max_keys=max_keys

    def allow(self,peer,kind,limit,now=None):
        now=time.monotonic() if now is None else now
        key=(peer,kind)
        with self.lock:
            start,count=self.entries.pop(key,(now,0))
            if now-start>=3600:start,count=now,0
            self.entries[key]=(start,count+1)
            while len(self.entries)>self.max_keys:self.entries.popitem(last=False)
            return count<limit


def install_live(app,site):
    if os.getenv('RADAR_PLANNING_LIVE_ENABLED','0')!='1':return False
    try:
        root,config=validate_assets(site)
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        app.logger.warning('Live planning assets unavailable; keeping previous snapshot')
        return False
    from flask import jsonify,request
    from services.planning_parcel_catalog import install_catalog
    from services.planning_tiles import install_tiles
    cache=Path(site)/'data/planning/tile-cache'
    if not install_tiles(app,cache,prefix='/api/planning/gis-tiles',max_entries=512,
                         metadata_directory=root/'metadata'):
        return False
    install_catalog(app,root/'parcels.sqlite',prefix='/api/planning/parcels',expanded=True)
    old=app.config.get('PLANNING_OVERLAY_CONFIG')
    layers=[]
    if old:
        path=Path(site)/old['catalogUrl'].lstrip('/')
        layers=json.loads(path.read_text(encoding='utf8'))['layers']
        for item in layers:
            if item.get('source')=='gis':item['inspection_only']=True
    layers.extend(app.extensions['planning_native_layers'])
    from config.planning_regions import LANDUSE_2030_LAYERS, VISION_100_LAYERS, TRANSPORT_LAYERS, ADMINISTRATIVE_LAYERS
    layers.extend((*LANDUSE_2030_LAYERS, *VISION_100_LAYERS, *TRANSPORT_LAYERS, *ADMINISTRATIVE_LAYERS))
    app.config['PLANNING_OVERLAY_CONFIG']={
        'catalogUrl':'/api/planning/catalog.json',
        'assetBase':old['assetBase'] if old else '/static/maps/planning/overlays/',
        'parcelBase':'/api/planning/parcels','release':config['release']}
    @app.get('/api/planning/catalog.json')
    def planning_live_catalog():return jsonify(layers=layers)

    limiter=PlanningLimiter()
    @app.before_request
    def limit_planning():
        if not request.path.startswith('/api/planning/'):return None
        from auth.core import client_ip_from_request
        kind='tile' if request.path.startswith('/api/planning/gis-tiles/') else 'lookup' if request.path.endswith('/planning.json') else 'parcel'
        if not limiter.allow(client_ip_from_request(),kind,{'tile':9000,'parcel':1800,'lookup':120}[kind]):
            response=jsonify(error='Thao tác quá nhanh. Vui lòng thử lại sau.')
            response.status_code=429;response.headers['Retry-After']='60';return response

    @app.after_request
    def planning_private(response):
        if request.path.startswith('/api/planning/'):
            response.headers['Cache-Control']='private, no-store'
            response.headers['X-Robots-Tag']='noindex, nofollow'
            response.headers.pop('X-Radar-Public-Cache',None)
        return response
    return True

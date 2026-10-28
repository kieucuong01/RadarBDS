"""Bounded local gateway for the official GIS native zoom grid; no image scaling."""
from __future__ import annotations

from hashlib import sha256
from contextlib import contextmanager
from io import BytesIO
import json
import math
from pathlib import Path
import os
import queue
import threading
import time

from PIL import Image
import requests

from services.planning_parcels import API, SOURCE
from config.planning_regions import PLANNING_BOUNDS, PLANNING_REGIONS

SERVICES = {'partition':'SuDungDat_QHPK_HCM_V2','urban_general':'SuDungDat_QHC_HCM'}
PARTITION_SUPPLEMENT = 'QHXD_SDD_2025_QHPK_V3'
SUPPLEMENTS = {'partition':PARTITION_SUPPLEMENT,'urban_general':'QHXD_SDD_2025_QHCDT'}
METADATA_SERVICES = {**SERVICES,**{theme+'_supplement':service for theme,service in SUPPLEMENTS.items()}}
ORIGIN = math.pi*6378137
RESOLUTION = 2*ORIGIN/256
HEADERS = {'User-Agent':'Mozilla/5.0','Referer':SOURCE,'Origin':'https://gisxaydung.tphcm.gov.vn'}


def tile_bounds(z,x,y):
    if any(type(v) is not int for v in (z,x,y)) or not 8 <= z <= 23 or not (0 <= x < 2**z and 0 <= y < 2**z):
        raise ValueError('Invalid native tile coordinates')
    span = 2*ORIGIN/2**z
    return (-ORIGIN+x*span,ORIGIN-(y+1)*span,-ORIGIN+(x+1)*span,ORIGIN-y*span)


def validate_grid(metadata):
    info = metadata.get('tileInfo',{})
    sr = info.get('spatialReference',{})
    origin = info.get('origin',{})
    lods = {row['level']:row['resolution'] for row in info.get('lods',[])}
    if (info.get('rows') != 256 or info.get('cols') != 256
            or sr.get('latestWkid',sr.get('wkid')) != 3857
            or abs(origin.get('x',0)+ORIGIN)>.001 or abs(origin.get('y',0)-ORIGIN)>.001
            or any(z not in lods or not math.isclose(lods[z],RESOLUTION/2**z,rel_tol=1e-8) for z in range(8,24))):
        raise ValueError('Official GIS grid differs from XYZ Web Mercator')


def validate_png(payload):
    if not payload.startswith(b'\x89PNG\r\n\x1a\n') or len(payload)>2_000_000:
        raise ValueError('Invalid native GIS tile data')
    with Image.open(BytesIO(payload)) as im:
        if im.size != (256,256):
            raise ValueError('Unexpected native tile dimensions')
        im.verify()


class NativeGISTiles:
    def __init__(self,directory,max_entries=4096,metadata_directory=None):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True,exist_ok=True)
        self.max_entries = max_entries
        self.count = len(list(self.directory.rglob('*.png')))
        self.lock = threading.Lock()
        self.gate = threading.BoundedSemaphore(4)
        self.sessions = queue.LifoQueue()
        for _ in range(4):
            session=requests.Session();session.trust_env=False;session.headers.update(HEADERS);self.sessions.put(session)
        self.flights = {}
        self.verified = False
        metadata_directory = Path(metadata_directory) if metadata_directory else self.directory/'metadata'
        try:
            for theme in METADATA_SERVICES:
                validate_grid(json.loads((metadata_directory/f'{theme}.json').read_text(encoding='utf8')))
            self.verified = True
        except (OSError,ValueError,KeyError,TypeError):
            pass

    @contextmanager
    def write_lock(self):
        with self.lock:
            with (self.directory/'.cache.lock').open('ab') as lock:
                if os.name=='posix':
                    import fcntl
                    fcntl.flock(lock,fcntl.LOCK_EX)
                try:yield
                finally:
                    if os.name=='posix':fcntl.flock(lock,fcntl.LOCK_UN)

    def fetch(self,theme,z,x,y):
        if not self.verified:
            raise ValueError('Native GIS metadata has not been verified')
        session=self.sessions.get(timeout=3)
        try:
            primary = self._fetch_service(session,SERVICES[theme],z,x,y)
            foreground = Image.open(BytesIO(primary)).convert('RGBA')
            low,high = foreground.getchannel('A').getextrema()
            if low == 255:
                return primary
            supplement = self._fetch_service(session,SUPPLEMENTS[theme],z,x,y)
            if high == 0:
                return supplement
            background = Image.open(BytesIO(supplement)).convert('RGBA')
            if background.getchannel('A').getbbox() is None:
                return primary
            # Both official images share this exact native grid; primary pixels stay on top.
            output = BytesIO()
            Image.alpha_composite(background,foreground).save(output,format='PNG')
            return output.getvalue()
        finally:
            self.sessions.put(session)

    @staticmethod
    def _public_get(session,url,params=None):
        for attempt in range(2):
            try:
                response=session.get(url,params=params,timeout=(4,12),allow_redirects=False)
                if attempt==0 and response.status_code in (429,500,502,503,504):
                    time.sleep(.25);continue
                return response
            except (requests.ConnectionError,requests.Timeout):
                if attempt:raise
                time.sleep(.25)

    def _fetch_service(self,session,service,z,x,y):
        base = API+'/arcm/rest/services/HCM/'+service+'/MapServer'
        # This endpoint is public. A parcel JWT in Authorization makes ArcGIS reject it.
        response = self._public_get(session,base+f'/tile/{z}/{y}/{x}')
        if response.status_code == 404:
            bbox = tile_bounds(z,x,y)
            params = {'bbox':','.join(map(str,bbox)),'bboxSR':3857,'imageSR':3857,
                      'size':'256,256','format':'png32','transparent':'true','f':'json'}
            meta = self._public_get(session,base+'/export',params=params)
            meta.raise_for_status(); data = meta.json(); extent = data.get('extent',{})
            if (data.get('width') != 256 or data.get('height') != 256
                    or extent.get('spatialReference',{}).get('latestWkid',extent.get('spatialReference',{}).get('wkid')) not in (3857,102100)
                    or any(abs(extent.get(k,math.inf)-v)>.00001 for k,v in zip(('xmin','ymin','xmax','ymax'),bbox))):
                raise ValueError('GIS fallback export changed the native grid')
            params['f'] = 'image'
            response = self._public_get(session,base+'/export',params=params)
        if response.status_code != 200:
            raise ValueError('Official GIS tile is unavailable')
        validate_png(response.content)
        return response.content

    def get(self,theme,z,x,y):
        if theme not in SERVICES:
            raise ValueError('Unknown planning collection')
        west,south,east,north = tile_bounds(z,x,y)
        lon1,lon2 = math.degrees(west/6378137),math.degrees(east/6378137)
        lat1,lat2 = math.degrees(math.atan(math.sinh(south/6378137))),math.degrees(math.atan(math.sinh(north/6378137)))
        (min_lat,min_lon),(max_lat,max_lon) = PLANNING_BOUNDS[theme]
        if lon2 < min_lon or lon1 > max_lon or lat2 < min_lat or lat1 > max_lat:
            raise LookupError('Tile outside supported area')
        source_key = SERVICES[theme]+'-'+SUPPLEMENTS[theme]
        path = self.directory/theme/source_key/str(z)/str(x)/f'{y}.png'
        def read():
            try:
                if time.time()-path.stat().st_mtime<86400:
                    data = path.read_bytes();validate_png(data);return data
            except (OSError,ValueError):
                pass
            return None
        cached = read()
        if cached is not None:
            return cached
        key = (theme,z,x,y)
        with self.lock:
            event = self.flights.get(key)
            owner = event is None
            if owner:
                if len(self.flights)>=32:
                    raise TimeoutError('Native GIS queue is full')
                event = self.flights[key] = threading.Event()
        if not owner:
            event.wait(30)
            cached = read()
            if cached is None: raise TimeoutError('Native tile load did not finish')
            return cached
        try:
            if not self.gate.acquire(timeout=3):
                raise TimeoutError('Native GIS is busy')
            try:
                payload = self.fetch(theme,z,x,y);validate_png(payload)
            finally:
                self.gate.release()
            path.parent.mkdir(parents=True,exist_ok=True)
            with self.write_lock():
                temporary = path.with_name(path.name+f'.{os.getpid()}.{threading.get_ident()}.download');temporary.write_bytes(payload);temporary.replace(path)
                audit=json.dumps({'source':API+'/arcm/rest/services/HCM/'+SERVICES[theme]+'/MapServer',
                    'supplement_source':API+'/arcm/rest/services/HCM/'+SUPPLEMENTS[theme]+'/MapServer',
                    'z':z,'x':x,'y':y,'size':[256,256],'bounds_3857':tile_bounds(z,x,y),
                    'sha256':sha256(payload).hexdigest(),'captured_at':time.time(),'resampled':False})
                audit_temp=temporary.with_suffix('.json.download');audit_temp.write_text(audit,encoding='utf8');audit_temp.replace(path.with_suffix('.json'))
                # Recount shared disk contents: production has several worker processes.
                files=[]
                for candidate in self.directory.rglob('*.png'):
                    try: files.append((candidate.stat().st_mtime,candidate))
                    except FileNotFoundError: pass
                files=[p for _,p in sorted(files)]
                self.count=len(files)
                if self.count>self.max_entries:
                    for old in files[:self.count-self.max_entries]:
                        old.unlink(missing_ok=True);old.with_suffix('.json').unlink(missing_ok=True);self.count -= 1
            return payload
        finally:
            with self.lock:
                self.flights.pop(key,None);event.set()


def native_layers(prefix='/local-planning/gis-tiles'):
    result=[]
    for theme in SERVICES:
        region = 'TP.HCM mới' if theme=='partition' else 'Bình Dương (cũ)'
        area_id = 'hcm-expanded' if theme=='partition' else 'binh-duong-legacy'
        identifier=('hcm-expanded' if theme=='partition' else 'binh-duong')+'-'+theme.replace('_','-')+'-native-gis'
        title = 'Phân khu và quy hoạch chung xã' if theme=='partition' else 'Quy hoạch chung đô thị'
        manifest={'id':identifier,'status':'reference_overlay' if prefix.startswith('/api/') else 'local_experiment','title':title+' · '+region,
                  'bounds':PLANNING_BOUNDS[theme],'source_kind':'official_gis',
                  'alignment_method':'official_coordinates','legend_available':False,'map_scale':None,
                  'render_mode':'xyz','tile_template':prefix+'/'+theme+'/{z}/{x}/{y}.png',
                  'tile_size':256,'min_zoom':8,'max_zoom':23,
                  'notice':'Ô GIS gốc trên cùng lưới zoom; bổ sung vùng trống từ '+SUPPLEMENTS[theme]+' dưới lớp nền chính. '
                    +'Lưu đệm tối đa 24 giờ. Vùng trống không đồng nghĩa không có quy hoạch; chưa xác minh hiệu lực hoặc độ chính xác địa chính.'}
        result.append({'id':identifier,'name':manifest['title'],'city':region,'scope':'region',
                       'area_id':area_id,'theme':theme,'source':'gis','status':'overlay_ready',
                       'decision':'Theo từng đồ án trên GIS','source_url':SOURCE,'manifest':manifest})
    return result


def install_tiles(app,directory,prefix='/local-planning/gis-tiles',max_entries=4096,metadata_directory=None):
    from flask import jsonify,make_response
    cache=NativeGISTiles(directory,max_entries=max_entries,metadata_directory=metadata_directory)
    if not cache.verified:return False
    app.extensions['planning_native_layers']=native_layers(prefix)
    app.extensions['planning_navigation_regions']=PLANNING_REGIONS
    @app.get(prefix+'/<theme>/<int:z>/<int:x>/<int:y>.png')
    def planning_tile(theme,z,x,y):
        try:
            if theme not in SERVICES:raise ValueError('Unknown collection')
            tile_bounds(z,x,y)
        except ValueError:
            return jsonify(error='Ô bản đồ không hợp lệ.'),400
        try:
            payload=cache.get(theme,z,x,y)
            response=make_response(payload);response.mimetype='image/png';return response
        except LookupError:
            return jsonify(error='Ngoài vùng hỗ trợ.'),404
        except TimeoutError:
            response=jsonify(error='GIS đang bận. Thử lại sau.');response.status_code=503;response.headers['Retry-After']='2';return response
        except (requests.RequestException,ValueError,OSError):
            return jsonify(error='Chưa tải được ô GIS gốc.'),502
    return True

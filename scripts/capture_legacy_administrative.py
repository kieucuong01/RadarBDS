"""Curate the public, pre-merger ward-polygon snapshot, keeping source identifiers."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import unicodedata
from zipfile import ZipFile

from shapely.geometry import shape
from scripts.capture_administrative_boundaries import write_snapshot
from scripts.capture_national_administrative import publish_registry

ROOT=Path(__file__).resolve().parents[1]
SOURCE='https://github.com/phuongnt-oe/vietnam-polygon-export-tool'
REVISION='f5ea3e3225b9af3534d293ac42dafa0ab82f9c85'
BLOB='d9bb9e9705603b2ce555543834e8740ba025156b'


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD',value.lower().replace('đ','d')) if not unicodedata.combining(c)).replace('–','-').replace(' ','').replace('-','')


def capture(archive):
    raw=archive.read_bytes()
    assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==BLOB
    with ZipFile(archive) as z:
        assert z.namelist()==['ward_polygons.geojson']
        source=json.loads(z.read('ward_polygons.geojson'))
    assert source['type']=='FeatureCollection' and len(source['features'])==10038
    provinces=json.loads((ROOT/'config/planning_landuse_areas.json').read_text(encoding='utf8'))['provinces']
    by_name={normalized(p['name']):p for p in provinces}
    by_name.update({normalized('Hồ Chí Minh'):next(p for p in provinces if p['id']=='hcm'),
                    normalized('Huế'):next(p for p in provinces if p['id']=='thua-thien-hue')})
    groups=defaultdict(list);seen=set()
    for feature in source['features']:
        p=feature['properties'];code=p['wardCode']
        assert code not in seen and 5<=len(code)<=8 and code.isascii() and code.isalnum()
        seen.add(code);province=by_name[normalized(p['provinceName'])]
        geometry=shape(feature['geometry'])
        w,s,e,n=geometry.bounds
        assert 101<w<e<119 and 6<s<n<25 and geometry.is_valid and not geometry.is_empty
        groups[province['id']].append((p,geometry))
    assert set(groups)=={p['id'] for p in provinces}
    layers=[]
    for province in provinces:
        slug=province['id'];rows=[];geometries=[]
        for index,(p,g) in enumerate(sorted(groups[slug],key=lambda x:x[0]['wardCode']),1):
            rows.append({'attributes':{'MaPhuongXa':p['wardCode'],'TenXa':p['wardName'],
                'OBJECTID':index,'TenTinhCu':p['provinceName'],'TenHuyenCu':p['districtName']}})
            geometries.append(g)
        output=ROOT/'static/data/admin_vn_legacy'/slug
        write_snapshot(output,rows,geometries,{'source_url':SOURCE,'source_service':'data/ward_polygons.zip#'+slug,
            'source_revision':REVISION,'source_blob_sha1':BLOB,'boundary_vintage':'pre-merger; exact survey date unspecified',
            'identifier_scheme':'Upstream wardCode; not official GSO codes'})
        overview=json.loads((output/'overview.json').read_text(encoding='utf8'));count=len(rows)
        identifier=slug+'-administrative-legacy'
        notice=f'{count} phường/xã cũ theo bản GeoJSON công khai trước sáp nhập; nguồn chưa ghi ngày đo/hiệu lực cụ thể. Mã là mã riêng của nguồn, không phải mã TCTK. Có thể khác các lần điều chỉnh trước 01/7/2025; chỉ dùng tham khảo.'
        layers.append({'id':identifier,'name':f'Địa giới {province["name"]} (cũ) · {count} phường/xã',
            'city':province['name']+' (cũ)','scope':'region','area_id':province['region_id'],
            'coverage_provinces':[slug],'theme':'administrative_legacy','source':'gis','status':'overlay_ready',
            'decision':'Ranh phường/xã trước sáp nhập từ GeoJSON công khai; bản tham khảo',
            'source_url':SOURCE,'manifest':{'id':identifier,'status':'reference_overlay','title':'Địa giới '+province['name']+' (cũ)',
                'source_kind':'open_administrative_reference','render_mode':'geojson',
                'geojson_url':f'/static/data/admin_vn_legacy/{slug}/overview.json?v=legacy-admin-20261031',
                'bounds':overview['bounds'],'unit_count':count,'map_scale':None,'legend_available':False,
                'attribution':f'<a href="{SOURCE}/tree/{REVISION}" target="_blank" rel="noopener noreferrer">Địa giới cũ · Vietnam Polygon Export Tool · dữ liệu tham khảo</a>',
                'notice':notice}})
    (ROOT/'config/planning_administrative_legacy.json').write_text(json.dumps({'source_checked_on':'2026-10-31',
        'source_revision':REVISION,'source_blob_sha1':BLOB,'layers':layers},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    publish_registry(json.loads((ROOT/'config/planning_administrative.json').read_text(encoding='utf8'))['layers'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--archive',type=Path,required=True)
    capture(parser.parse_args().archive)

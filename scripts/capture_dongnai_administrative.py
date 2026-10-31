"""Build the 95-unit Dong Nai open reference snapshot from pinned local GeoJSON."""
import argparse
import json
from pathlib import Path
from shapely.geometry import shape
from scripts.capture_administrative_boundaries import write_snapshot

SOURCE='https://github.com/thanglequoc/vietnamese-provinces-database'


def capture(source,output):
    entries=json.loads((source/'github-wards-dir.json').read_text(encoding='utf8'))
    revision=json.loads((source/'github-commit.json').read_text(encoding='utf8'))['sha']
    assert len(entries)==95
    rows=[];geometries=[]
    for entry in sorted(entries,key=lambda item:item['name']):
        data=json.loads((source/entry['name']).read_text(encoding='utf8'))
        assert data['type']=='FeatureCollection' and len(data['features'])==1
        f=data['features'][0];p=f['properties'];code=p['code']
        assert len(code)==5 and code.isdecimal()
        geometry=shape(f['geometry'])
        w,s,e,n=geometry.bounds
        assert 106<w<e<109 and 10<s<n<13
        rows.append({'attributes':{'MaPhuongXa':code,'TenXa':p['fullName'],
            'OBJECTID':int(code),'TenTinhCu':''}})
        geometries.append(geometry)
    assert len({r['attributes']['MaPhuongXa'] for r in rows})==95
    write_snapshot(output,rows,geometries,{'source_url':SOURCE,
        'source_service':'json/geojson/75_dong_nai/wards','source_revision':revision,
        'source_license':'MIT','reference_url':'https://sapnhap.bando.com.vn/'})
    (output/'LICENSE.txt').write_text((source/'SOURCE-LICENSE.txt').read_text(encoding='utf8'),encoding='utf8')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('static/data/admin_dongnai_2025'))
    args=parser.parse_args();capture(args.source,args.output)

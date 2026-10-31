"""Curate the other 32 new provinces from the same pinned open boundary source."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from shapely.geometry import shape
from scripts.capture_administrative_boundaries import write_snapshot

ROOT=Path(__file__).resolve().parents[1]
SOURCE='https://github.com/thanglequoc/vietnamese-provinces-database'
REVISION='8b78ba5118715e1fa81769286724db79346abf52'
COVERAGE={
 '01':['ha-noi'],'04':['cao-bang'],'08':['ha-giang','tuyen-quang'],
 '11':['dien-bien'],'12':['lai-chau'],'14':['son-la'],'15':['lao-cai','yen-bai'],
 '19':['bac-kan','thai-nguyen'],'20':['lang-son'],'22':['quang-ninh'],
 '24':['bac-giang','bac-ninh'],'25':['phu-tho','vinh-phuc','hoa-binh'],
 '31':['hai-phong','hai-duong'],'33':['hung-yen','thai-binh'],
 '37':['ninh-binh','ha-nam','nam-dinh'],'38':['thanh-hoa'],'40':['nghe-an'],
 '42':['ha-tinh'],'44':['quang-binh','quang-tri'],'46':['thua-thien-hue'],
 '48':['da-nang','quang-nam'],'51':['quang-ngai','kon-tum'],
 '52':['gia-lai','binh-dinh'],'56':['khanh-hoa','ninh-thuan'],
 '66':['dak-lak','phu-yen'],'68':['lam-dong','binh-thuan','dak-nong'],
 '75':['dong-nai','binh-phuoc'],'79':['hcm','binh-duong','brvt'],
 '80':['tay-ninh','long-an'],'82':['dong-thap','tien-giang'],
 '86':['vinh-long','ben-tre','tra-vinh'],'91':['an-giang','kien-giang'],
 '92':['can-tho','hau-giang','soc-trang'],'96':['ca-mau','bac-lieu']}


def vertices(coordinates):
    if coordinates and isinstance(coordinates[0],(int,float)):
        return 1
    return sum(vertices(c) for c in coordinates)


def capture(source):
    provinces=json.loads((source/'provinces-wards.json').read_text(encoding='utf8'))
    tree=json.loads((source/'geojson-tree.json').read_text(encoding='utf8'))
    assert not tree.get('truncated') and len(provinces)==34
    assert sum(len(p['Wards']) for p in provinces)==3321
    existing=json.loads((ROOT/'config/planning_administrative.json').read_text(encoding='utf8'))
    layers=[x for x in existing['layers'] if x['id'] in ('hcm-administrative-2025','dongnai-administrative-2025')]
    assert len(layers)==2
    for province in provinces:
        code=province['Code']
        if code in ('75','79'):
            continue
        directory=code+'_'+province['CodeName']
        entries=[x for x in tree['tree'] if x['type']=='blob' and x['path'].startswith(directory+'/wards/')]
        expected={w['Code']:w['FullName'] for w in province['Wards']}
        assert len(entries)==len(expected)
        rows=[];geometries=[]
        for entry in sorted(entries,key=lambda e:e['path']):
            path=source/'source'/entry['path'];raw=path.read_bytes()
            assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==entry['sha'],str(path)
            data=json.loads(raw);assert data['type']=='FeatureCollection' and len(data['features'])==1
            feature=data['features'][0];p=feature['properties'];ward=p['code']
            assert ward in expected and p['fullName']==expected[ward]
            geometry=shape(feature['geometry']);w,s,e,n=geometry.bounds
            assert 100<w<e<119 and 6<s<n<25,(ward,geometry.bounds)
            if not geometry.is_valid:
                raise ValueError('Invalid source polygon: '+ward)
            rows.append({'attributes':{'MaPhuongXa':ward,'TenXa':p['fullName'],'OBJECTID':int(ward),'TenTinhCu':''}})
            geometries.append(geometry)
        assert {r['attributes']['MaPhuongXa'] for r in rows}==set(expected)
        output=ROOT/'static/data/admin_vn_2025'/code
        write_snapshot(output,rows,geometries,{'source_url':SOURCE,'source_service':'json/geojson/'+directory+'/wards',
            'source_revision':REVISION,'source_license':'MIT','reference_url':'https://sapnhap.bando.com.vn/'})
        overview=json.loads((output/'overview.json').read_text(encoding='utf8'))
        assert all(shape(f['geometry']).is_valid for f in overview['features']),code
        count=len(expected);identifier='vn-'+code+'-administrative-2025'
        name=province['Name']
        layers.append({'id':identifier,'name':f'Địa giới hành chính {name} mới · {count} đơn vị',
            'city':name+' mới','scope':'region','area_id':'vn-'+code+'-expanded',
            'coverage_provinces':COVERAGE[code],'theme':'administrative','source':'gis',
            'status':'overlay_ready','decision':f'Ranh {count} xã/phường/đặc khu từ dữ liệu mở, chỉ tham khảo',
            'source_url':SOURCE,'manifest':{'id':identifier,'status':'reference_overlay',
            'title':'Địa giới hành chính '+name+' mới','source_kind':'open_administrative_reference',
            'render_mode':'geojson','geojson_url':f'/static/data/admin_vn_2025/{code}/overview.json?v=national-admin-20261031',
            'bounds':overview['bounds'],'unit_count':count,'map_scale':None,'legend_available':False,
            'attribution':f'<a href="{SOURCE}" target="_blank" rel="noopener noreferrer">Địa giới {name} · Vietnamese Provinces Database (MIT)</a>',
            'notice':f'{count} đơn vị cấp xã của {name} mới. Nguồn mở tổng hợp, không thay hồ sơ địa giới pháp lý. Tổng quan giản lược 10 m; từ zoom 13 tải ranh gốc theo vùng nhìn.'}})
        print(name,count,flush=True)
    (ROOT/'static/data/admin_vn_2025/LICENSE.txt').write_text((ROOT/'static/data/admin_dongnai_2025/LICENSE.txt').read_text(encoding='utf8'),encoding='utf8')
    (ROOT/'config/planning_administrative.json').write_text(json.dumps({'source_checked_on':'2026-10-31','layers':layers},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    publish_registry(layers)


def publish_registry(layers):
    legacy=ROOT/'config/planning_administrative_legacy.json'
    if legacy.exists():layers=[*layers,*json.loads(legacy.read_text(encoding='utf8'))['layers']]
    registry={}
    for item in layers:
        m=item['manifest'];base,query=m['geojson_url'].split('overview.json')
        data=json.loads((ROOT/base.lstrip('/')/'overview.json').read_text(encoding='utf8'))
        full=[json.loads((ROOT/base.lstrip('/')/(f['properties']['code']+'.json')).read_text(encoding='utf8')) for f in data['features']]
        max_vertices=max(vertices(f['geometry']['coordinates']) for f in full)
        max_polygons=max(len(f['geometry']['coordinates']) if f['geometry']['type']=='MultiPolygon' else 1 for f in full)
        assert max_polygons<=2048,(item['id'],max_polygons)
        assert max_vertices<=100000,(item['id'],max_vertices)
        b=m['bounds'];limits=[math.floor(b[0][0]*100)/100-.01,math.floor(b[0][1]*100)/100-.01,
            math.ceil(b[1][0]*100)/100+.01,math.ceil(b[1][1]*100)/100+.01]
        if item['id']=='hcm-administrative-2025':limits=[8.5,106.25,11.65,107.75]
        if item['id']=='dongnai-administrative-2025':limits=[10,106,13,109]
        registry[item['id']]={'theme':item['theme'],'base':base,'query':query,'url':m['geojson_url'],'bounds':b,
            'limits':limits,'count':m['unit_count'],'source':item['source_url'],'kind':m['source_kind'],
            'service':data['source_service'],'max_vertices':max(20000,max_vertices),'max_polygons':max(500,max_polygons),
            'codes':[f['properties']['code'] for f in data['features']]}
    source='// Generated by scripts/capture_national_administrative.py; exact published source allowlist.\n'
    source+="(function(root){'use strict';var sources="+json.dumps(registry,ensure_ascii=False,separators=(',',':'))+';'
    source+="if(typeof module==='object'&&module.exports)module.exports=sources;if(root)root.RadarAdministrativeSources=sources;})(typeof window!=='undefined'?window:null);\n"
    (ROOT/'static/js/main/planning_administrative_sources.js').write_text(source,encoding='utf8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args();capture(args.source)

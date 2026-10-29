"""Capture public transport lines without drawing or joining inferred route segments."""
import argparse
from datetime import date
import json
from pathlib import Path

from services.planning_parcels import API, PublicGIS

BASE = '/arcgis/rest/services/HCM/'
RING1_NAMES = {'Phạm Văn Đồng', 'Hương lộ 2 - Thoại Ngọc Hầu', 'Đường Vành Đai Trong',
               'Hoàng Văn Thụ', 'Bạch Đằng',
               'Hồng Lạc-Hoàng Văn Thụ-Trần Quốc Hoàn-Trường Sơn-Bạch Đằng-Hồng Hà'}


def query(client, service, layer, **params):
    response = client.session.get(API+BASE+service+'/FeatureServer/'+str(layer)+'/query',
        params={'f':'json','where':'1=1','outSR':4326,'resultRecordCount':1000,
                'orderByFields':'OBJECTID ASC', **params}, timeout=(5,25))
    response.raise_for_status()
    data=response.json()
    if data.get('error') or data.get('exceededTransferLimit'):
        raise ValueError('Incomplete transport response')
    assert data.get('spatialReference',{}).get('wkid') == 4326 or params.get('returnGeometry')=='false'
    return data['features']


def feature(row, service, layer, group):
    a=row['attributes'];paths=row['geometry']['paths']
    assert paths and all(len(p)>=2 for p in paths)
    name=a['TenDuong']
    return {'type':'Feature','geometry':{'type':'MultiLineString','coordinates':paths},
        'properties':{'source_id':a['OBJECTID'],'source_service':service,'source_layer':layer,
          'name':name,'group':group,'source_status':a.get('phanLoai') or 'Theo lớp Giao thông hiện trạng',
          'label':('VĐ2 · theo GIS' if group=='ring2' else 'VĐ1 · đoạn đối chiếu' if group=='ring1_segments' else name)}}


def capture(output):
    client=PublicGIS();client.guest();features=[]
    for layer,group in [(1,'corridor'),(2,'ring')]:
        rows=query(client,'GiaoThongHienTrang',layer,outFields='OBJECTID,TenDuong,CDai_Km',returnGeometry='true')
        features.extend(feature(r,'GiaoThongHienTrang',layer,group) for r in rows)
    # Name scan is keyset-paged: do not trust a silently capped first 1,000 rows.
    rows=[];last=0
    for _ in range(10):
        response=client.session.get(API+BASE+'HTKT_QHCTP/FeatureServer/14/query', params={
          'f':'json','where':f'OBJECTID > {last}','outFields':'OBJECTID,TenDuong',
          'returnGeometry':'false','resultRecordCount':1000,'orderByFields':'OBJECTID ASC'},timeout=(5,25))
        response.raise_for_status();data=response.json();page=data.get('features',[])
        if data.get('error'):raise ValueError('GIS names unavailable')
        rows.extend(page)
        if not data.get('exceededTransferLimit'):break
        next_id=max(r['attributes']['OBJECTID'] for r in page)
        assert next_id>last;last=next_id
    else:raise ValueError('Transport name scan limit exceeded')
    ids=[str(r['attributes']['OBJECTID']) for r in rows if r['attributes'].get('TenDuong') in RING1_NAMES
         or (r['attributes'].get('TenDuong') or '').startswith('Vành đài 2-')]
    assert 1<=len(ids)<=100
    rows=query(client,'HTKT_QHCTP',14,objectIds=','.join(ids),outFields='OBJECTID,TenDuong,phanLoai',returnGeometry='true')
    assert {r['attributes']['OBJECTID'] for r in rows}==set(map(int,ids))
    features.extend(feature(r,'HTKT_QHCTP',14,'ring2' if r['attributes']['TenDuong'].startswith('Vành đài 2-')
                            else 'ring1_segments') for r in rows)
    points=[p for f in features for line in f['geometry']['coordinates'] for p in line]
    bounds=[[min(p[1] for p in points),min(p[0] for p in points)],
            [max(p[1] for p in points),max(p[0] for p in points)]]
    data={'type':'FeatureCollection','source_checked_on':date.today().isoformat(),
          'source_url':'https://gisxaydung.tphcm.gov.vn/tracuuttqh',
          'ring1_reference_url':'https://ttbc-hcm.gov.vn/xe-khong-dat-chuan-vao-vung-han-che-khi-thai-tp-hcm-co-the-nhan-phat-den-400-000-dong-1020119.html',
          'notice':'VĐ1 là các đoạn đường đã đối chiếu, chưa xác minh tuyến khép kín. Giữ tên và trạng thái từng đoạn GIS; không nối khoảng trống.',
          'bounds':bounds,'features':features}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf8')
    print(json.dumps({'features':len(features),'bytes':output.stat().st_size,'bounds':bounds}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('static/data/planning_transport_roads.geojson'))
    capture(parser.parse_args().output)

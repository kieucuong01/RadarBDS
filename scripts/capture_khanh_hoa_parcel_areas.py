"""Capture safe source locality references, not parcel/owner data."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.planning_khanh_hoa_parcels import KhanhHoaGIS, QUERY, SOURCE

# Codes/names observed in the official public/8192 district selector.
DISTRICTS = {'568':'Thành phố Nha Trang', '569':'Thành phố Cam Ranh',
    '570':'Huyện Cam Lâm', '571':'Huyện Vạn Ninh', '572':'Thị xã Ninh Hòa',
    '573':'Huyện Khánh Vĩnh', '574':'Huyện Diên Khánh', '575':'Huyện Khánh Sơn'}


def references(data):
    if data.get('exceededTransferLimit') or not 0 < len(data['features']) < 1000:
        raise ValueError('Incomplete source references')
    province = next(p for p in json.loads((ROOT/'config/planning_landuse_areas.json').read_bytes())['provinces']
                    if p['id']=='khanh-hoa')
    windows = {d['id']: d['bounds'] for d in province['districts']}
    areas, excluded, seen = [], [], set()
    for row in data['features']:
        attrs = row['attributes']
        code, raw_district = attrs.get('MaXa'), attrs.get('MaHuyen')
        district = str(raw_district or '').strip()
        city, ward = attrs.get('TenHuyen'), attrs.get('TenPhuong')
        if (not isinstance(code, str) or not re.fullmatch(r'\d{5}', code)
                or not isinstance(raw_district, str) or not re.fullmatch(r'\d{3} *', raw_district)
                or district not in DISTRICTS or not isinstance(city, str)
                or not DISTRICTS[district].endswith(' '+city)
                or not isinstance(ward, str) or not 0 < len(ward) <= 100
                or any(ord(c)<32 for c in ward)):
            excluded.append(attrs)
            continue
        key = f'kh-{district}-{code}'
        if key in seen:
            raise ValueError('Ambiguous source locality')
        seen.add(key)
        bounds = windows[district]
        areas.append(dict(code=code, area_id=key, district=district, city=DISTRICTS[district],
                          ward=ward, source_city=city, source_ward=ward, source_district_value=raw_district,
                          province='khanh-hoa', bounds=bounds,
                          center=[sum(p[i] for p in bounds)/2 for i in (0,1)],
                          bounds_kind='historic_district_navigation_window'))
    if {a['district'] for a in areas} != set(DISTRICTS):
        raise ValueError('Missing source district references')
    return dict(source=SOURCE, checked_on='2026-11-02', source_query=QUERY,
                reference_only='Source locality codes/names; district bounds for navigation only, not parcel masks or coverage proof. Trường Sa not supplied.',
                excluded_references=excluded, areas=sorted(areas,key=lambda a:a['area_id']))


if __name__=='__main__':
    data = KhanhHoaGIS().request(QUERY,params=dict(f='json',where='1=1',
        outFields='MaXa,MaHuyen,TenPhuong,TenHuyen',returnGeometry='false',
        returnDistinctValues='true',orderByFields='MaHuyen,MaXa',resultRecordCount=1000))
    result = references(data)
    target = ROOT/'config/planning_khanh_hoa_parcel_areas.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(areas=len(result['areas']),excluded=len(result['excluded_references']))))

import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point,shape
from shapely.ops import transform

ROOT=Path(__file__).resolve().parents[1]


def test_new_province_assets_are_complete_valid_and_keep_original_details():
    catalog=json.loads((ROOT/'config/planning_administrative.json').read_text(encoding='utf8'))['layers']
    assert len(catalog)==34 and sum(x['manifest']['unit_count'] for x in catalog)==3321
    codes=set();project=Transformer.from_crs(4326,3857,always_xy=True).transform
    for item in catalog:
        folder=ROOT/item['manifest']['geojson_url'].split('?')[0].lstrip('/')
        overview=json.loads(folder.read_text(encoding='utf8'));folder=folder.parent
        assert len(overview['features'])==item['manifest']['unit_count']
        largest=None;largest_vertices=0
        for feature in overview['features']:
            p=feature['properties'];assert p['code'] not in codes;codes.add(p['code'])
            detail=json.loads((folder/(p['code']+'.json')).read_text(encoding='utf8'))
            geometry=shape(detail['geometry']);display=shape(feature['geometry'])
            assert detail['properties']==p and geometry.is_valid and display.is_valid
            assert geometry.contains(Point(p['label'][1],p['label'][0]))
            if len(json.dumps(detail['geometry']))>largest_vertices:
                largest_vertices=len(json.dumps(detail['geometry']));largest=(geometry,display)
        assert transform(project,largest[0]).hausdorff_distance(transform(project,largest[1]))<=10.1
    assert len(codes)==3321


def test_administrative_source_registry_load_order_and_licence():
    template=(ROOT/'templates/index.html').read_text(encoding='utf8')
    assert template.index('planning_administrative_sources.js')<template.index('planning_administrative.js')<template.index('planning_overlay.js')
    assert 'MIT License' in (ROOT/'static/data/admin_vn_2025/LICENSE.txt').read_text(encoding='utf8')

import json
import unicodedata
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import transform

ROOT=Path(__file__).resolve().parents[1]


def test_administrative_snapshot_is_complete_and_details_keep_valid_source_polygons():
    folder=ROOT/'static/data/admin_hcm_2025'
    data=json.loads((folder/'overview.json').read_text(encoding='utf8'))
    assert len(data['features'])==168
    assert len(list(folder.glob('*.json')))==169
    assert sum(unicodedata.normalize('NFC',f['properties']['name']).startswith('Phường ') for f in data['features'])==113
    assert sum(unicodedata.normalize('NFC',f['properties']['name']).startswith('Xã ') for f in data['features'])==54
    project=Transformer.from_crs(4326,3857,always_xy=True).transform
    for feature in data['features']:
        p=feature['properties'];full=json.loads((folder/(p['code']+'.json')).read_text(encoding='utf8'))
        geometry=shape(full['geometry']);overview=shape(feature['geometry'])
        assert full['properties']==p and geometry.is_valid and overview.is_valid
        assert geometry.contains(Point(p['label'][1],p['label'][0]))
        assert [list(geometry.bounds)[1::-1],list(geometry.bounds)[3:1:-1]]==p['bounds']
        assert transform(project,geometry).hausdorff_distance(transform(project,overview))<=10.1
    assert (folder/'overview.json').stat().st_size<1_000_000
    assert data['source_service']=='HanhChinhXa/FeatureServer/0'


def test_admin_module_is_loaded_before_overlay_and_keeps_independent_source():
    template=(ROOT/'templates/index.html').read_text(encoding='utf8')
    assert template.index('planning_administrative.js')<template.index('planning_overlay.js')
    data=json.loads((ROOT/'config/planning_administrative.json').read_text(encoding='utf8'))
    item=data['layers'][0]
    assert item['theme']=='administrative' and item['source']=='gis'
    assert item['manifest']['unit_count']==168


def test_dongnai_snapshot_has_95_valid_units_and_reference_provenance():
    folder=ROOT/'static/data/admin_dongnai_2025'
    data=json.loads((folder/'overview.json').read_text(encoding='utf8'))
    assert len(data['features'])==95 and len({f['properties']['code'] for f in data['features']})==95
    assert len(list(folder.glob('*.json')))==96
    assert data['source_url']=='https://github.com/thanglequoc/vietnamese-provinces-database'
    assert data['source_license']=='MIT' and len(data['source_revision'])==40
    assert 'Copyright (c) 2021 Thang Le Quoc' in (folder/'LICENSE.txt').read_text(encoding='utf8')
    project=Transformer.from_crs(4326,3857,always_xy=True).transform
    for feature in data['features']:
        p=feature['properties']
        full=json.loads((folder/(p['code']+'.json')).read_text(encoding='utf8'))
        geometry=shape(full['geometry']);overview=shape(feature['geometry'])
        assert geometry.is_valid and overview.is_valid and full['properties']==p
        assert geometry.contains(Point(p['label'][1],p['label'][0]))
        assert transform(project,geometry).hausdorff_distance(transform(project,overview))<=10.1
    assert (folder/'overview.json').stat().st_size<1_500_000
    item=json.loads((ROOT/'config/planning_administrative.json').read_text(encoding='utf8'))['layers'][1]
    assert item['coverage_provinces']==['dong-nai','binh-phuoc']
    assert item['manifest']['source_kind']=='open_administrative_reference'

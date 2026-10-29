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

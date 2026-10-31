import json
from pathlib import Path

from shapely.geometry import shape,Point

ROOT=Path(__file__).resolve().parents[1]


def test_old_province_snapshot_keeps_source_codes_and_valid_commune_geometries():
    catalog=json.loads((ROOT/'config/planning_administrative_legacy.json').read_text(encoding='utf8'))
    assert len(catalog['layers'])==63
    seen=set();districts=set()
    for item in catalog['layers']:
        path=ROOT/item['manifest']['geojson_url'].split('?')[0].lstrip('/')
        data=json.loads(path.read_text(encoding='utf8'))
        assert data['source_revision']==catalog['source_revision']
        assert data['source_blob_sha1']==catalog['source_blob_sha1']
        assert 'not official GSO' in data['identifier_scheme']
        assert len(data['features'])==item['manifest']['unit_count']
        for feature in data['features']:
            p=feature['properties'];assert p['code'] not in seen;seen.add(p['code'])
            districts.add((p['former_province'],p['district']))
            detail=json.loads(path.with_name(p['code']+'.json').read_text(encoding='utf8'))
            geometry=shape(detail['geometry'])
            assert detail['properties']==p and geometry.is_valid and shape(feature['geometry']).is_valid
            assert geometry.contains(Point(p['label'][1],p['label'][0]))
    assert len(seen)==10038 and len(districts)==692

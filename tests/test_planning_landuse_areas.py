import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_historic_navigation_has_all_supported_provinces_and_districts():
    data = json.loads((ROOT/'config/planning_landuse_areas.json').read_text(encoding='utf8'))
    layers = json.loads((ROOT/'config/planning_landuse_2030.json').read_text(encoding='utf8'))['layers']
    layer_ids = {item['id'] for item in layers}
    assert data['default_province'] == 'binh-duong' and data['default_district'] == '718'
    provinces = data['provinces']
    assert [(p['id'],len(p['districts'])) for p in provinces] == [('binh-duong',9),('hcm',22),('brvt',8),('dong-nai',11),('binh-phuoc',11)]
    assert {i for p in provinces for i in p['layer_ids']} == layer_ids
    for p in provinces:
        assert set(p['layer_ids']) <= layer_ids
        assert len({d['id'] for d in p['districts']}) == len(p['districts'])
        for d in p['districts']:
            (s,w),(n,e) = d['bounds']
            assert 8.5 <= s < n <= 12.4 and 106.25 <= w < e <= 107.7
            assert p['bounds'][0][0] <= s and p['bounds'][0][1] <= w
            assert p['bounds'][1][0] >= n and p['bounds'][1][1] >= e
    phu_rieng = next(d for d in provinces[-1]['districts'] if d['name']=='Phú Riềng')
    assert phu_rieng['source']=='verified_2030_sample_window'

def test_navigation_context_is_available_without_requesting_parcel_config(monkeypatch):
    import app
    monkeypatch.setitem(app.app.config, 'PLANNING_OVERLAY_CONFIG', {'catalogUrl':'/api/planning/catalog.json','assetBase':'/api/planning/'})
    html = app.app.test_client().get('/').get_data(as_text=True)
    assert 'RADAR_LANDUSE_AREAS' in html
    assert 'planning_area.js' in html
    assert html.index('planning_area.js') < html.index('planning_overlay.js')

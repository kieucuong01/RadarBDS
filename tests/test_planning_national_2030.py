"""National 2030 coverage must use verified sources, bounded loading and old names."""
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

def test_national_registry_covers_63_historic_provinces_with_audited_sources():
    from config.planning_regions import LANDUSE_AREAS, LANDUSE_2030_LAYERS, LANDUSE_SOURCE_RULES
    assert len(LANDUSE_AREAS) == 63
    assert len({p['id'] for p in LANDUSE_AREAS}) == 63
    layers = {p['id']:p for p in LANDUSE_2030_LAYERS}
    assert len(layers) == 63
    assert {i for p in LANDUSE_AREAS for i in p['layer_ids']} == set(layers)
    audit = json.loads((ROOT/'config/planning_landuse_2030_audit.json').read_text(encoding='utf8'))
    assert len(audit['provinces']) == 63
    assert all(p['nonempty_samples'] > 0 for p in audit['provinces'])
    for layer in layers.values():
        m = layer['manifest']; rule = LANDUSE_SOURCE_RULES[layer['id']]
        url = urlsplit(m['tile_template'])
        assert url.scheme == 'https' and not url.query and not url.fragment
        assert url.netloc in {'r4gmiynxmeobj.vcdn.cloud','s3.hn-1.cloud.cmctelecom.vn',
                              '251db3a9dce2de5.cmccloud.com.vn','sgp1.digitaloceanspaces.com',
                              'guland.sgp1.cdn.digitaloceanspaces.com','guland2.sgp1.cdn.digitaloceanspaces.com'}
        assert rule['tile_template'] == m['tile_template']
        assert rule['bounds'] == m['bounds']
        assert 8 <= m.get('min_native_zoom',8) <= m['max_native_zoom'] <= 18
        assert m['min_zoom'] >= m.get('min_native_zoom',8)-1
        assert m['source_kind'] == 'guland_reference' and m['legend_available'] is False
        assert layer['source_url'].startswith('https://guland.vn/soi-quy-hoach/')

def test_national_navigation_keeps_defaults_and_reference_district_windows():
    from config.planning_regions import LANDUSE_AREAS
    config = json.loads((ROOT/'config/planning_landuse_areas.json').read_text(encoding='utf8'))
    assert config['default_province'] == 'binh-duong' and config['default_district'] == '718'
    assert sum(len(p['districts']) for p in LANDUSE_AREAS) >= 700
    for p in LANDUSE_AREAS:
        for b in [p['bounds'],p.get('focus_bounds',p['bounds'])]+[d['bounds'] for d in p['districts']]:
            (s,w),(n,e)=b
            assert 7 <= s < n <= 24 and 101 <= w < e <= 118
        assert len({d['id'] for d in p['districts']}) == len(p['districts'])
        assert len({d['name'] for d in p['districts']}) == len(p['districts'])
    # Province overview should centre on the mainland rather than remote islands.
    for ident in ['khanh-hoa','da-nang']:
        p = next(p for p in LANDUSE_AREAS if p['id']==ident)
        assert p['focus_bounds'][1][1] < 110
        assert p['bounds'][1][1] > 112

def test_national_reference_does_not_expand_official_gis_or_parcel_scope():
    from config.planning_regions import HCM_EXPANDED_BOUNDS, PLANNING_BOUNDS
    assert all(b == HCM_EXPANDED_BOUNDS for b in PLANNING_BOUNDS.values())


def test_browser_navigation_omits_unused_shape_audit_fields():
    from config.planning_regions import LANDUSE_PUBLIC_AREAS, LANDUSE_AREAS
    assert [p['id'] for p in LANDUSE_PUBLIC_AREAS] == [p['id'] for p in LANDUSE_AREAS]
    assert all(set(d)=={'id','name','bounds'} for p in LANDUSE_PUBLIC_AREAS for d in p['districts'])
    assert any('source_shape_id' in d for p in LANDUSE_AREAS for d in p['districts'])

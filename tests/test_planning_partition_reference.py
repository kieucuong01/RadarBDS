import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_partition_registry_matches_observed_controls_and_positive_tiles():
    from config.planning_regions import PARTITION_REFERENCE_LAYERS, PARTITION_SOURCE_RULES

    audit = json.loads((ROOT / 'config/planning_partition_reference_audit.json').read_text(encoding='utf8'))
    provinces = audit['provinces']
    assert len(provinces) == len({p['province'] for p in provinces}) == 63
    assert PARTITION_REFERENCE_LAYERS
    for layer in PARTITION_REFERENCE_LAYERS:
        evidence = next(e for p in provinces for e in [p, *p.get('schemes', [])]
                        if e['source_url'] == layer['source_url'])
        manifest = layer['manifest']
        assert evidence['status'] == 'sampled_overlay'
        assert layer['theme'] == 'partition' and layer['source'] == 'guland'
        assert layer['coverage_provinces'] == [layer['area_id'].removesuffix('-legacy')]
        assert not set(layer['coverage_provinces']) & {'hcm', 'binh-duong', 'brvt'}
        if evidence.get('observed_tiles'):
            assert 'phân khu' in evidence['title'].lower()
            assert evidence['tile_template'] == manifest['tile_template']
            assert manifest['focus_bounds']
            assert manifest['max_native_zoom'] >= 15
            f = manifest['focus_bounds']
            centre = [(f[0][i] + f[1][i]) / 2 for i in range(2)]
            assert any(all(abs(s['point'][i] - centre[i]) < 0.00001 for i in range(2))
                       and s.get('pixels', 0) > 1000 and s['z'] >= 15 for s in evidence['samples'])
        else:
            assert any(c['attrs'].get('data-url') == manifest['tile_template'] for c in evidence['controls'])
        good = [s for s in evidence['samples'] if s.get('pixels', 0) > 0 and s.get('size') in ([256, 256], [512, 512])]
        assert good
        assert any(s['z'] == manifest['min_native_zoom'] for s in good)
        assert any(s['z'] == manifest['max_native_zoom'] for s in good)
        assert manifest['min_zoom'] == manifest['min_native_zoom']
        assert manifest['source_kind'] == 'guland_reference'
        assert manifest['map_scale'] is None
        assert PARTITION_SOURCE_RULES[layer['id']]['tile_template'] == manifest['tile_template']


def test_scheme_sources_are_added_only_after_readable_close_zoom_samples():
    from config.planning_regions import PARTITION_REFERENCE_LAYERS

    scheme_provinces = {l['coverage_provinces'][0] for l in PARTITION_REFERENCE_LAYERS
                        if '/xem-quy-hoach/' in l['source_url']}
    assert scheme_provinces == {'bac-kan', 'can-tho', 'ha-nam', 'hung-yen', 'nghe-an',
                                'quang-ngai', 'son-la', 'thanh-hoa', 'vinh-long', 'yen-bai'}


def test_partition_catalogue_is_wired_without_changing_existing_families():
    from flask import Flask
    from app import inject_planning_overlay
    from config.planning_regions import PARTITION_SOURCE_RULES

    app = Flask(__name__)
    with app.app_context():
        assert inject_planning_overlay()['planning_partition_source_rules'] == PARTITION_SOURCE_RULES
    template = (ROOT / 'templates/index.html').read_text(encoding='utf8')
    assert 'window.RADAR_PARTITION_SOURCE_RULES' in template

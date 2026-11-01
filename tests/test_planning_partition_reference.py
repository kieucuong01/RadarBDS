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
        assert '(lyk)' not in layer['name'].lower()
        assert 'lấy ý kiến' not in layer['name'].lower() and 'dự thảo' not in layer['name'].lower()
        evidence = next(e for p in provinces for e in [p, *p.get('schemes', [])]
                        if e['source_url'] == layer['source_url'] and e['status'] == 'sampled_overlay'
                        and (not e.get('tile_template') or e['tile_template'] == layer['manifest']['tile_template']))
        manifest = layer['manifest']
        assert evidence['status'] == 'sampled_overlay'
        assert layer['theme'] == 'partition' and layer['source'] == 'guland'
        assert layer['coverage_provinces'] == [layer['area_id'].removesuffix('-legacy')]
        assert not set(layer['coverage_provinces']) & {'hcm', 'binh-duong', 'brvt'}
        if evidence.get('observed_tiles') or evidence.get('metadata_request_url'):
            assert 'phân khu' in evidence['title'].lower()
            assert evidence['tile_template'] == manifest['tile_template']
            assert manifest['focus_bounds']
            assert manifest['max_native_zoom'] >= 15
            if evidence.get('metadata_request_url'):
                assert evidence['metadata']['url'] == manifest['tile_template']
                assert evidence['load_bounds'] == manifest['bounds']
                assert evidence['metadata_request_url'] == 'https://guland.vn/map-service/detail-layer?id=' + evidence['source_id']
            f = manifest['focus_bounds']
            centre = [(f[0][i] + f[1][i]) / 2 for i in range(2)]
            assert any(s.get('point') and all(abs(s['point'][i] - centre[i]) < 0.00001 for i in range(2))
                       and s.get('pixels', 0) > 1000 and s['z'] >= (manifest['min_zoom'] if evidence.get('district_survey') else 15)
                       for s in evidence['samples'])
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
    assert scheme_provinces >= {'bac-kan', 'can-tho', 'ha-nam', 'hung-yen', 'nghe-an',
                                'quang-ngai', 'son-la', 'thanh-hoa', 'vinh-long', 'yen-bai'}


def test_historic_district_survey_groups_verified_sheets_with_local_load_envelopes():
    import math
    from collections import Counter
    from config.planning_regions import PARTITION_REFERENCE_LAYERS

    audit = json.loads((ROOT / 'config/planning_partition_reference_audit.json').read_text(encoding='utf8'))
    survey = audit['district_survey']
    districts = survey['districts']
    assert len(districts) == len({(d['province'], d['district_id']) for d in districts}) == 671
    assert len({d['province'] for d in districts}) == 60
    assert all(d['status'] == 1 and 'district_id=' + d['district_id'] in d['request_url'] for d in districts)
    counts = Counter(l['coverage_provinces'][0] for l in PARTITION_REFERENCE_LAYERS)
    assert counts['long-an'] >= 2 and counts['dong-nai'] >= 2
    assert not any(p in counts for p in ('hcm', 'binh-duong', 'brvt'))
    assert len(PARTITION_REFERENCE_LAYERS) < 800
    templates = [(l['coverage_provinces'][0], l['manifest']['tile_template']) for l in PARTITION_REFERENCE_LAYERS]
    assert len(set(templates)) == len(templates)
    navigation = json.loads((ROOT / 'config/planning_landuse_areas.json').read_text(encoding='utf8'))['provinces']
    by_province = {p['id']: p for p in navigation}
    for p in audit['provinces']:
        for evidence in p.get('schemes', []):
            if not evidence.get('district_survey'):
                continue
            bounds = evidence['load_bounds']
            province_bounds = by_province[p['province']]['bounds']
            for sample in evidence['samples']:
                if not sample.get('pixels') or sample['z'] < 13:
                    continue
                n = 2 ** sample['z']
                a, (w, h) = sample['alpha_bounds'], sample['size']
                lat = lambda y: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
                pixel_bounds = [[lat(sample['y'] + a[3] / h), (sample['x'] + a[0] / w) / n * 360 - 180],
                                [lat(sample['y'] + a[1] / h), (sample['x'] + a[2] / w) / n * 360 - 180]]
                clipped = [[max(pixel_bounds[0][i], province_bounds[0][i]) for i in range(2)],
                           [min(pixel_bounds[1][i], province_bounds[1][i]) for i in range(2)]]
                if all(clipped[0][i] < clipped[1][i] for i in range(2)):
                    assert all(bounds[0][i] - 0.000001 <= clipped[0][i] and clipped[1][i] <= bounds[1][i] + 0.000001
                               for i in range(2)), evidence['source_id']


def test_partition_catalogue_is_wired_without_changing_existing_families():
    from flask import Flask
    from app import inject_planning_overlay
    from config.planning_regions import PARTITION_SOURCE_RULES

    app = Flask(__name__)
    with app.app_context():
        assert inject_planning_overlay()['planning_partition_source_rules'] == PARTITION_SOURCE_RULES
    template = (ROOT / 'templates/index.html').read_text(encoding='utf8')
    assert 'window.RADAR_PARTITION_SOURCE_RULES' in template

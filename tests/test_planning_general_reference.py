import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_general_sources_match_observed_controls_and_real_geographic_samples():
    from config.planning_regions import GENERAL_REFERENCE_LAYERS, GENERAL_SOURCE_RULES
    audit = json.loads((ROOT/'config/planning_general_reference_audit.json').read_bytes())['provinces']
    assert len(audit) == 63
    by = {p['province']: p for p in audit}
    assert {p['province'] for p in audit if p['status'] == 'existing_gis_preserved'} == {'binh-duong','hcm','brvt'}
    assert {l['coverage_provinces'][0] for l in GENERAL_REFERENCE_LAYERS} == {
        'bac-giang','bac-ninh','hai-duong','hai-phong','nam-dinh','quang-ninh'}
    for layer in GENERAL_REFERENCE_LAYERS:
        p = by[layer['coverage_provinces'][0]]
        m = layer['manifest']
        assert p['status'] == 'verified_samples'
        assert layer['source_url'] == p['source_url']
        assert m['tile_template'] == p['observed_template']
        assert layer['theme'] == GENERAL_SOURCE_RULES[layer['id']]['theme'] == 'urban_general'
        assert layer['source'] == 'guland'
        positives = [s for s in p['samples'] if s.get('positive')]
        assert m['min_native_zoom'] == min(s['z'] for s in positives)
        assert m['min_zoom'] >= m['min_native_zoom']
        assert m['max_native_zoom'] == max(s['z'] for s in positives)
        assert any(s['z'] >= 14 for s in positives)
        assert all(s['status'] == 200 and len(s['sha256']) == 64 for s in positives)
        south, west = m['bounds'][0]
        north, east = m['bounds'][1]
        assert all(south <= s['point'][0] <= north and west <= s['point'][1] <= east for s in positives)


def test_general_rules_are_exposed_separately_from_existing_sources():
    from app import app, inject_planning_overlay
    from config.planning_regions import GENERAL_SOURCE_RULES, PARTITION_SOURCE_RULES, CONSTRUCTION_SOURCE_RULES
    with app.test_request_context('/'):
        context = inject_planning_overlay()
        assert context['planning_general_source_rules'] == GENERAL_SOURCE_RULES
        assert context['planning_partition_source_rules'] == PARTITION_SOURCE_RULES
        assert context['planning_construction_source_rules'] == CONSTRUCTION_SOURCE_RULES

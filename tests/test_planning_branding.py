import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_branding_audit_covers_every_existing_source_and_keeps_review_provenance():
    data=json.loads((ROOT/'config/planning_reference_branding.json').read_text(encoding='utf8'))
    layers=json.loads((ROOT/'config/planning_landuse_2030.json').read_text(encoding='utf8'))['layers']
    assert {x['template'] for x in data['sources']}=={x['manifest']['tile_template'] for x in layers}
    assert {code for x in data['sources'] for code in x['layer_ids']}=={x['id'] for x in layers}
    assert data['coordinate_zoom']==11
    for source in data['sources']:
        assert source['coordinate_zoom']==11 and source['checked_on']=='2026-10-31'
        assert source['evidence'] and all(len(e['mosaic_sha256'])==64 for e in source['evidence'])
        assert source['review']==('logo_footprints_visually_confirmed' if source['rings'] else 'no_logo_observed_in_sampled_imagery')


def test_branding_registry_loads_before_overlay():
    template=(ROOT/'templates/index.html').read_text(encoding='utf8')
    assert template.index('planning_reference_branding.js')<template.index('planning_overlay.js')

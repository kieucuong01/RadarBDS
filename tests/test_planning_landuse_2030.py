"""Reference land-use imagery stays separate from the official GIS plan families."""
import json
from pathlib import Path


def test_landuse_sources_cover_three_former_regions_and_islands_without_relabeling():
    from config.planning_regions import LANDUSE_2030_LAYERS
    assert len(LANDUSE_2030_LAYERS) == 4
    assert len({r['id'] for r in LANDUSE_2030_LAYERS}) == 4
    for layer in LANDUSE_2030_LAYERS:
        assert layer['theme'] == 'land_use_2030' and layer['source'] == 'guland'
        assert layer['manifest']['source_kind'] == 'guland_reference'
        assert layer['manifest']['max_native_zoom'] == 17
        assert layer['manifest']['legend_available'] is False
        assert layer['source_url'].startswith('https://guland.vn/')
    assert {a['area_id'] for a in LANDUSE_2030_LAYERS} == {
        'binh-duong-legacy','hcm-legacy','brvt-legacy','con-dao'}
    config = json.loads((Path(__file__).resolve().parents[1]/'config/planning_landuse_2030.json').read_text(encoding='utf8'))
    assert config['layers'] == list(LANDUSE_2030_LAYERS)

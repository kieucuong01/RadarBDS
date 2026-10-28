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


def test_hcm_reference_window_covers_source_wards_without_loading_empty_northern_row():
    import math
    from config.planning_regions import LANDUSE_2030_LAYERS
    from services.planning_tiles import tile_bounds
    layer = next(a for a in LANDUSE_2030_LAYERS if a['area_id']=='hcm-legacy')
    (south,west),(north,east) = layer['manifest']['bounds']
    areas = json.loads((Path(__file__).resolve().parents[1]/'config/planning_parcel_areas.json').read_text(encoding='utf8'))['areas']
    hcm = [a for a in areas if 760 <= int(a['district']) <= 787]
    assert len(hcm) == 320
    assert all(south <= a['bounds'][0][0] < a['bounds'][1][0] <= north
               and west <= a['bounds'][0][1] < a['bounds'][1][1] <= east for a in hcm)
    # CDN has no HCM images here; the previous wide window requested this row
    # while viewing Bến Cát even though all historic HCM wards are south of it.
    _,tile_south,_,_ = tile_bounds(12,3261,1919)
    assert north < math.degrees(math.atan(math.sinh(tile_south/6378137)))

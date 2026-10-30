"""Reference land-use imagery stays separate from the official GIS plan families."""
import json
from pathlib import Path


def test_landuse_sources_cover_hcm_and_new_dong_nai_without_relabeling():
    from config.planning_regions import LANDUSE_2030_LAYERS
    assert len(LANDUSE_2030_LAYERS) == 63
    assert len({r['id'] for r in LANDUSE_2030_LAYERS}) == 63
    for layer in LANDUSE_2030_LAYERS:
        assert layer['theme'] == 'land_use_2030' and layer['source'] == 'guland'
        assert layer['manifest']['source_kind'] == 'guland_reference'
        capped = {'binh-duong-legacy','hcm-legacy','brvt-legacy','con-dao','dong-nai-expanded','bac-giang-legacy','bac-ninh-legacy'}
        assert layer['manifest']['max_native_zoom'] == (17 if layer['area_id'] in capped else 18)
        assert layer['manifest']['legend_available'] is False
        assert layer['source_url'].startswith('https://guland.vn/')
        visible = [layer['decision'], layer['manifest']['notice']]
        assert all('guland' not in text.lower() for text in visible)
        assert '>Nguồn dữ liệu QH 2030<' in layer['manifest']['attribution']
    assert {'binh-duong-legacy','hcm-legacy','brvt-legacy','con-dao','dong-nai-expanded','tay-ninh-legacy','long-an-legacy'} <= {a['area_id'] for a in LANDUSE_2030_LAYERS}
    config = json.loads((Path(__file__).resolve().parents[1]/'config/planning_landuse_2030.json').read_text(encoding='utf8'))
    assert config['layers'] == list(LANDUSE_2030_LAYERS)


def test_dong_nai_reference_covers_both_former_provinces_on_one_native_grid():
    from config.planning_regions import LANDUSE_2030_LAYERS, PLANNING_REGIONS
    layer = next(a for a in LANDUSE_2030_LAYERS if a['area_id'] == 'dong-nai-expanded')
    manifest = layer['manifest']
    assert manifest['tile_template'] == 'https://s3.hn-1.cloud.cmctelecom.vn/guland9/qh-dong-nai/sdd/{z}/{x}/{y}.png'
    assert manifest['min_native_zoom'] == 9
    assert manifest['max_native_zoom'] == 17
    assert len(manifest['coverage_windows']) == 2
    for lat, lon in [(10.956,106.843),(10.724,106.883),(10.927,107.407),
                     (11.272,107.437),(11.535,106.884),(11.846,106.59),(12.139,107.107)]:
        assert any(s <= lat <= n and w <= lon <= e for (s,w),(n,e) in manifest['coverage_windows'])
    assert not any(s <= 11.13 <= n and w <= 106.61 <= e for (s,w),(n,e) in manifest['coverage_windows'])
    regions = {a['id']: a for a in PLANNING_REGIONS}
    assert {'dong-nai-expanded','dong-nai-legacy','binh-phuoc-legacy'} <= regions.keys()
    assert regions['dong-nai-expanded']['bounds'] == manifest['bounds']


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


def test_new_tay_ninh_sources_keep_two_former_provinces_separate_and_native_zoom_18():
    from config.planning_regions import LANDUSE_2030_LAYERS, LANDUSE_AREAS, PLANNING_REGIONS
    for province, count in [('tay-ninh',9),('long-an',15)]:
        area = next(p for p in LANDUSE_AREAS if p['id']==province)
        layer = next(p for p in LANDUSE_2030_LAYERS if p['area_id']==province+'-legacy')
        manifest = layer['manifest']
        assert len(area['districts']) == count
        assert manifest['tile_template'] == f'https://r4gmiynxmeobj.vcdn.cloud/{province}-2030/{{z}}/{{x}}/{{y}}.png'
        assert manifest['min_zoom']==8 and manifest['max_native_zoom']==18
        assert manifest['max_zoom']==23 and manifest['tile_size']==256
        assert next(r for r in PLANNING_REGIONS if r['id']==province+'-legacy')['bounds'] == manifest['bounds']
        for district in area['districts']:
            (s,w),(n,e) = district['bounds']
            assert manifest['bounds'][0][0]<=s<n<=manifest['bounds'][1][0]
            assert manifest['bounds'][0][1]<=w<e<=manifest['bounds'][1][1]

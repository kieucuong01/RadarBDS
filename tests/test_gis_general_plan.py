"""The general-plan image keeps its native grid; the display mask is not a plan boundary."""
import json

import numpy as np
import pytest
from PIL import Image

from scripts.build_ben_cat_gis_partitions import digest, export_url, write_json
from scripts.build_ben_cat_gis_general import build


def fixture(tmp_path):
    extent = dict(xmin=11850000, ymin=1240000, xmax=11855000, ymax=1245000, spatialReference={'wkid': 3857})
    write_json(tmp_path / 'export.json', dict(width=100, height=100, extent=extent))
    Image.fromarray(np.full((100, 100, 4), [90, 170, 50, 255], dtype='uint8')).save(tmp_path / 'source.png')
    mask = np.zeros((100, 100), dtype='uint8'); mask[10:90, 10:90] = 255
    Image.fromarray(mask).save(tmp_path / 'mask.png')
    url = export_url('https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/SuDungDat_QHC_HCM/MapServer/export',
                     [extent[k] for k in ('xmin', 'ymin', 'xmax', 'ymax')], [100, 100])
    return dict(id='ben-cat-general-gis', title='Quy hoạch chung đô thị · 1/10.000', decision='Hồ sơ đối chiếu 1573/2022',
                map_scale=10000, source_url='https://gisxaydung.tphcm.gov.vn/tracuuttqh', publication_url='https://example.com/decision',
                captured_on='2026-10-27', source_request=url, notice='Chưa xác minh cập nhật điều chỉnh cục bộ.',
                hashes={n: digest(tmp_path / n) for n in ('export.json', 'source.png')},
                display_masks=[dict(path='mask.png', sha256=digest(tmp_path / 'mask.png'), native_extent=extent)],
                reference_area_ha=1540)


def test_general_plan_keeps_native_colors_and_uses_explicit_display_mask(tmp_path):
    config = fixture(tmp_path)
    result = build(config, tmp_path, tmp_path)
    assert result['theme'] == 'urban_general' and result['map_scale'] == 10000
    assert result['alignment_method'] == 'official_coordinates'
    assert result['bounds'][0][0] < result['bounds'][1][0]
    image = Image.open(tmp_path / 'overlay.webp').convert('RGBA')
    assert image.size == (80, 80)
    assert image.getpixel((40, 40)) == (90, 170, 50, 255)
    audit = json.loads((tmp_path / 'alignment-audit.json').read_text())
    assert audit['general_plan_boundary_verified'] is False
    assert audit['currency_verified'] is False
    assert audit['native_extent']['xmin'] == 11850500


def test_general_plan_does_not_mislabel_reference_admin_mask_as_official_plan_boundary(tmp_path):
    config = fixture(tmp_path)
    config['map_scale'] = None
    config['display_mask_method'] = 'Historic administrative snapshot, display clipping only'
    manifest = build(config, tmp_path, tmp_path)
    audit = json.loads((tmp_path / 'alignment-audit.json').read_text())
    assert manifest['map_scale'] is None
    assert audit['display_mask_method'] == config['display_mask_method']
    assert audit['general_plan_boundary_verified'] is False


def test_general_reference_union_adds_missing_regions_without_removing_existing_pixels(tmp_path):
    config = fixture(tmp_path)
    before = build(config, tmp_path, tmp_path)
    extra = np.zeros((100,100),dtype='uint8');extra[5:15,60:95]=255
    Image.fromarray(extra).save(tmp_path/'extra.png')
    config['display_masks'].append(dict(path='extra.png',sha256=digest(tmp_path/'extra.png'),
                                       native_extent=config['display_masks'][0]['native_extent']))
    after = build(config, tmp_path, tmp_path)
    assert after['bounds'][1][0] > before['bounds'][1][0]
    assert after['bounds'][1][1] > before['bounds'][1][1]
    image = np.asarray(Image.open(tmp_path/'overlay.webp').convert('RGBA'))
    assert image[5,0,3] == 255
    assert image[2,55,3] == 255


def test_general_plan_rejects_tampered_capture_or_wrong_service(tmp_path):
    config = fixture(tmp_path)
    config['source_request'] = config['source_request'].replace('SuDungDat_QHC_HCM', 'SuDungDat_QHPK_HCM_V2')
    with pytest.raises(ValueError, match='general-plan service'):
        build(config, tmp_path, tmp_path)
    config = fixture(tmp_path)
    (tmp_path / 'mask.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash'):
        build(config, tmp_path, tmp_path)


def test_general_plan_rejects_missing_data_inside_display_area(tmp_path):
    config = fixture(tmp_path)
    Image.new('RGBA', (100, 100)).save(tmp_path / 'source.png')
    config['hashes']['source.png'] = digest(tmp_path / 'source.png')
    with pytest.raises(ValueError, match='coverage is incomplete'):
        build(config, tmp_path, tmp_path)


def test_display_mask_projects_by_native_extent_instead_of_stretching(tmp_path):
    config = fixture(tmp_path)
    # Move the same mask image half a source width east; only its in-window
    # part contributes. Sampling by array position would incorrectly stay put.
    config['display_masks'][0]['native_extent'] = dict(config['display_masks'][0]['native_extent'], xmin=11852500, xmax=11857500)
    config['reference_area_ha'] = 770
    # The shifted shape reaches the export edge, so a complete city image
    # cannot be silently clipped and published.
    with pytest.raises(ValueError, match='edge-clipped'):
        build(config, tmp_path, tmp_path)

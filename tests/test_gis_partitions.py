"""Native GIS images must share a grid and use the official closed outline."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest

from scripts.build_ben_cat_gis_partitions import (
    DEFAULT_CONFIG, build_layer, digest, download, export_url, export_window, validate_grid, write_json,
)


def test_public_download_uses_working_client_and_preserves_previous_file_on_empty_body(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import requests
    calls = []
    payload = b'\x89PNG\r\n\x1a\nfixture'
    def response(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, content=payload, raise_for_status=lambda: None)
    monkeypatch.setattr(requests, 'get', response)
    target = tmp_path / 'source.png'
    download('https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/example/MapServer/export', target)
    assert target.read_bytes() == payload
    assert calls[0][1]['headers']['Origin'] == 'https://gisxaydung.tphcm.gov.vn'
    payload = b''
    with pytest.raises(RuntimeError, match='empty|Empty'):
        download(calls[0][0], target)
    assert target.read_bytes() == b'\x89PNG\r\n\x1a\nfixture'
    payload = b'<html>Request rejected</html>'
    with pytest.raises(RuntimeError, match='PNG'):
        download(calls[0][0], target)
    assert target.read_bytes() == b'\x89PNG\r\n\x1a\nfixture'


def test_public_download_stops_on_denied_response(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import requests
    calls = []
    def denied(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=401, content=b'denied')
    monkeypatch.setattr(requests, 'get', denied)
    with pytest.raises(RuntimeError, match='401'):
        download('https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/example/MapServer/export', tmp_path / 'source.png')
    assert len(calls) == 1
from scripts.build_ben_cat_official_gis import footprint_mask


def test_catalog_has_eight_distinct_native_partition_sources():
    config = json.loads(DEFAULT_CONFIG.read_text(encoding='utf8'))
    layers = config['layers']
    assert len(layers) == len({row['slug'] for row in layers}) == 8
    assert {row['decision_prefix'] for row in layers} == {'2909', '2910', '2911', '2912', '2913', '1450', '1451', '1452'}
    assert all(row['id'].endswith('-gis-qhpk') and row['map_scale'] == 2000 for row in layers)


def test_thu_dau_mot_uses_twelve_actual_partition_decisions_not_invented_new_town_wards():
    config = json.loads((DEFAULT_CONFIG.parent / 'thu_dau_mot_gis_partitions.json').read_text(encoding='utf8'))
    layers = config['layers']
    assert len(layers) == len({row['id'] for row in layers}) == 12
    assert {row['name'] for row in layers}.isdisjoint({'Hòa Phú', 'Phú Tân'})
    assert all(row['id'].startswith('tdm-') and row['map_scale'] == 2000 for row in layers)
    assert all('NgayKy >=' in row['outline_filter'] and "SoQD LIKE '" in row['outline_filter'] for row in layers)
    assert all(row['plan_identity']['decision_fields'] == ['SoQD', 'NgayKy'] for row in layers)


def test_export_uses_direct_public_image_not_returned_localhost_href():
    url = export_url('https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/ThongTinDoAn/MapServer/export',
                     [1, 2, 3, 4], [100, 100], outline_filter="SoQD_DC LIKE '2913%'")
    query = parse_qs(urlsplit(url).query)
    assert query['f'] == ['image']
    assert query['bboxSR'] == query['imageSR'] == ['3857']
    assert json.loads(query['layerDefs'][0]) == {'0': "SoQD_DC LIKE '2913%'"}
    with pytest.raises(ValueError, match='public GIS'):
        export_url('http://localhost:6080/export', [1, 2, 3, 4], [100, 100])


def test_export_window_is_padded_hint_not_used_as_outline():
    layer = {'window_hint_bounds': [[11, 106], [11.1, 106.1]], 'window_padding_fraction': .2}
    window = export_window(layer)
    assert window[0] < window[2] and window[1] < window[3]
    assert window[2] - window[0] > 11000


def test_grid_rejects_shifted_or_wrong_crs_requests():
    service = 'https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/ThongTinDoAn/MapServer/export'
    export = {'width': 100, 'height': 100, 'extent': {'xmin': 1, 'ymin': 2, 'xmax': 3, 'ymax': 4}}
    validate_grid(export_url(service, [1, 2, 3, 4], [100, 100]), export, (100, 100))
    with pytest.raises(ValueError, match='grid'):
        validate_grid(export_url(service, [2, 2, 4, 4], [100, 100]), export, (100, 100))
    with pytest.raises(ValueError, match='grid'):
        validate_grid(export_url(service, [1, 2, 3, 4], [100, 100]).replace('imageSR=3857', 'imageSR=4326'), export, (100, 100))


def test_outline_rejects_empty_open_multiple_or_edge_clipped_shapes():
    with pytest.raises(ValueError, match='Empty'):
        footprint_mask(np.zeros((40, 40), dtype='uint8'))
    outline = np.zeros((40, 40), dtype='uint8')
    outline[10, 10:30] = outline[29, 10:30] = 255
    outline[10:30, 10] = outline[10:30, 29] = 255
    assert footprint_mask(outline).sum() == 400
    multiple = outline.copy()
    multiple[3:6, 3:6] = 255
    with pytest.raises(ValueError, match='connected'):
        footprint_mask(multiple)
    outline[15:24, 10] = 0
    with pytest.raises(ValueError, match='closed'):
        footprint_mask(outline)
    outline[0, 0] = 255
    with pytest.raises(ValueError, match='clipped'):
        footprint_mask(outline)


def make_capture(directory):
    from PIL import Image
    extent = dict(xmin=11850000, ymin=1240000, xmax=11855000, ymax=1245000, spatialReference={'wkid': 3857})
    export = dict(width=100, height=100, extent=extent)
    write_json(directory / 'export.json', export)
    source = np.full((100, 100, 4), 255, dtype='uint8')
    Image.fromarray(source).save(directory / 'source.png')
    outline = np.zeros((100, 100, 4), dtype='uint8')
    outline[10, 10:90, 3] = outline[89, 10:90, 3] = 255
    outline[10:90, 10, 3] = outline[10:90, 89, 3] = 255
    Image.fromarray(outline).save(directory / 'outline.png')
    service = 'https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/ThongTinDoAn/MapServer/export'
    urls = {key: export_url(service, [extent[k] for k in ('xmin', 'ymin', 'xmax', 'ymax')], [100, 100],
                           outline_filter="SoQD_DC LIKE '2913%'" if key == 'outline' else None) for key in ('source', 'outline')}
    write_json(directory / 'requests.json', urls)
    write_json(directory / 'capture.json', dict(captured_on='2026-10-27', hashes={name: digest(directory / name) for name in ('export.json', 'source.png', 'outline.png', 'requests.json')}))


def test_builder_keeps_native_extent_hashes_and_honest_accuracy_flags(tmp_path):
    make_capture(tmp_path)
    layer = dict(id='fixture-gis-qhpk', title='Fixture', name='Fixture', decision='Fixture', decision_prefix='2913', map_scale=2000,
                 publication_url='https://example.com/ward-specific-publication',
                 plan_identity={'status': 'verified', 'evidence': 'Synthetic test fixture only'})
    manifest = build_layer(dict(source_url='https://example.com', publication_url='https://example.com'), layer, tmp_path)
    assert manifest['theme'] == 'partition_plan'
    assert manifest['publication_url'] == layer['publication_url']
    assert manifest['alignment_method'] == 'official_coordinates'
    assert manifest['artifacts']['overlay.webp'] == digest(tmp_path / 'overlay.webp')
    audit = json.loads((tmp_path / 'alignment-audit.json').read_text(encoding='utf8'))
    assert audit['native_extent']['xmin'] == 11850500
    assert audit['survey_accuracy_verified'] is False
    assert audit['window_hint_is_boundary'] is False
    (tmp_path / 'outline.png').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='hash mismatch'):
        build_layer(dict(source_url='', publication_url=''), layer, tmp_path)


def test_unverified_plan_identity_cannot_be_published_as_native_overlay(tmp_path):
    with pytest.raises(ValueError, match='identity is unverified'):
        build_layer({}, {'plan_identity': {'status': 'pending'}}, tmp_path)

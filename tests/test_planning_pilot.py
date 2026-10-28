import hashlib
import json
import runpy
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest
from flask import Flask

from scripts.build_ben_cat_planning_pilot import fit_affine, load_source_image
from scripts.build_ben_cat_official_gis import footprint_mask, cropped_extent
from scripts.run_planning_pilot import install_pilot, read_manifest


def test_image_source_preserves_reference_pixels_and_checks_hash(tmp_path):
    from PIL import Image
    path = tmp_path / 'original.png'
    Image.new('RGB', (80, 60), (11, 22, 33)).save(path)
    config = {'source_type': 'image', 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    loaded = load_source_image(path, config)
    assert loaded.size == (80, 60)
    assert loaded.getpixel((20, 30)) == (11, 22, 33, 255)
    config['source_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='hash mismatch'):
        load_source_image(path, config)


def test_official_outline_must_be_closed_and_within_export():
    alpha = np.zeros((80, 100), dtype='uint8')
    alpha[10, 10:91] = alpha[70, 10:91] = 255
    alpha[10:71, 10] = alpha[10:71, 90] = 255
    filled = footprint_mask(alpha)
    assert filled[40, 50] and not filled[1, 1]
    alpha[10, 40:55] = 0
    with pytest.raises(ValueError, match='not closed|one connected'):
        footprint_mask(alpha)
    alpha[0, 50] = 255
    with pytest.raises(ValueError, match='clipped'):
        footprint_mask(alpha)


def test_official_crop_preserves_native_world_pixel_grid():
    extent = {'xmin': 1000, 'ymin': 2000, 'xmax': 1400, 'ymax': 2600,
              'spatialReference': {'wkid': 3857}}
    actual = cropped_extent(extent, (200, 300), (10, 20, 110, 220))
    assert actual == {'xmin': 1020, 'xmax': 1220, 'ymin': 2160, 'ymax': 2560,
                      'spatialReference': {'wkid': 3857}}
    extent['spatialReference'] = {'wkid': 4326}
    with pytest.raises(ValueError, match='Web Mercator'):
        cropped_extent(extent, (200, 300), (10, 20, 110, 220))


def test_official_build_clips_native_raster_and_does_not_invent_fit_accuracy(tmp_path, monkeypatch):
    from PIL import Image, ImageDraw
    import scripts.build_ben_cat_official_gis as builder
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    folder = tmp_path / '.local/planning-ben-cat/fixture'
    folder.mkdir(parents=True)
    Image.new('RGBA', (100, 100), (20, 40, 60, 255)).save(folder / 'raster.png')
    outline = Image.new('RGBA', (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(outline).rectangle((20, 20, 80, 80), outline=(0, 200, 120, 255))
    outline.save(folder / 'outline.png')
    extent = {'xmin': 11860000, 'ymin': 1240000, 'xmax': 11861000, 'ymax': 1241000,
              'spatialReference': {'wkid': 3857}}
    (folder / 'export.json').write_text(json.dumps({'width': 100, 'height': 100, 'extent': extent}))
    (folder / 'request.txt').write_text('https://example.invalid/export?bbox=11860000,1240000,11861000,1241000&bboxSR=3857&size=100,100')
    config = {'id': 'fixture', 'slug': 'fixture', 'title': 'Fixture', 'decision': 'Test',
              'source_url': 'https://example.invalid', 'publication_url': 'https://example.invalid',
              'source_filename': 'raster.png', 'outline_filename': 'outline.png',
              'export_metadata_filename': 'export.json', 'outline_url_filename': 'request.txt',
              'source_sha256': hashlib.sha256((folder / 'raster.png').read_bytes()).hexdigest(),
              'outline_sha256': hashlib.sha256((folder / 'outline.png').read_bytes()).hexdigest(),
              'map_scale': 2000, 'reference_area_ha': 37.21, 'captured_on': '2026-10-27',
              'notice': 'Test fixture', 'attribution': 'Synthetic fixture'}
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps(config))
    builder.build(config_path)
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf8'))
    assert manifest['alignment_method'] == 'official_coordinates'
    assert manifest['legend_available'] is False
    assert 'check_max_m' not in manifest
    assert Image.open(folder / 'overlay.webp').size == (61, 61)
    audit = json.loads((folder / 'alignment-audit.json').read_text(encoding='utf8'))
    assert audit['native_extent']['xmin'] == 11860200
    assert audit['native_extent']['ymax'] == 1240800


def test_overlay_runtime_failure_and_lifecycle():
    result = subprocess.run(['node', 'tests/planning_overlay_runtime.cjs'],
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr


def test_affine_requires_distributed_points_and_measures_checks():
    pixels = np.array([[0, 0], [100, 0], [0, 100], [100, 100], [50, 0], [0, 50]])
    target = pixels * [2, -2] + [1000, 2000]
    matrix, errors = fit_affine(pixels, target)
    assert np.max(errors) < 1e-8
    assert np.allclose(np.array([30, 40, 1]) @ matrix, [1060, 1920])
    with pytest.raises(ValueError):
        fit_affine(pixels[:3], target[:3])
    with pytest.raises(ValueError):
        fit_affine(np.zeros((6, 2)), target)


def pilot_client(tmp_path):
    for name in ('overlay.webp', 'legend.webp'):
        (tmp_path / name).write_bytes(b'local-fixture')
    manifest = {
        'id': 'thoi-hoa-2909-qh01', 'status': 'local_experiment',
        'bounds': [[11.07, 106.58], [11.14, 106.67]],
        'artifacts': {name: hashlib.sha256(b'local-fixture').hexdigest()
                      for name in ('overlay.webp', 'legend.webp')},
    }
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    app = Flask(__name__)
    install_pilot(app, tmp_path)
    return app.test_client()


def test_local_files_are_allowlisted_private_and_loopback_only(tmp_path):
    client = pilot_client(tmp_path)
    response = client.get('/local-planning/manifest.json')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert response.headers.get('X-Radar-Public-Cache') is None
    assert client.get('/local-planning/overlay.webp').status_code == 200
    assert client.get('/local-planning/thoi-hoa-original.pdf').status_code == 404
    assert client.get('/local-planning/../.env').status_code == 404
    assert client.get('/local-planning/manifest.json',
                      environ_overrides={'REMOTE_ADDR': '203.0.113.4'}).status_code == 404
    assert client.get('/local-planning/manifest.json',
                      headers={'Host': 'radarbds.vn'}).status_code == 404
    assert client.get('/local-planning/manifest.json',
                      headers={'X-Forwarded-For': '203.0.113.4'}).status_code == 404


def test_invalid_or_missing_artifacts_fail_closed(tmp_path):
    client = pilot_client(tmp_path)
    (tmp_path / 'overlay.webp').write_bytes(b'changed')
    assert client.get('/local-planning/manifest.json').status_code == 503
    assert client.get('/local-planning/overlay.webp').status_code == 503
    (tmp_path / 'manifest.json').write_text('{broken', encoding='utf-8')
    assert client.get('/local-planning/manifest.json').status_code == 503


def test_catalog_isolates_each_layer_and_scopes_assets(tmp_path):
    client = pilot_client(tmp_path)
    catalog = client.get('/local-planning/catalog.json')
    assert catalog.status_code == 200
    assert catalog.headers['Cache-Control'] == 'private, no-store'
    layers = {row['id']: row for row in catalog.json['layers']}
    assert len(layers) == 35
    assert sum(row.get('theme')=='land_use_2030' for row in layers.values()) == 4
    assert layers['thoi-hoa-2909-qh01']['status'] == 'overlay_ready'
    assert layers['thoi-hoa-2909-qh01']['city'] == 'Bến Cát'
    assert layers['tan-dinh-2910-qh01']['status'] == 'artifact_unavailable'
    assert layers['hoa-loi-2911-qh01']['status'] == 'artifact_unavailable'
    assert layers['my-phuoc-2913']['status'] == 'source_missing_map'
    assert layers['thoi-hoa-2909-qh01']['source'] == 'document'
    assert layers['my-phuoc-gis-qhpk']['source'] == 'gis'
    assert layers['my-phuoc-gis-qhpk']['status'] == 'artifact_unavailable'
    assert layers['ben-cat-general-gis']['theme'] == 'urban_general'
    assert not any(row.get('theme') == 'district_landuse' for row in layers.values())
    assert layers['ben-cat-general-gis']['status'] == 'artifact_unavailable'
    tdm = [row for row in layers.values() if row['city'] == 'Thủ Dầu Một']
    assert len(tdm) == 14
    assert layers['tdm-general-gis']['theme'] == 'urban_general'
    assert layers['tdm-north-east-gis-qhpk']['status'] == 'artifact_unavailable'
    assert layers['tdm-north-east-gis-qhpk']['theme'] == 'partition'
    assert 'Hòa Phú' in layers['tdm-north-east-gis-qhpk']['name']
    assert 'Phú Tân' in layers['tdm-north-east-gis-qhpk']['name']
    assert client.get('/local-planning/thoi-hoa-2909-qh01/overlay.webp').status_code == 200
    assert client.get('/local-planning/tan-dinh-2910-qh01/overlay.webp').status_code == 503
    assert client.get('/local-planning/unknown/overlay.webp').status_code == 404
    assert client.get('/local-planning/thoi-hoa-2909-qh01/original.pdf').status_code == 404
    assert client.get('/local-planning/an-dien-1450/overlay.webp').status_code == 404


def test_catalog_exposes_theme_sources_and_serves_only_fixed_artifact_folder(tmp_path, monkeypatch):
    import scripts.run_planning_pilot as runner
    folder = tmp_path / 'gis-partitions' / 'thoi-hoa'
    folder.mkdir(parents=True)
    (folder / 'overlay.webp').write_bytes(b'gis-raster')
    data = {'id': 'thoi-hoa-gis', 'status': 'local_experiment', 'legend_available': False,
            'bounds': [[11.07, 106.58], [11.14, 106.67]],
            'artifacts': {'overlay.webp': hashlib.sha256(b'gis-raster').hexdigest()}}
    (folder / 'manifest.json').write_text(json.dumps(data), encoding='utf8')
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'layers': [{
        'id': data['id'], 'name': 'Thới Hòa', 'slug': 'thoi-hoa', 'city': 'Bến Cát',
        'theme': 'partition', 'source': 'gis', 'area_id': 'thoi-hoa', 'scope': 'area',
        'status': 'overlay_ready', 'decision': '2909', 'artifact_dir': 'gis-partitions/thoi-hoa',
        'source_url': 'https://gisxaydung.tphcm.gov.vn/tracuuttqh'
    }]}), encoding='utf8')
    monkeypatch.setattr(runner, 'CATALOG_PATH', path)
    app = Flask(__name__)
    install_pilot(app, tmp_path)
    client = app.test_client()
    row = client.get('/local-planning/catalog.json').json['layers'][0]
    assert (row['theme'], row['source'], row['area_id']) == ('partition', 'gis', 'thoi-hoa')
    assert row['status'] == 'overlay_ready'
    assert client.get('/local-planning/thoi-hoa-gis/overlay.webp').data == b'gis-raster'
    assert client.get('/local-planning/thoi-hoa-gis/../manifest.json').status_code == 404
    changed = json.loads(path.read_text(encoding='utf8'))
    changed['layers'][0]['artifact_dir'] = '../outside-pilot'
    path.write_text(json.dumps(changed), encoding='utf8')
    escaped_app = Flask(__name__)
    install_pilot(escaped_app, tmp_path)
    escaped = escaped_app.test_client()
    assert escaped.get('/local-planning/catalog.json').json['layers'][0]['status'] == 'artifact_unavailable'
    assert escaped.get('/local-planning/thoi-hoa-gis/overlay.webp').status_code == 503


def test_source_sheet_preview_is_allowlisted_and_integrity_checked(tmp_path, monkeypatch):
    import scripts.run_planning_pilot as runner
    catalog_path = tmp_path / 'catalog.json'
    catalog_path.write_text(json.dumps({'layers': [{
        'id': 'hoa-loi-2911-qh01', 'name': 'Hòa Lợi', 'slug': 'hoa-loi',
        'status': 'document_only', 'decision': '2911', 'source_url': 'https://drive.google.com/file/d/example/view',
    }]}), encoding='utf8')
    monkeypatch.setattr(runner, 'CATALOG_PATH', catalog_path)
    client = pilot_client(tmp_path)
    folder = tmp_path / 'hoa-loi'
    folder.mkdir()
    preview = folder / 'preview.webp'
    preview.write_bytes(b'original-sheet-preview')
    index = {'hoa-loi-2911-qh01': hashlib.sha256(preview.read_bytes()).hexdigest()}
    (tmp_path / 'documents.json').write_text(json.dumps(index), encoding='utf8')
    url = '/local-planning/hoa-loi-2911-qh01/preview.webp'
    assert client.get(url).status_code == 200
    assert client.get('/local-planning/hoa-loi-2911-qh01/overlay.webp').status_code == 404
    preview.write_bytes(b'changed')
    assert client.get(url).status_code == 503


def test_official_native_layer_uses_verified_overlay_without_fake_legend(tmp_path, monkeypatch):
    import scripts.run_planning_pilot as runner
    folder = tmp_path / 'my-phuoc'
    folder.mkdir()
    (folder / 'overlay.webp').write_bytes(b'official-raster')
    manifest = {'id': 'my-phuoc-2913', 'status': 'local_experiment',
                'bounds': [[11.12, 106.57], [11.18, 106.64]], 'legend_available': False,
                'artifacts': {'overlay.webp': hashlib.sha256(b'official-raster').hexdigest()}}
    (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
    assert read_manifest(folder, manifest['id'])['legend_available'] is False
    catalog_path = tmp_path / 'native-catalog.json'
    catalog_path.write_text(json.dumps({'layers': [{
        'id': manifest['id'], 'name': 'Mỹ Phước', 'slug': 'my-phuoc', 'status': 'overlay_ready',
        'decision': '2913', 'source_url': 'https://gisxaydung.tphcm.gov.vn/tracuuttqh'
    }]}), encoding='utf8')
    monkeypatch.setattr(runner, 'CATALOG_PATH', catalog_path)
    app = Flask(__name__)
    install_pilot(app, tmp_path)
    client = app.test_client()
    assert client.get('/local-planning/my-phuoc-2913/overlay.webp').status_code == 200
    assert client.get('/local-planning/my-phuoc-2913/legend.webp').status_code == 404


def test_standard_app_has_no_pilot_asset_registration():
    source = Path('app.py').read_text(encoding='utf-8')
    assert 'install_pilot(' not in source


def test_pilot_privacy_headers_run_after_existing_asset_cache_hook(tmp_path):
    app = Flask(__name__)

    @app.after_request
    def immutable_asset(response):
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        response.headers['X-Radar-Public-Cache'] = '1'
        return response

    install_pilot(app, tmp_path)
    response = app.test_client().get('/local-planning/catalog.json')
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert response.headers.get('X-Radar-Public-Cache') is None


def test_runner_starts_even_when_pilot_artifacts_are_missing(monkeypatch):
    app = Flask(__name__)
    starts = []
    monkeypatch.setitem(sys.modules, 'app', SimpleNamespace(app=app))
    monkeypatch.setattr(app, 'run', lambda **kwargs: starts.append(kwargs))
    original = Path.read_text

    def missing_manifest(path, *args, **kwargs):
        if path.name == 'manifest.json':
            raise FileNotFoundError(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', missing_manifest)
    runpy.run_path('scripts/run_planning_pilot.py', run_name='__main__')
    assert starts == [dict(host='127.0.0.1', port=5055, debug=False, use_reloader=False)]
    assert app.test_client().get('/local-planning/manifest.json').status_code == 503

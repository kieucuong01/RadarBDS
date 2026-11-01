from PIL import Image
import hashlib
import json
import pytest


def test_downsample_preserves_xyz_quadrants_and_transparency():
    from scripts.build_planning_overview import compose_parent

    children = {(0, 0): Image.new('RGBA', (256, 256), 'red'),
                (1, 0): Image.new('RGBA', (256, 256), 'green'),
                (0, 1): Image.new('RGBA', (512, 512), 'blue')}
    image = compose_parent(children)
    assert image.size == (256, 256)
    assert image.getpixel((64, 64)) == (255, 0, 0, 255)
    assert image.getpixel((192, 64)) == (0, 128, 0, 255)
    assert image.getpixel((64, 192)) == (0, 0, 255, 255)
    assert image.getpixel((192, 192)) == (0, 0, 0, 0)


def test_prepared_binh_phuoc_overview_is_content_addressed_and_does_not_change_native_source():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    prepared = json.loads((root / 'config/planning_overviews.json').read_text())['overviews'][0]
    layers = json.loads((root / 'config/planning_partition_reference.json').read_text(encoding='utf8'))['layers']
    layer = next(l for l in layers if l['id'] == prepared['layer_id'])['manifest']
    assert prepared['release'] == hashlib.sha256(json.dumps(prepared['files'], sort_keys=True).encode()).hexdigest()[:16]
    assert layer['min_native_zoom'] == prepared['source_zoom'] == 15
    assert layer['tile_template'] == prepared['source_template']
    assert layer['overview']['min_zoom'] == 0 and layer['overview']['max_zoom'] == 14
    assert layer['overview']['tile_template'].startswith('/static/maps/planning/overlays/' + prepared['release'] + '/')
    assert prepared['source_tile_count'] == 8742 and not prepared['source_gaps']
    assert len(prepared['files']) == 3069
    assert {int(f.split('/')[0]) for f in prepared['files']} == set(range(15))


def test_builder_never_activates_a_pyramid_when_every_source_tile_is_missing(tmp_path, monkeypatch):
    from scripts import build_planning_overview as builder
    (tmp_path / 'config').mkdir()
    layer = dict(id='test', theme='partition', source='guland', manifest=dict(
        render_mode='xyz', min_native_zoom=1, bounds=[[11, 106], [12, 107]],
        tile_template='https://public.example/{z}/{x}/{y}.png'))
    (tmp_path / 'config/planning_partition_reference.json').write_text(json.dumps({'layers': [layer]}))

    class Response:
        status_code = 403
        def __enter__(self): return self
        def __exit__(self, *args): return False

    class Session:
        def mount(self, *args): pass
        def get(self, url, **kwargs):
            assert kwargs['allow_redirects'] is False
            return Response()

    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    monkeypatch.setattr(builder.requests, 'Session', Session)
    with pytest.raises(ValueError, match='No source imagery'):
        builder.build('test', tmp_path / 'output')
    assert not (tmp_path / 'output/test/manifest.json').exists()

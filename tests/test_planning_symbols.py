import base64
from io import BytesIO
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def test_bundled_symbols_keep_real_source_images_and_reference_colours():
    path = ROOT / 'static/data/planning_symbols.json'
    assert path.stat().st_size < 130_000
    data = json.loads(path.read_text(encoding='utf8'))
    assert len(data['groups']) == 7
    assert sum(len(g['rows']) for g in data['groups'] if g['theme'] != 'land_codes') == 333
    assert sum(len(g['rows']) for g in data['groups'] if g['theme'] == 'land_codes') == 67
    for group in data['groups']:
        assert len(group['legend_sha256']) == 64
        assert len({r['code'] for r in group['rows']}) == len(group['rows'])
        for row in group['rows']:
            assert row['code'] and row['label']
            image = base64.b64decode(row['image'].split(',', 1)[1], validate=True)
            with Image.open(BytesIO(image)) as im:
                assert im.format == 'PNG' and im.size == (20, 20)
                im.verify()
    codes = {r['code']: r for r in data['groups'][0]['rows']}
    for code, rgb in {'ONT': (255, 208, 255), 'ODT': (255, 160, 255), 'CLN': (255, 210, 160)}.items():
        with Image.open(BytesIO(base64.b64decode(codes[code]['image'].split(',')[1]))) as im:
            assert im.getpixel((10, 10)) == rgb


def test_measure_and_legend_scripts_load_before_overlay():
    template = (ROOT / 'templates/index.html').read_text(encoding='utf8')
    for helper in ['planning_measure.js', 'planning_legend.js']:
        assert template.index(helper) < template.index("filename='js/main/planning_overlay.js'")
    assert 'planning-tools-20261029' in template

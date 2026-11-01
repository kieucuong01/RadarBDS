"""Build a bounded offline overview pyramid; never fan out source tiles in a web request."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import math
from pathlib import Path
import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def compose_parent(children):
    parent = Image.new('RGBA', (256, 256))
    for (x, y), image in children.items():
        parent.paste(image.convert('RGBA').resize((128, 128), Image.Resampling.LANCZOS), (x * 128, y * 128))
    return parent


def tile_range(bounds, zoom):
    def xy(lat, lon):
        n = 2 ** zoom
        return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    (south, west), (north, east) = bounds
    left, top = xy(north, west)
    right, bottom = xy(south, east)
    return left, top, right, bottom


def build(layer_id, output):
    layers = json.loads((ROOT / 'config/planning_partition_reference.json').read_text(encoding='utf8'))['layers']
    layer = next(l for l in layers if l['id'] == layer_id)
    data = layer['manifest']
    if layer['theme'] != 'partition' or layer['source'] != 'guland' or data['render_mode'] != 'xyz':
        raise ValueError('Only a registered partition raster can be prepared')
    zoom = data['min_native_zoom']
    left, top, right, bottom = tile_range(data['bounds'], zoom)
    total = (right - left + 1) * (bottom - top + 1)
    if not 1 <= zoom <= 18 or total > 12000:
        raise ValueError('Source capture exceeds the offline budget')
    output = Path(output).resolve()
    work = output / layer_id
    source = work / 'source'
    stage = work / 'pyramid'
    files, missing = {}, []
    sessions = threading.local()

    def fetch(x, y):
        path = source / str(zoom) / str(x) / (str(y) + '.png')
        absent = path.with_suffix('.missing')
        if absent.exists():
            return None, str(absent.relative_to(source))
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.download')
            url = data['tile_template'].format(z=zoom, x=x, y=y)
            if not hasattr(sessions, 'client'):
                sessions.client = requests.Session()
                sessions.client.trust_env = False
                sessions.client.mount('https://', HTTPAdapter(max_retries=Retry(
                    total=2, backoff_factor=.4, status_forcelist=(429, 500, 502, 503, 504))))
            with sessions.client.get(url, timeout=(5, 20), stream=True, allow_redirects=False) as response:
                if response.status_code in (403, 404):
                    # Preserve a source gap; a missing tile is not a land-use conclusion.
                    absent.write_text(str(response.status_code))
                    return None, str(absent.relative_to(source))
                if response.status_code != 200:
                    raise ValueError('Unexpected source HTTP status: ' + str(response.status_code))
                parts, size = [], 0
                for part in response.iter_content(65536):
                    size += len(part)
                    if size > 2_000_000:
                        raise ValueError('Oversized source tile')
                    parts.append(part)
                temporary.write_bytes(b''.join(parts))
            with Image.open(temporary) as image:
                if image.size not in ((256, 256), (512, 512)) or image.format != 'PNG':
                    raise ValueError('Invalid source image')
                image.verify()
            temporary.replace(path)
        with Image.open(path) as image:
            return image.convert('RGBA'), None

    def save(image, z, x, y):
        relative = f'{z}/{x}/{y}.png'
        payload = io.BytesIO()
        image.save(payload, format='PNG', optimize=True)
        raw = payload.getvalue()
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return relative, hashlib.sha256(raw).hexdigest()

    def parent(job):
        x, y = job
        children, gaps = {}, []
        for dx in (0, 1):
            for dy in (0, 1):
                sx, sy = x * 2 + dx, y * 2 + dy
                if not (left <= sx <= right and top <= sy <= bottom):
                    continue
                image, gap = fetch(sx, sy)
                if image is not None:
                    children[(dx, dy)] = image
                if gap:
                    gaps.append(gap)
        return save(compose_parent(children), zoom - 1, x, y), gaps

    jobs = [(x, y) for x in range(left // 2, right // 2 + 1) for y in range(top // 2, bottom // 2 + 1)]
    print(f'Preparing {total} source tiles; four workers; {len(jobs)} first-level overview tiles', flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for count, (entry, gaps) in enumerate(pool.map(parent, jobs), 1):
            files[entry[0]] = entry[1]
            missing.extend(gaps)
            if count % 50 == 0:
                print(f'Prepared {count}/{len(jobs)} overview tiles; source gaps {len(missing)}', flush=True)
    if len(missing) == total:
        raise ValueError('No source imagery available; overview must not be activated')
    for z in range(zoom - 2, -1, -1):
        parents = {(int(name.split('/')[1]) // 2, int(name.split('/')[2].split('.')[0]) // 2)
                   for name in files if name.startswith(str(z + 1) + '/')}
        for x, y in sorted(parents):
            children = {}
            for dx in (0, 1):
                for dy in (0, 1):
                    path = stage / f'{z+1}/{x*2+dx}/{y*2+dy}.png'
                    if path.exists():
                        with Image.open(path) as image:
                            children[(dx, dy)] = image.convert('RGBA')
            entry = save(compose_parent(children), z, x, y)
            files[entry[0]] = entry[1]
    release = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:16]
    manifest = dict(layer_id=layer_id, source_template=data['tile_template'], source_zoom=zoom,
                    bounds=data['bounds'], min_zoom=0, max_zoom=zoom - 1, release=release,
                    source_tile_count=total, source_gaps=missing, files=files)
    (work / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    print(f'Built {len(files)} tiles; release {release}; source gaps {len(missing)}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layer', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/planning-overviews')
    args = parser.parse_args()
    build(args.layer, args.output)

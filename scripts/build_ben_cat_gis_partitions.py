"""Capture public native-coordinate QHPK exports; never create replacement boundaries.

Downloaded images stay in ignored .local/. No authentication or returned image href
is used. A PDF-derived bounding box is only an export window, never a clipping mask.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import numpy as np
import requests

try:
    from scripts.build_ben_cat_official_gis import cropped_extent, footprint_mask
except ModuleNotFoundError:
    from build_ben_cat_official_gis import cropped_extent, footprint_mask

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'config/ben_cat_gis_partitions.json'
DEFAULT_OUTPUT = ROOT / '.local/planning-ben-cat/gis-partitions'
API_PREFIX = 'https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def export_window(layer):
    from pyproj import Transformer
    south_west, north_east = layer['window_hint_bounds']
    transform = Transformer.from_crs(4326, 3857, always_xy=True)
    xmin, ymin = transform.transform(south_west[1], south_west[0])
    xmax, ymax = transform.transform(north_east[1], north_east[0])
    pad = layer.get('window_padding_fraction', .2)
    dx, dy = (xmax - xmin) * pad, (ymax - ymin) * pad
    return [xmin - dx, ymin - dy, xmax + dx, ymax + dy]


def export_url(service, extent, size, *, outline_filter=None, metadata=False):
    if not service.startswith(API_PREFIX) or not service.endswith('/MapServer/export'):
        raise ValueError('Only the configured public GIS export service is allowed')
    params = dict(bbox=','.join(map(str, extent)), bboxSR=3857, imageSR=3857,
                  size=','.join(map(str, size)), format='png32', transparent='true',
                  f='json' if metadata else 'image')
    if outline_filter:
        params.update(layers='show:0', layerDefs=json.dumps({'0': outline_filter}))
    return service + '?' + urlencode(params)


def download(url, path):
    """Public read using the transport verified against this GIS host."""
    response = requests.get(url, headers={
        'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gisxaydung.tphcm.gov.vn/',
        'Origin': 'https://gisxaydung.tphcm.gov.vn', 'Accept': 'application/json',
    }, timeout=(10, 45))
    if response.status_code in (401, 403):
        raise RuntimeError('Public export denied: HTTP ' + str(response.status_code))
    response.raise_for_status()
    payload = response.content
    if not payload:
        raise RuntimeError('Public export returned an empty body')
    if Path(path).suffix == '.png' and not payload.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError('Public export did not return PNG image data')
    if Path(path).suffix == '.json':
        try:
            metadata = json.loads(payload)
        except ValueError as exc:
            raise RuntimeError('Public export returned invalid JSON') from exc
        if not isinstance(metadata, dict) or 'error' in metadata:
            raise RuntimeError('Public export returned invalid metadata or a service error')
    temp = Path(str(path) + '.download')
    temp.write_bytes(payload)
    temp.replace(path)


def capture_layer(config, layer, directory):
    """Capture metadata, then both images on the server-confirmed native pixel grid."""
    directory.mkdir(parents=True, exist_ok=True)
    size = layer['size']
    window = export_window(layer)
    source_meta_url = export_url(config['land_use_service'], window, size, metadata=True)
    download(source_meta_url, directory / 'export.json')
    export = json.loads((directory / 'export.json').read_text(encoding='utf8'))
    extent = export['extent']
    bbox = [extent[k] for k in ('xmin', 'ymin', 'xmax', 'ymax')]
    size = [export['width'], export['height']]
    # A single exact plan ID is preferred. Otherwise the official decision prefix
    # is spatially restricted by this window and must yield one closed outline.
    outline_filter = layer.get('outline_filter', "SoQD_DC LIKE '" + layer['decision_prefix'] + "%'")
    urls = {'metadata': source_meta_url,
            'source': export_url(config['land_use_service'], bbox, size),
            'outline': export_url(config['outline_service'], bbox, size, outline_filter=outline_filter)}
    for kind in ('source', 'outline'):
        download(urls[kind], directory / (kind + '.png'))
    write_json(directory / 'requests.json', urls)
    write_json(directory / 'capture.json', {'captured_on': config['captured_on'],
               'hashes': {name: digest(directory / name) for name in ('export.json', 'source.png', 'outline.png', 'requests.json')}})


def validate_grid(url, export, image_size):
    query = parse_qs(urlsplit(url).query)
    extent = export['extent']
    if image_size != (export['width'], export['height']):
        raise ValueError('Native export dimensions differ')
    expected = [extent[k] for k in ('xmin', 'ymin', 'xmax', 'ymax')]
    if (query.get('bboxSR') != ['3857'] or query.get('imageSR') != ['3857']
            or query.get('size') != [f'{image_size[0]},{image_size[1]}']
            or not np.allclose(list(map(float, query.get('bbox', [''])[0].split(','))), expected, rtol=0, atol=1e-6)):
        raise ValueError('Image request differs from native export grid')


def build_layer(config, layer, directory):
    from PIL import Image
    from pyproj import Transformer
    if layer.get('plan_identity', {}).get('status') != 'verified':
        raise ValueError('Official plan identity is unverified; confirm ward, decision and decision year/date before building')
    capture = json.loads((directory / 'capture.json').read_text(encoding='utf8'))
    for name, expected in capture['hashes'].items():
        if digest(directory / name) != expected:
            raise ValueError('Capture hash mismatch: ' + name)
    export = json.loads((directory / 'export.json').read_text(encoding='utf8'))
    urls = json.loads((directory / 'requests.json').read_text(encoding='utf8'))
    original = Image.open(directory / 'source.png').convert('RGBA')
    outline = Image.open(directory / 'outline.png').convert('RGBA')
    if original.size != outline.size:
        raise ValueError('Official image/outline pixel grids differ')
    for kind in ('source', 'outline'):
        validate_grid(urls[kind], export, original.size)
    outline_query = parse_qs(urlsplit(urls['outline']).query)
    expected_filter = layer.get('outline_filter', "SoQD_DC LIKE '" + layer['decision_prefix'] + "%'")
    if outline_query.get('layers') != ['show:0'] or json.loads(outline_query.get('layerDefs', ['{}'])[0]) != {'0': expected_filter}:
        raise ValueError('Official outline is not restricted to the configured plan')
    mask = footprint_mask(np.asarray(outline)[:, :, 3])
    rgba = np.asarray(original).copy()
    if np.count_nonzero(rgba[:, :, 3][mask]) < mask.sum() * .5:
        raise ValueError('Official land-use raster is missing within the plan outline')
    rgba[:, :, 3] = np.where(mask, rgba[:, :, 3], 0)
    ys, xs = np.where(mask)
    crop = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    native = cropped_extent(export['extent'], original.size, crop)
    unproject = Transformer.from_crs(3857, 4326, always_xy=True)
    west, south = unproject.transform(native['xmin'], native['ymin'])
    east, north = unproject.transform(native['xmax'], native['ymax'])
    rx = (export['extent']['xmax'] - export['extent']['xmin']) / original.width
    ry = (export['extent']['ymax'] - export['extent']['ymin']) / original.height
    area = float(mask.sum() * rx * ry * math.cos(math.radians((north + south) / 2)) ** 2 / 10000)
    # Reject gross collisions/clipped slivers; these are display plausibility
    # checks, and never certified cadastral measurements.
    if not 100 < area < 10000:
        raise ValueError('Plan footprint area is implausible for this local ward pilot')
    Image.fromarray(rgba).crop(crop).save(directory / 'overlay.webp', quality=95)
    Image.fromarray((mask * 255).astype('uint8')).save(directory / 'official-footprint-mask.png')
    manifest = {key: layer[key] for key in ('id', 'title', 'decision', 'map_scale')}
    manifest.update(status='local_experiment', source_kind='official_gis', theme='partition_plan',
                    alignment_method='official_coordinates', bounds=[[south, west], [north, east]],
                    source_url=config['source_url'], publication_url=layer.get('publication_url', config['publication_url']),
                    source_sha256=digest(directory / 'source.png'), legend_available=False,
                    captured_on=capture['captured_on'],
                    notice='Ảnh GIS công khai, giữ tọa độ gốc và cắt theo đường bao đồ án của nguồn. Chưa xác minh độ chính xác địa chính, hiệu lực hiện tại hoặc quy hoạch từng thửa.',
                    attribution='Sở Quy hoạch – Kiến trúc TP.HCM · GIS công khai · ' + layer['name'],
                    artifacts={'overlay.webp': digest(directory / 'overlay.webp')})
    audit = dict(config=layer, native_extent=native, export_extent=export['extent'], crop_pixels=crop,
                 footprint_area_ha=round(area, 2), source_requests=urls, capture_hashes=capture['hashes'],
                 footprint_method='single connected closed official GIS outline; one-pixel antialias gap closure',
                 window_hint_is_boundary=False, survey_accuracy_verified=False, currency_verified=False,
                 public_reuse_verified=False)
    write_json(directory / 'alignment-audit.json', audit)
    write_json(directory / 'manifest.json', manifest)
    return manifest


def reuse_my_phuoc(config, layer, directory):
    """Migrate the already hash-pinned official capture, retaining its actual date."""
    import shutil
    old = ROOT / '.local/planning-ben-cat/my-phuoc'
    old_config = json.loads((ROOT / 'config/ben_cat_planning_my_phuoc.json').read_text(encoding='utf8'))
    for filename, key in ((old_config['source_filename'], 'source_sha256'), (old_config['outline_filename'], 'outline_sha256')):
        if digest(old / filename) != old_config[key]:
            raise ValueError('Existing Mỹ Phước capture hash mismatch')
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(old / old_config['source_filename'], directory / 'source.png')
    shutil.copy2(old / old_config['outline_filename'], directory / 'outline.png')
    shutil.copy2(old / old_config['export_metadata_filename'], directory / 'export.json')
    export = json.loads((directory / 'export.json').read_text(encoding='utf8'))
    bbox = [export['extent'][k] for k in ('xmin', 'ymin', 'xmax', 'ymax')]
    urls = dict(metadata='Previously captured official metadata; preserved export.json',
                source=export_url(config['land_use_service'], bbox, [export['width'], export['height']]),
                outline=(old / old_config['outline_url_filename']).read_text().strip())
    write_json(directory / 'requests.json', urls)
    write_json(directory / 'capture.json', {'captured_on': old_config['captured_on'],
               'hashes': {name: digest(directory / name) for name in ('export.json', 'source.png', 'outline.png', 'requests.json')}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--slug', action='append', help='Only these ward slugs')
    parser.add_argument('--capture', action='store_true', help='Fetch public source exports before building')
    parser.add_argument('--reuse-my-phuoc', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf8'))
    results = []
    for layer in config['layers']:
        if args.slug and layer['slug'] not in args.slug:
            continue
        directory = args.output / layer['slug']
        try:
            if args.reuse_my_phuoc and layer['slug'] == 'my-phuoc':
                reuse_my_phuoc(config, layer, directory)
            elif args.capture:
                capture_layer(config, layer, directory)
            manifest = build_layer(config, layer, directory)
            result = dict(slug=layer['slug'], status='overlay_ready', bounds=manifest['bounds'])
        except (OSError, ValueError, KeyError, RuntimeError, requests.RequestException) as exc:
            result = dict(slug=layer['slug'], status='source_unavailable', reason=str(exc))
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / 'build-result.json', results)
    return 0 if all(row['status'] == 'overlay_ready' for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())

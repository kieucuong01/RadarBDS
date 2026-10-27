"""Build a loopback pilot from public GIS exports and their native map extent."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def footprint_mask(alpha):
    """Fill the single closed official outline; never substitute a guessed ward box."""
    import cv2
    binary = (np.asarray(alpha) > 0).astype('uint8')
    if binary.ndim != 2 or not binary.any():
        raise ValueError('Empty official footprint')
    if binary[0].any() or binary[-1].any() or binary[:, 0].any() or binary[:, -1].any():
        raise ValueError('Footprint is clipped by export extent')
    # Close only subpixel/one-pixel antialias gaps in the rendered outline.
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), dtype='uint8'))
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if count != 2 or stats[1, cv2.CC_STAT_AREA] < 20:
        raise ValueError('Expected one connected official outline')
    exterior = binary.copy()
    cv2.floodFill(exterior, None, (0, 0), 2)
    filled = exterior != 2
    if filled.sum() < binary.sum() * 3:
        raise ValueError('Official outline is not closed')
    return filled


def cropped_extent(extent, size, crop):
    if extent.get('spatialReference', {}).get('latestWkid', extent.get('spatialReference', {}).get('wkid')) not in (3857, 102100):
        raise ValueError('Official export must use Web Mercator')
    left, top, right, bottom = crop
    rx = (extent['xmax'] - extent['xmin']) / size[0]
    ry = (extent['ymax'] - extent['ymin']) / size[1]
    if not all(math.isfinite(v) and v > 0 for v in (rx, ry)):
        raise ValueError('Invalid native export pixel grid')
    return {'xmin': extent['xmin'] + left * rx, 'xmax': extent['xmin'] + right * rx,
            'ymin': extent['ymax'] - bottom * ry, 'ymax': extent['ymax'] - top * ry,
            'spatialReference': {'wkid': 3857}}


def build(config_path=ROOT / 'config/ben_cat_planning_my_phuoc.json'):
    from PIL import Image
    from pyproj import Transformer
    config = json.loads(Path(config_path).read_text(encoding='utf8'))
    directory = ROOT / '.local/planning-ben-cat' / config['slug']
    image_path, outline_path = directory / config['source_filename'], directory / config['outline_filename']
    for path, key in ((image_path, 'source_sha256'), (outline_path, 'outline_sha256')):
        if hashlib.sha256(path.read_bytes()).hexdigest() != config[key]:
            raise ValueError('Official source hash mismatch: ' + path.name)
    original = Image.open(image_path).convert('RGBA')
    outline = Image.open(outline_path).convert('RGBA')
    export = json.loads((directory / config['export_metadata_filename']).read_text(encoding='utf8'))
    if original.size != outline.size or original.size != (export['width'], export['height']):
        raise ValueError('Official image/outline pixel grids differ')
    extent = export['extent']
    outline_query = parse_qs(urlsplit((directory / config['outline_url_filename']).read_text().strip()).query)
    expected_bbox = [extent[k] for k in ('xmin', 'ymin', 'xmax', 'ymax')]
    if outline_query.get('bboxSR') != ['3857'] or not np.allclose(
        list(map(float, outline_query['bbox'][0].split(','))), expected_bbox, rtol=0, atol=1e-6
    ) or outline_query.get('size') != [f'{original.width},{original.height}']:
        raise ValueError('Official footprint request does not match source extent')
    mask = footprint_mask(np.asarray(outline)[:, :, 3])
    rgba = np.asarray(original).copy()
    rgba[:, :, 3] = np.where(mask, rgba[:, :, 3], 0)
    ys, xs = np.where(mask)
    crop = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    native = cropped_extent(extent, original.size, crop)
    unproject = Transformer.from_crs(3857, 4326, always_xy=True)
    west, south = unproject.transform(native['xmin'], native['ymin'])
    east, north = unproject.transform(native['xmax'], native['ymax'])
    rx = (extent['xmax'] - extent['xmin']) / original.width
    ry = (extent['ymax'] - extent['ymin']) / original.height
    area = float(mask.sum() * rx * ry * math.cos(math.radians((north + south) / 2)) ** 2 / 10000)
    if abs(area - config['reference_area_ha']) / config['reference_area_ha'] > .1:
        raise ValueError('Official footprint area differs materially from project reference')
    Image.fromarray(rgba).crop(crop).save(directory / 'overlay.webp', quality=95)
    Image.fromarray((mask * 255).astype('uint8')).save(directory / 'official-footprint-mask.png')
    manifest = {key: config[key] for key in ('id', 'title', 'decision', 'source_url', 'publication_url', 'source_sha256', 'map_scale', 'notice', 'attribution')}
    manifest.update(status='local_experiment', source_kind='official_gis', alignment_method='official_coordinates',
                    bounds=[[south, west], [north, east]], legend_available=False,
                    captured_on=config['captured_on'], artifacts={'overlay.webp': hashlib.sha256((directory / 'overlay.webp').read_bytes()).hexdigest()})
    (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    audit = {'config': config, 'native_extent': native, 'export_extent': extent, 'crop_pixels': crop,
             'footprint_area_ha': round(area, 2), 'reference_area_ha': config['reference_area_ha'],
             'footprint_method': 'fill single connected closed outline exported by official GIS; one-pixel antialias gap closure',
             'survey_accuracy_verified': False, 'currency_verified': False, 'public_reuse_verified': False}
    (directory / 'alignment-audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/ben_cat_planning_my_phuoc.json')
    build(parser.parse_args().config)

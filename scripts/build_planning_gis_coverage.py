"""Restore real QHPK pixels omitted by plan-outline clipping; never infer plan boundaries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

import cv2
import numpy as np
from PIL import Image
from pyproj import Transformer

try:
    from scripts.build_ben_cat_gis_partitions import digest, validate_grid, write_json
    from scripts.build_ben_cat_official_gis import cropped_extent
except ModuleNotFoundError:
    from build_ben_cat_gis_partitions import digest, validate_grid, write_json
    from build_ben_cat_official_gis import cropped_extent

ROOT = Path(__file__).resolve().parents[1]
SERVICE = 'https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/SuDungDat_QHPK_HCM_V2/MapServer/export'


def checked(root, item):
    path = (Path(root) / item['path']).resolve()
    if not path.is_relative_to(Path(root).resolve()) or digest(path) != item['sha256']:
        raise ValueError('Input path/hash mismatch')
    return path


def sample_mask(mask, extent, target, size):
    """Sample alpha by world coordinates; pixels outside its own extent stay empty."""
    height, width = mask.shape
    cropped_extent(extent, (width, height), (0, 0, width, height))
    cropped_extent(target, size, (0, 0, *size))
    x = target['xmin'] + (np.arange(size[0]) + .5) * (target['xmax'] - target['xmin']) / size[0]
    y = target['ymax'] - (np.arange(size[1]) + .5) * (target['ymax'] - target['ymin']) / size[1]
    ix = np.floor((x - extent['xmin']) / (extent['xmax'] - extent['xmin']) * width).astype(int)
    iy = np.floor((extent['ymax'] - y) / (extent['ymax'] - extent['ymin']) * height).astype(int)
    valid = ((ix >= 0) & (ix < width))[None, :] & ((iy >= 0) & (iy < height))[:, None]
    return mask[np.clip(iy, 0, height-1)[:, None], np.clip(ix, 0, width-1)[None, :]] & valid


def geometry_mask(geometry, extent, size):
    if geometry['type'] not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Reference display geometry must be polygonal')
    project = Transformer.from_crs(4326, 3857, always_xy=True)
    mask = np.zeros((size[1], size[0]), dtype='uint8')
    polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
    for polygon in polygons:
        part = np.zeros_like(mask)
        for index, ring in enumerate(polygon):
            xy = np.asarray([project.transform(*point[:2]) for point in ring])
            xy[:, 0] = (xy[:, 0] - extent['xmin']) / (extent['xmax'] - extent['xmin']) * size[0]
            xy[:, 1] = (extent['ymax'] - xy[:, 1]) / (extent['ymax'] - extent['ymin']) * size[1]
            cv2.fillPoly(part, [np.rint(xy).astype('int32')], 255 if index == 0 else 0)
        mask |= part
    return mask > 0


def build(config, root, output):
    output = Path(output)
    extent, n = config['extent'], config['tile_size']
    size = (n*2, n*2)
    cropped_extent(extent, size, (0, 0, *size))
    if len(config['tiles']) != 4 or {(t['row'], t['col']) for t in config['tiles']} != {(0,0),(0,1),(1,0),(1,1)}:
        raise ValueError('Four unique native tiles are required')
    mosaic = np.zeros((size[1], size[0], 4), dtype='uint8')
    for tile in config['tiles']:
        request = tile['request']
        if urlsplit(request)._replace(query='').geturl() != SERVICE:
            raise ValueError('Expected the official partition service')
        meta = json.loads(checked(root, tile['metadata']).read_text(encoding='utf8'))
        image = Image.open(checked(root, tile['image'])).convert('RGBA')
        validate_grid(request, meta, image.size)
        r, c = tile['row'], tile['col']
        dx, dy = (extent['xmax']-extent['xmin'])/2, (extent['ymax']-extent['ymin'])/2
        expected = [extent['xmin']+c*dx, extent['ymax']-(r+1)*dy,
                    extent['xmin']+(c+1)*dx, extent['ymax']-r*dy]
        actual = [meta['extent'][k] for k in ('xmin','ymin','xmax','ymax')]
        if image.size != (n,n) or not np.allclose(actual, expected, rtol=0, atol=1e-6):
            raise ValueError('Native tile grid is shifted or inconsistent')
        cropped_extent(meta['extent'], (n,n), (0,0,n,n))
        mosaic[r*n:(r+1)*n, c*n:(c+1)*n] = np.asarray(image)
    geo = json.loads(checked(root, config['geometry']).read_text(encoding='utf8'))
    features = {f['properties']['name']: f for f in geo['features']}
    regions = {ward: geometry_mask(features[ward]['geometry'], extent, size) for ward in config['wards']}
    target = np.logical_or.reduce(list(regions.values()))
    if not target.any() or target[0].any() or target[-1].any() or target[:,0].any() or target[:,-1].any():
        raise ValueError('Requested reference region is empty or clipped by capture grid')
    existing = np.zeros_like(target)
    for item in config['exclusions']:
        old = np.asarray(Image.open(checked(root, item['image'])).convert('RGBA'))[:, :, 3] > 0
        audit = json.loads(checked(root, item['audit']).read_text(encoding='utf8'))
        existing |= sample_mask(old, audit['native_extent'], extent, size)
    patch = target & ~existing & (mosaic[:, :, 3] > 0)
    if not patch.any():
        raise ValueError('No new real GIS pixels are available')
    ys, xs = np.where(patch)
    crop = (int(xs.min()), int(ys.min()), int(xs.max())+1, int(ys.max())+1)
    native = cropped_extent(extent, size, crop)
    unproject = Transformer.from_crs(3857, 4326, always_xy=True)
    west, south = unproject.transform(native['xmin'], native['ymin'])
    east, north = unproject.transform(native['xmax'], native['ymax'])
    output.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mosaic).save(output/'source-mosaic.png')
    rgba = mosaic.copy(); rgba[:, :, 3] = np.where(patch, rgba[:, :, 3], 0)
    Image.fromarray(rgba).crop(crop).save(output/'overlay.webp', lossless=True)
    coverage = [dict(ward=ward, reference_pixels=int(mask.sum()), before_pixels=int((mask&existing).sum()),
                     new_pixels=int((mask&patch).sum()), after_pixels=int((mask&(existing|patch)).sum())) for ward,mask in regions.items()]
    manifest = {k: config[k] for k in ('id','title','decision','notice','source_url','captured_on')}
    manifest.update(status='local_experiment', theme='partition', source_kind='official_gis', map_scale=None,
                    bounds=[[south,west],[north,east]], alignment_method='official_coordinates', legend_available=False,
                    source_sha256=digest(output/'source-mosaic.png'), attribution='Sở Quy hoạch – Kiến trúc TP.HCM · GIS công khai',
                    artifacts={'overlay.webp':digest(output/'overlay.webp')})
    write_json(output/'manifest.json', manifest)
    write_json(output/'alignment-audit.json', dict(config=config, coverage=coverage, crop_pixels=crop, native_extent=native,
               source_extent=extent, rgb_resampled=False, new_pixels=int(patch.sum()), existing_pixels_overpainted=0,
               official_plan_boundary_verified=False, legal_edition_verified=False,
               method='Native QHPK tile mosaic; reference ward windows; only real GIS pixels absent from existing overlays'))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'config/thu_dau_mot_gis_supplement.json')
    parser.add_argument('--output', type=Path, default=ROOT/'.local/planning-ben-cat/thu-dau-mot/supplement')
    args = parser.parse_args()
    print(json.dumps(build(json.loads(args.config.read_text(encoding='utf8')), ROOT, args.output), ensure_ascii=False))

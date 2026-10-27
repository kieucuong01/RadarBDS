"""Build public QHC images on their native grid, bounded by hash-pinned display masks.

QHPK unions or reference administrative snapshots do not assert QHC boundaries.
All downloaded inputs and generated images remain under ignored .local/.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

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
SERVICE = 'https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/SuDungDat_QHC_HCM/MapServer/export'


def build(config, directory, mask_root):
    directory, mask_root = Path(directory), Path(mask_root).resolve()
    if urlsplit(config['source_request'])._replace(query='').geturl() != SERVICE:
        raise ValueError('Expected the official general-plan service')
    for name in ('export.json', 'source.png'):
        if digest(directory / name) != config['hashes'][name]:
            raise ValueError('Capture hash mismatch: ' + name)
    export = json.loads((directory / 'export.json').read_text(encoding='utf8'))
    source = np.asarray(Image.open(directory / 'source.png').convert('RGBA')).copy()
    height, width = source.shape[:2]
    validate_grid(config['source_request'], export, (width, height))
    extent = export['extent']
    # cropped_extent also rejects a non-Web-Mercator export.
    cropped_extent(extent, (width, height), (0, 0, width, height))
    rx = (extent['xmax'] - extent['xmin']) / width
    ry = (extent['ymax'] - extent['ymin']) / height
    x = extent['xmin'] + (np.arange(width) + .5) * rx
    y = extent['ymax'] - (np.arange(height) + .5) * ry
    union = np.zeros((height, width), dtype=bool)
    for item in config['display_masks']:
        path = (mask_root / item['path']).resolve()
        if not path.is_relative_to(mask_root) or digest(path) != item['sha256']:
            raise ValueError('Display mask hash/path mismatch')
        mask = np.asarray(Image.open(path).convert('L')) > 0
        mh, mw = mask.shape
        e = item['native_extent']
        cropped_extent(e, (mw, mh), (0, 0, mw, mh))
        ix = np.floor((x - e['xmin']) / (e['xmax'] - e['xmin']) * mw).astype(int)
        iy = np.floor((e['ymax'] - y) / (e['ymax'] - e['ymin']) * mh).astype(int)
        valid_x, valid_y = (ix >= 0) & (ix < mw), (iy >= 0) & (iy < mh)
        union |= mask[np.clip(iy, 0, mh - 1)[:, None], np.clip(ix, 0, mw - 1)[None, :]] & valid_y[:, None] & valid_x[None, :]
    if not union.any() or union[0].any() or union[-1].any() or union[:, 0].any() or union[:, -1].any():
        raise ValueError('Empty or edge-clipped display mask')
    if np.count_nonzero(source[:, :, 3][union]) < union.sum() * .95:
        raise ValueError('General-plan GIS coverage is incomplete within the display mask')
    ys, xs = np.where(union)
    crop = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    native = cropped_extent(extent, (width, height), crop)
    transform = Transformer.from_crs(3857, 4326, always_xy=True)
    west, south = transform.transform(native['xmin'], native['ymin'])
    east, north = transform.transform(native['xmax'], native['ymax'])
    area = float(union.sum() * rx * ry * math.cos(math.radians((north + south) / 2)) ** 2 / 10000)
    if abs(area / config['reference_area_ha'] - 1) > .1:
        raise ValueError('Display area differs materially from the city reference')
    source[:, :, 3] = np.where(union, source[:, :, 3], 0)
    Image.fromarray(source).crop(crop).save(directory / 'overlay.webp', lossless=True)
    manifest = {key: config[key] for key in ('id', 'title', 'decision', 'map_scale', 'source_url', 'publication_url', 'captured_on', 'notice')}
    manifest.update(status='local_experiment', theme='urban_general', source_kind='official_gis',
                    alignment_method='official_coordinates', bounds=[[south, west], [north, east]],
                    source_sha256=config['hashes']['source.png'], legend_available=False,
                    attribution='Sở Quy hoạch – Kiến trúc TP.HCM · GIS quy hoạch chung đô thị',
                    artifacts={'overlay.webp': digest(directory / 'overlay.webp')})
    write_json(directory / 'manifest.json', manifest)
    write_json(directory / 'alignment-audit.json', dict(config=config, native_extent=native,
               display_area_ha=round(area, 2), source_coverage_fraction=float(np.count_nonzero(source[:, :, 3][union]) / union.sum()),
               crop_pixels=crop, display_mask_method=config.get('display_mask_method',
                   'Union of hash-pinned native GIS QHPK footprints; nearest pixel sampling on QHC grid'),
               general_plan_boundary_verified=False, currency_verified=False, survey_accuracy_verified=False,
               general_plan_decision_version_verified=False))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/ben_cat_gis_general.json')
    parser.add_argument('--output', type=Path, default=ROOT / '.local/planning-ben-cat/general-plan')
    parser.add_argument('--mask-root', type=Path, default=ROOT / '.local/planning-ben-cat')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf8'))
    print(json.dumps(build(config, args.output, args.mask_root), ensure_ascii=False))

"""Build a local-only raster experiment from the official Thoi Hoa scanned PDF."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load_source_image(path, config):
    """Read the exact hashed source, retaining its original pixel coordinate frame."""
    from PIL import Image
    if hashlib.sha256(path.read_bytes()).hexdigest() != config['source_sha256']:
        raise ValueError('Source hash mismatch')
    source_type = config.get('source_type', 'pdf')
    if source_type == 'image':
        with Image.open(path) as source:
            return source.convert('RGBA')
    if source_type != 'pdf':
        raise ValueError('Unsupported planning source type')
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(path)
    page = document[config['page'] - 1]
    try:
        return page.render(scale=2).to_pil().convert('RGBA')
    finally:
        page.close()
        document.close()


def fit_affine(pixels, target):
    pixels, target = np.asarray(pixels, dtype=float), np.asarray(target, dtype=float)
    if pixels.shape != target.shape or pixels.ndim != 2 or pixels.shape[1] != 2 or len(pixels) < 6:
        raise ValueError('At least six corresponding 2D points are required')
    if not np.isfinite(pixels).all() or not np.isfinite(target).all():
        raise ValueError('Control points must be finite')
    design = np.column_stack((pixels, np.ones(len(pixels))))
    matrix, _, rank, _ = np.linalg.lstsq(design, target, rcond=None)
    if rank != 3:
        raise ValueError('Control points must not be collinear')
    return matrix, np.linalg.norm(design @ matrix - target, axis=1)


def build(config_path=None, output_directory=None):
    import cv2
    from PIL import Image, ImageDraw
    from pyproj import Transformer

    output = Path(output_directory or ROOT / '.local/planning-ben-cat')
    config = json.loads(Path(config_path or ROOT / 'config/ben_cat_planning_pilot.json').read_text(encoding='utf-8'))
    source_path = output / config.get('source_filename', 'thoi-hoa-original.pdf')
    original = load_source_image(source_path, config)
    raster = original.copy()
    reference_size = np.array(config['reference_pixel_size'])
    factor = np.array(raster.size) / reference_size
    project = Transformer.from_crs(4326, 3857, always_xy=True)
    unproject = Transformer.from_crs(3857, 4326, always_xy=True)

    def targets(points):
        return np.array([project.transform(p['lng'], p['lat']) for p in points])

    pixels = np.array([p['pixel'] for p in config['controls']])
    affine, errors = fit_affine(pixels, targets(config['controls']))
    check_pixels = np.array([p['pixel'] + [1] for p in config['checks']])
    check_errors = np.linalg.norm(check_pixels @ affine - targets(config['checks']), axis=1)
    # Web Mercator distances are not ground metres; remove the local scale factor.
    ground_factor = np.cos(np.deg2rad(np.mean([p['lat'] for p in config['controls']])))
    errors *= ground_factor
    check_errors *= ground_factor
    if max(errors.max(), check_errors.max()) > 150:
        raise ValueError('Pilot gross-alignment check failed (>150 m); inspect points')

    mask_points = np.array(config['mask'], dtype=float)
    mask = Image.new('L', raster.size, 0)
    ImageDraw.Draw(mask).polygon([tuple(p) for p in mask_points * factor], fill=255)
    raster.putalpha(mask)
    projected = np.column_stack((mask_points, np.ones(len(mask_points)))) @ affine
    left, bottom = projected.min(axis=0)
    right, top = projected.max(axis=0)
    width = 4096
    resolution = (right - left) / width
    height = int(np.ceil((top - bottom) / resolution))
    # Keep bounds exactly consistent with the integer pixel grid.
    bottom = top - height * resolution
    source_to_world = np.vstack((affine.T, [0, 0, 1])) @ np.diag([1/factor[0], 1/factor[1], 1])
    world_to_output = np.array([[1/resolution, 0, -left/resolution],
                                [0, -1/resolution, top/resolution], [0, 0, 1]])
    warped = cv2.warpAffine(np.asarray(raster), (world_to_output @ source_to_world)[:2],
                            (width, height), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    Image.fromarray(warped).save(output / 'overlay.webp', quality=90)
    crop = [round(v * factor[i % 2]) for i, v in enumerate(config['legend_crop'])]
    original.crop(crop).save(output / 'legend.webp', quality=95)
    west, south = unproject.transform(left, bottom)
    east, north = unproject.transform(right, top)
    manifest = {key: config[key] for key in ('id', 'title', 'sheet', 'decision', 'source_url',
                                            'publication_url', 'source_sha256', 'page', 'map_scale')}
    manifest.update(status='local_experiment', bounds=[[south, west], [north, east]],
                    source_kind=config.get('source_kind', 'official_published_pdf'),
                    fit_rmse_m=round(float(np.sqrt(np.mean(errors**2))), 1),
                    check_rmse_m=round(float(np.sqrt(np.mean(check_errors**2))), 1),
                    check_max_m=round(float(check_errors.max()), 1),
                    check_count=len(config['checks']),
                    notice=config.get('notice', 'Bản thử căn chỉnh từ hồ sơ 2022. Chưa xác minh hiệu lực hiện tại; không dùng để xác định quy hoạch từng thửa.'),
                    attribution=config.get('attribution', 'UBND thị xã Bến Cát · hồ sơ 2022 · bản thử căn chỉnh'),
                    artifacts={name: hashlib.sha256((output/name).read_bytes()).hexdigest()
                               for name in ('overlay.webp', 'legend.webp')})
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    audit = {'source': config, 'affine_pixel_to_epsg3857': affine.tolist(),
             'control_errors_m': errors.tolist(), 'check_errors_m': check_errors.tolist(),
             'output_pixels': [width, height], 'manifest': manifest,
             'production_accuracy_passed': False, 'public_reuse_verified': False,
             'currency_verified': False}
    (output/'alignment-audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    build(args.config, args.output)

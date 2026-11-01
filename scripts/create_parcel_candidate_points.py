"""Find lookup seeds in boundary PNGs, never cadastral vertices or parcel polygons."""
import argparse
import json
import math
from pathlib import Path
import re

from PIL import Image


TILE = re.compile(r'https://s3\.hn-1\.cloud\.cmctelecom\.vn/guland9/qh-dong-nai/thuadat/(\d+)/(\d+)/(\d+)\.png')


def candidate_points(tiles):
    # Optional operator-only dependencies; neither is added to the web runtime.
    import cv2
    import numpy as np

    if not isinstance(tiles, list) or not 1 <= len(tiles) <= 9:
        raise ValueError('Use one to nine adjacent boundary tiles')
    images, descriptors, zoom, pixels = {}, {}, None, None
    for tile in tiles:
        match = TILE.fullmatch(tile['url'])
        if not match:
            raise ValueError('Unsupported boundary tile URL')
        z, x, y = map(int, match.groups())
        if not 14 <= z <= 22 or not (0 <= x < 2**z and 0 <= y < 2**z) or (x, y) in images:
            raise ValueError('Invalid or duplicate tile coordinates')
        path = Path(tile['file'])
        if path.stat().st_size > 2_000_000:
            raise ValueError('Oversized boundary image')
        with Image.open(path) as image:
            if image.format != 'PNG' or image.size not in ((256, 256), (512, 512)):
                raise ValueError('Expected a 256/512 pixel PNG tile')
            if zoom is not None and (zoom != z or pixels != image.width):
                raise ValueError('Mixed tile zooms or pixel sizes')
            zoom, pixels = z, image.width
            images[x, y] = np.array(image.convert('RGBA'))
            descriptors[x, y] = tile['url']
    west, east = min(x for x, y in images), max(x for x, y in images)
    north, south = min(y for x, y in images), max(y for x, y in images)
    if east-west > 2 or south-north > 2 or len(images) != (east-west+1)*(south-north+1):
        raise ValueError('Tiles must form a complete small rectangle')
    image = np.concatenate([np.concatenate([images[x, y] for x in range(west, east+1)], axis=1)
                            for y in range(north, south+1)], axis=0)
    boundary = (image[:, :, 3] > 24).astype('uint8')
    boundary = cv2.dilate(boundary, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(1-boundary, connectivity=4)
    seeds = []
    for index in range(1, count):
        x, y, width, height, area = map(int, stats[index])
        if area < 20 or x == 0 or y == 0 or x+width == image.shape[1] or y+height == image.shape[0]:
            continue
        region = (labels[y:y+height, x:x+width] == index).astype('uint8')
        distance = cv2.distanceTransform(region, cv2.DIST_L2, 5)
        _, clearance, _, point = cv2.minMaxLoc(distance)
        if clearance < 3:
            continue
        px, py = x+point[0], y+point[1]
        tx, ty = west+px//pixels, north+py//pixels
        local_x, local_y = px % pixels+.5, py % pixels+.5
        lon = (tx+local_x/pixels)/2**zoom*360-180
        lat = math.degrees(math.atan(math.sinh(math.pi*(1-2*(ty+local_y/pixels)/2**zoom))))
        seeds.append(dict(seed_only=True, url=descriptors[tx, ty], pixel_x=local_x, pixel_y=local_y,
                          pixels=pixels, lat=lat, lng=lon, clearance_px=round(clearance, 2), region_pixels=area))
    return sorted(seeds, key=lambda s: (s['url'], s['pixel_y'], s['pixel_x']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path, help='JSON list of observed tile URL and local PNG file')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.manifest.stat().st_size > 100_000:
        raise ValueError('Oversized tile manifest')
    seeds = candidate_points(json.loads(args.manifest.read_bytes()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(seeds, indent=2), encoding='utf-8')
    print(f'{len(seeds)} lookup seeds; not cadastral coordinates or complete parcel coverage')


if __name__ == '__main__':
    main()

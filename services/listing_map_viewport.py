"""Bounded viewport inputs and lightweight initial area framing, without a DB scan."""
from functools import lru_cache
import json
import math
import unicodedata

from config.listing_map import LISTING_MAP_BOUNDS, LISTING_MAP_WARD_BOUNDARY_PATHS, LISTING_MAP_WARD_REGISTRY_PATH


def parse_bbox(value):
    try:
        west, south, east, north = map(float, value.split(','))
    except (ValueError, AttributeError):
        raise ValueError('invalid_bbox') from None
    if not all(math.isfinite(v) for v in (west, south, east, north)) or not (
        -180 <= west < east <= 180 and -90 <= south < north <= 90
    ):
        raise ValueError('invalid_bbox')
    (miny, minx), (maxy, maxx) = LISTING_MAP_BOUNDS
    west, south, east, north = max(west, minx), max(south, miny), min(east, maxx), min(north, maxy)
    return (west, south, east, north) if west < east and south < north else ()


def _key(value):
    return ''.join(c for c in unicodedata.normalize('NFD', str(value).casefold().replace('đ','d'))
                   if unicodedata.category(c) != 'Mn').strip()


def _points(coordinates):
    if len(coordinates) >= 2 and all(isinstance(v, (int,float)) for v in coordinates[:2]):
        yield coordinates[:2]
    else:
        for child in coordinates:
            yield from _points(child)


@lru_cache(maxsize=1)
def _areas():
    cities = ('THỦ DẦU MỘT', 'BẾN CÁT', 'THUẬN AN', 'DĨ AN', 'TÂN UYÊN')
    rows = []
    for city, path in zip(cities, LISTING_MAP_WARD_BOUNDARY_PATHS):
        try:
            data = json.loads(path.read_text(encoding='utf8'))
            for feature in data['features']:
                points = list(_points(feature['geometry']['coordinates']))
                xs, ys = zip(*points)
                rows.append((_key(city), _key(feature['properties']['name']), [[min(ys),min(xs)], [max(ys),max(xs)]]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    # A retained centre can still frame a ward whose historic boundary is unavailable.
    known = {(city, ward) for city, ward, _ in rows}
    for ward in json.loads(LISTING_MAP_WARD_REGISTRY_PATH.read_text(encoding='utf8'))['wards']:
        city, name = _key(ward['city']), _key(ward['ward'])
        if (city,name) not in known:
            lat, lng = ward['lat'], ward['lng']
            rows.append((city,name,[[lat-.006,lng-.006],[lat+.006,lng+.006]]))
            known.add((city,name))
    from config.planning_parcels import PLANNING_REGIONS
    for area in PLANNING_REGIONS:
        city,name = _key(area['city']),_key(area['ward'])
        if (city,name) not in known:
            rows.append((city,name,area['bounds']))
            known.add((city,name))
    return rows


def initial_bounds(cities=(), wards=()):
    cities = {_key(part) for value in cities for part in value.split(',') if part.strip()}
    wards = {_key(value) for value in wards if value.strip()}
    areas = [bounds for city, ward, bounds in _areas() if (not cities or city in cities) and (not wards or ward in wards)]
    if not areas and wards:
        return initial_bounds(tuple(cities), ())
    if not areas:
        return LISTING_MAP_BOUNDS
    return [[min(b[0][0] for b in areas),min(b[0][1] for b in areas)],
            [max(b[1][0] for b in areas),max(b[1][1] for b in areas)]]

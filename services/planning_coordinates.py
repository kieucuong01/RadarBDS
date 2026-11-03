"""Explicit WGS84 / VN-2000 input; never guess a survey projection."""
from functools import lru_cache
import math
import re

PROJECTIONS = {'tm3-10300':9205,'tm3-10400':9206,'tm3-10430':9207,'tm3-10445':9208,
               'tm3-10500':None,'tm3-10530':9209,'tm3-10545':9210,'tm3-10600':9211,
               'tm3-10615':9212,'tm3-10630':9213,'tm3-10700':9214,'tm3-10715':9215,
               'tm3-10730':9216,'tm3-10745':5899,'tm3-10815':9217,'tm3-10830':9218,
               'utm48':3405,'utm49':3406}


def projection_crs(code):
    if code != 'tm3-10500':
        return PROJECTIONS[code]
    from pyproj.crs import CRS, ProjectedCRS
    from pyproj.crs.coordinate_operation import TransverseMercatorConversion
    return ProjectedCRS(name='VN-2000 / TM-3 105-00', geodetic_crs=CRS.from_epsg(4756),
                        conversion=TransverseMercatorConversion(latitude_natural_origin=0,
                            longitude_natural_origin=105, scale_factor_natural_origin=.9999,
                            false_easting=500000, false_northing=0))


def _number(value):
    if not isinstance(value, str) or not re.fullmatch(r'[+-]?\d{1,9}(?:[.,]\d{1,18})?', value.strip()):
        raise ValueError('Invalid coordinate')
    return float(value.strip().replace(',', '.'))


@lru_cache(maxsize=len(PROJECTIONS))
def _transformer(code):
    from pyproj.transformer import TransformerGroup
    group = TransformerGroup(projection_crs(code), 4326, always_xy=True, allow_ballpark=False)
    if not group.transformers:
        raise ValueError('No accurate datum transformation available')
    return group.transformers[0]


def coordinate_point(values):
    first, second = _number(values.get('first')), _number(values.get('second'))
    if values.get('system') == 'wgs84':
        lon, lat, accuracy = second, first, None
    elif values.get('system') == 'vn2000' and values.get('crs') in PROJECTIONS:
        if not (100000 <= first <= 3000000 and 100000 <= second <= 900000):
            raise ValueError('Invalid VN-2000 northing/easting')
        transformer = _transformer(values['crs'])
        lon, lat = transformer.transform(second, first, errcheck=True)
        accuracy = transformer.accuracy
    else:
        raise ValueError('Unknown coordinate system')
    if not (math.isfinite(lon) and math.isfinite(lat) and 100 <= lon <= 112 and 6 <= lat <= 25):
        raise ValueError('Coordinate outside Vietnam reference bounds')
    return lon, lat, accuracy


def coordinate_outline(values):
    """Convert user corner coordinates; never label the outline as a GIS parcel."""
    from pyproj import Geod
    from shapely.geometry import Polygon, mapping
    if not isinstance(values, dict) or not isinstance(values.get('corners'), str):
        raise ValueError('Missing corner coordinates')
    text = values['corners']
    if len(text) > 12000:
        raise ValueError('Too many corner coordinates')
    rows = [line.strip() for line in text.splitlines() if line.strip()]
    if not 3 <= len(rows) <= 101:
        raise ValueError('Use 3 to 100 corners')
    points, accuracy = [], None
    for index, row in enumerate(rows, 1):
        cells = re.split(r'[;\s]+', row)
        if len(cells) == 3 and cells[0] == str(index):
            cells = cells[1:]
        if len(cells) != 2:
            raise ValueError('Use two coordinates per row, optionally preceded by point number')
        lon, lat, accuracy = coordinate_point(dict(values, first=cells[0], second=cells[1]))
        points.append((lon, lat))
    if points[0] == points[-1]:
        points.pop()
    if not 3 <= len(points) <= 100 or len(set(points)) != len(points):
        raise ValueError('Duplicate or missing corner coordinates')
    polygon = Polygon(points)
    if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
        raise ValueError('Crossed or empty boundary')
    west, south, east, north = polygon.bounds
    if east-west > 1 or north-south > 1:
        raise ValueError('Boundary is too large; check coordinate system')
    area, perimeter = Geod(ellps='WGS84').geometry_area_perimeter(polygon)
    if abs(area) < .01:
        raise ValueError('Boundary area is too small')
    center = polygon.representative_point()
    return dict(type='Feature', geometry=mapping(polygon),
                properties=dict(origin='user_corners', area=abs(area), perimeter=perimeter,
                                vertex_count=len(points), transform_accuracy_m=accuracy),
                point=[center.y, center.x])

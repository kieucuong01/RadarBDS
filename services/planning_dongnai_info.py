"""Planning intersections from allowlisted public Dong Nai GIS layers."""
import json
import math
from pathlib import Path
import requests

from services.planning_dongnai_parcels import DongNaiGIS, PLANNING_QUERIES, SOURCE
from services.planning_parcels import esri_geometry

PLAN_SOURCES = ((PLANNING_QUERIES[0], 'Quy hoạch chi tiết'),
                (PLANNING_QUERIES[1], 'Quy hoạch chung đô thị'))
FIELDS = ('OBJECTID,KyHieuLoaiDat,MucDichSuDung,TenKhuChucNang,TangCaoXayDung,'
          'MatDoXayDungTrungBinh,HeSoSuDungDat')


def _polygon(rings):
    from shapely.geometry import shape
    if (not isinstance(rings, list) or not 0 < len(rings) <= 100
            or any(not isinstance(r, list) for r in rings)
            or sum(len(r) for r in rings) > 20000
            or any(len(r) < 4 or r[0] != r[-1] or any(
                not isinstance(p, list) or len(p) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in p)
                or not (106.25 <= p[0] <= 107.65 and 11.2 <= p[1] <= 12.4)
                for p in r) for r in rings)):
        raise ValueError('Invalid planning rings')
    polygon = shape(esri_geometry(rings))
    if polygon.is_empty or not polygon.is_valid:
        raise ValueError('Invalid planning polygon')
    return polygon


def _area(geometry):
    from pyproj import Geod
    geod = Geod(ellps='WGS84')
    if geometry.geom_type == 'Polygon':
        def ring_area(ring):
            x, y = ring.xy
            return abs(geod.polygon_area_perimeter(x, y)[0])
        return max(0, ring_area(geometry.exterior) - sum(ring_area(r) for r in geometry.interiors))
    return sum(_area(g) for g in getattr(geometry, 'geoms', []))


class DongNaiPlanning:
    def __init__(self, client=None):
        self.client = client or DongNaiGIS()
        self.land_codes = json.loads((Path(__file__).resolve().parents[1] /
            'config/planning_dongnai_land_codes.json').read_text(encoding='utf8'))['codes']

    def lookup(self, feature):
        if feature['properties'].get('source') != SOURCE:
            raise ValueError('Wrong cadastral provider')
        geometry = feature['geometry']
        if geometry['type'] not in ('Polygon', 'MultiPolygon'):
            raise ValueError('Invalid parcel geometry')
        rings = geometry['coordinates'] if geometry['type'] == 'Polygon' else [
            ring for polygon in geometry['coordinates'] for ring in polygon]
        parcel = _polygon(rings)
        from shapely.errors import GEOSException
        plans, unavailable, successful = [], [], 0
        for path, title in PLAN_SOURCES:
            try:
                plans.extend(self._layer(path, title, rings, parcel))
                successful += 1
            except (requests.RequestException, ValueError, KeyError, TypeError, GEOSException):
                unavailable.append(title)
        if not successful:
            raise ValueError('All planning sources unavailable')
        return dict(plans=plans, unavailable_layers=unavailable)

    def _layer(self, path, title, rings, parcel):
        from shapely.ops import unary_union
        extra = ',TenDuAn,KyHieuLoDat' if path == PLANNING_QUERIES[0] else ''
        params = dict(f='json', where='1=1',
            geometry=json.dumps({'rings': rings, 'spatialReference': {'wkid': 4326}}, separators=(',', ':')),
            geometryType='esriGeometryPolygon', inSR=4326, spatialRel='esriSpatialRelIntersects',
            outFields=FIELDS+extra, returnGeometry='true', outSR=4326,
            resultRecordCount=100, orderByFields='OBJECTID ASC')
        requested = None
        if path == PLANNING_QUERIES[1]:
            # Direct-ID geometry fetch avoids the slow spatial+geometry query on this service.
            index = self.client.request(path, params=dict(params, returnGeometry='false', outFields='OBJECTID'))
            candidates = index.get('features') if isinstance(index, dict) else None
            if (not isinstance(candidates, list) or len(candidates) >= 100
                    or index.get('error') or index.get('exceededTransferLimit')):
                raise ValueError('Incomplete planning index')
            requested = []
            for row in candidates:
                attributes = row.get('attributes') if isinstance(row, dict) else None
                oid = attributes.get('OBJECTID') if isinstance(attributes, dict) else None
                if type(oid) is not int or not 0 < oid < 2**53 or oid in requested:
                    raise ValueError('Invalid planning index')
                requested.append(oid)
            if not requested:
                return []
            params = dict(f='json', objectIds=','.join(map(str, requested)),
                          outFields=FIELDS, returnGeometry='true', outSR=4326,
                          resultRecordCount=100, orderByFields='OBJECTID ASC')
        data = self.client.request(path, params=params)
        rows = data.get('features') if isinstance(data, dict) else None
        if (not isinstance(rows, list) or len(rows) >= 100 or data.get('error')
                or data.get('exceededTransferLimit')
                or (rows and data.get('spatialReference', {}).get('wkid') != 4326)):
            raise ValueError('Incomplete or invalid planning response')
        groups, seen = {}, set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('geometry'), dict):
                raise ValueError('Invalid planning feature')
            attr = row.get('attributes')
            if not isinstance(attr, dict):
                raise ValueError('Invalid planning attributes')
            oid = attr.get('OBJECTID')
            if type(oid) is not int or not 0 < oid < 2**53 or oid in seen:
                raise ValueError('Invalid planning identifier')
            seen.add(oid)
            values = {}
            for key in (FIELDS+extra).split(','):
                value = attr.get(key)
                if value is not None and (type(value) not in (str, int, float)
                        or isinstance(value, str) and (len(value) > 2000 or '\x00' in value)
                        or isinstance(value, (int, float)) and not math.isfinite(value)):
                    raise ValueError('Invalid planning value')
                values[key] = value
            intersection = parcel.intersection(_polygon((row.get('geometry') or {}).get('rings')))
            area = _area(intersection)
            if area <= 0:
                continue
            name = values.get('TenDuAn') or values.get('MaDuAn') or title
            group = groups.setdefault(str(name), {'type': title, 'name': str(name), 'zones': [], '_intersections': []})
            group['_intersections'].append(intersection)
            group['zones'].append(dict(
                maMucDichSuDungDat=values.get('MucDichSuDung') or values.get('KyHieuLoaiDat'),
                mucDichSuDungDat=values.get('TenKhuChucNang') or self.land_codes.get(str(values.get('MucDichSuDung'))) or values.get('MucDichSuDung'),
                dienTich=round(area, 2), kyHieuLoDat=values.get('KyHieuLoDat'),
                tangCaoXayDung=values.get('TangCaoXayDung'),
                matDoXayDungTrungBinh=values.get('MatDoXayDungTrungBinh'),
                heSoSuDungDat=values.get('HeSoSuDungDat')))
        if requested is not None and seen != set(requested):
            raise ValueError('Incomplete planning geometry batch')
        plans = []
        for group in groups.values():
            group['intersection_area'] = round(_area(unary_union(group.pop('_intersections'))), 2)
            plans.append(group)
        return plans

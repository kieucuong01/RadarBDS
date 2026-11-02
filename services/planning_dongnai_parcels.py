"""Anonymous cadastral queries from Dong Nai GIS (former Binh Phuoc coverage)."""
import json
from pathlib import Path

import requests

from services.planning_live_parcels import LiveParcels

SOURCE = 'https://gis.dongnai.gov.vn/'
QUERY = '/arcgis/rest/services/NenDiaChinh/MapServer/1/query'
PLANNING_QUERIES = (
    '/arcgis/rest/services/QHCT/QHCT_SDD/FeatureServer/0/query',
    '/arcgis/rest/services/SuDungDat/ThongTinQuyHoachSDD_Cache/MapServer/6/query',
)
# Keep public IDs disjoint from the existing HCM/immutable catalogue IDs.
ID_OFFSET = 1_000_000_000_000


class DongNaiGIS:
    def request(self, path, *, params):
        if path not in (QUERY, *PLANNING_QUERIES):
            raise ValueError('Unsupported Dong Nai endpoint')
        # ArcGIS query is read-only. POST avoids IIS limits for long polygons.
        planning = path in PLANNING_QUERIES
        method, arguments = (requests.post, {'data': params}) if planning else (requests.get, {'params': params})
        with method(SOURCE.rstrip('/') + path, **arguments, timeout=(3, 5) if planning else (5, 20),
                    stream=True, allow_redirects=False) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError('Unexpected source redirect')
            parts, size = [], 0
            for part in response.iter_content(65536):
                size += len(part)
                if size > 10_000_000:
                    raise ValueError('Oversized parcel response')
                parts.append(part)
        data = json.loads(b''.join(parts))
        if not isinstance(data, dict) or data.get('error'):
            raise ValueError('Invalid source response')
        return data


class DongNaiParcels(LiveParcels):
    query_path = QUERY
    fallback_path = None
    excluded_districts = frozenset()
    coordinate_bounds = (106.25, 11.2, 107.65, 12.4)
    id_offset = ID_OFFSET
    source = SOURCE

    def __init__(self, client=None, cache_bytes=8_000_000):
        super().__init__(client=client or DongNaiGIS(), cache_bytes=cache_bytes)
        self.areas = json.loads((Path(__file__).resolve().parents[1] /
            'config/planning_dongnai_parcel_areas.json').read_text(encoding='utf8'))['areas']
        self.by_area = {a['area_id']: a for a in self.areas}
        self.all_where = 'MaQuanHuyen IN (' + ','.join(
            "'%s'" % d for d in sorted({a['district'] for a in self.areas})) + ')'

    def _reference_key(self, code, district):
        # The public administrative layer reuses three ward codes across districts.
        return 'bp-%s-%s' % (district, code)


class RegionalParcels:
    """Route verified regional sources without mixing their object identifiers."""
    coverage_bounds = [[8.5, 106.25], [13.0, 109.6]]
    revision = 'regional-khanhhoa-20261102'

    def __init__(self, hcm=None, dongnai=None, khanhhoa=None):
        from services.planning_khanh_hoa_parcels import KhanhHoaParcels
        self.hcm = hcm if hcm is not None else LiveParcels()
        self.dongnai = dongnai if dongnai is not None else DongNaiParcels()
        self.khanhhoa = khanhhoa if khanhhoa is not None else KhanhHoaParcels()
        self.providers = (self.hcm, self.dongnai, self.khanhhoa)
        self.areas = [a for p in self.providers for a in p.areas]
        self.snapshot_areas = set()

    def _covered(self, provider):
        keys = {a.get('area_id', a['code']) for a in provider.areas}
        return bool(keys) and keys <= self.snapshot_areas

    def _provider(self, area):
        for provider in (self.dongnai, self.khanhhoa):
            if area in provider.by_area:
                return provider
        return self.hcm

    def search(self, area, sheet, parcel):
        return self._provider(area).search(area, sheet, parcel)

    def sample(self, area):
        return self._provider(area).sample(area)

    def feature(self, identifier, area=None):
        from services.planning_khanh_hoa_parcels import ID_OFFSET as KH_OFFSET
        provider = self.khanhhoa if identifier >= KH_OFFSET else self.dongnai if identifier >= ID_OFFSET else self.hcm
        return provider.feature(identifier, area)

    @staticmethod
    def _intersects(provider, bbox):
        west, south, east, north = bbox
        return any(a['bounds'][0][1] <= east and a['bounds'][1][1] >= west
                   and a['bounds'][0][0] <= north and a['bounds'][1][0] >= south
                   for a in provider.areas
                   if a['district'] not in provider.excluded_districts)

    def needs_viewport(self, bbox, legacy_areas):
        return any(not self._covered(p) and self._intersects(p, bbox) for p in self.providers)

    def viewport(self, bbox):
        features, matched, excluded, truncated = [], 0, 0, False
        for provider in self.providers:
            if not self._covered(provider) and self._intersects(provider, bbox):
                result = provider.viewport(bbox)
                features.extend(result['features'])
                matched += result['matched']
                excluded += result.get('excluded_count', 0)
                truncated = truncated or result['truncated']
        return dict(type='FeatureCollection', features=features[:1500], matched=matched,
                    excluded_count=excluded, truncated=truncated or len(features) > 1500)

    def point(self, longitude, latitude):
        features, truncated = [], False
        for provider in self.providers:
            if self._intersects(provider, (longitude, latitude, longitude, latitude)):
                result = provider.point(longitude, latitude)
                features.extend(result['features'])
                truncated = truncated or result['truncated']
        return dict(type='FeatureCollection', features=features[:20], matched=len(features),
                    truncated=truncated or len(features)>20)

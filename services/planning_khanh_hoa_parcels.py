"""Anonymous official Khánh Hòa cadastral source; original polygons only."""
import json
from pathlib import Path

import requests

from services.planning_live_parcels import LiveParcels

SOURCE = 'https://gis.khanhhoa.gov.vn/'
QUERY = '/arcgis/rest/services/Base/DiaChinh/MapServer/8/query'
ID_OFFSET = 2_000_000_000_000
FIELDS = 'OBJECTID,So_To,So_Thua,Dien_Tich,MaXa,MaHuyen,TenPhuong,TenHuyen'


class KhanhHoaGIS:
    def request(self, path, *, params):
        fields = params.get('outFields')
        aggregate = any(params.get(key) == 'true' for key in ('returnCountOnly','returnIdsOnly','returnExtentOnly'))
        if (path != QUERY or fields not in (None, FIELDS, 'MaXa,MaHuyen,TenPhuong,TenHuyen')
                or fields is None and not aggregate):
            raise ValueError('Unsupported Khánh Hòa endpoint')
        with requests.get(SOURCE.rstrip('/')+QUERY, params=params, timeout=(4, 12),
                          stream=True, allow_redirects=False) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError('Unexpected GIS redirect')
            raw = bytearray()
            for part in response.iter_content(65536):
                raw.extend(part)
                if len(raw)>10_000_000:
                    raise ValueError('Oversized GIS response')
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('error'):
            raise ValueError('Invalid GIS response')
        return data


class KhanhHoaParcels(LiveParcels):
    query_path = QUERY
    fallback_path = None
    query_fields = FIELDS
    sheet_field, parcel_field = 'So_To', 'So_Thua'
    excluded_districts = frozenset()
    coordinate_bounds = (108.5, 11.7, 109.6, 13.0)
    id_offset = ID_OFFSET
    source = SOURCE

    def __init__(self, client=None, cache_bytes=8_000_000):
        super().__init__(client=client or KhanhHoaGIS(), cache_bytes=cache_bytes)
        self.areas = json.loads((Path(__file__).resolve().parents[1] /
            'config/planning_khanh_hoa_parcel_areas.json').read_text(encoding='utf8'))['areas']
        self.by_area = {a['area_id']: a for a in self.areas}
        self.all_where = 'MaHuyen IN (' + ','.join("'%s'" % value for value in sorted(
            {a['source_district_value'] for a in self.areas})) + ')'

    def _reference_key(self, code, district):
        return f'kh-{district}-{code}'

    def _attributes(self, attributes):
        code, district = str(attributes.get('MaXa') or '').strip(), str(attributes.get('MaHuyen') or '').strip()
        ref = self.by_area.get(self._reference_key(code, district))
        if (not ref or attributes.get('TenPhuong') != ref['source_ward']
                or attributes.get('TenHuyen') != ref['source_city']):
            # Source has null and conflicting locality rows; never guess their membership.
            return None
        return dict(OBJECTID=attributes.get('OBJECTID'), SoTo=attributes.get('So_To'),
                    SoThua=attributes.get('So_Thua'), DienTich=attributes.get('Dien_Tich'),
                    MaPhuongXa=code, MaQuanHuyen=district)

    def _area_where(self, area):
        ref = self.by_area.get(area)
        if not ref:
            raise ValueError('Unsupported Khánh Hòa area')
        return "MaXa = '%s' AND MaHuyen = '%s'" % (ref['code'], ref['source_district_value'])

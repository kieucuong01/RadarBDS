"""Verified optional Bình Phước spatial snapshot; reuse existing bounded readers."""
from hashlib import file_digest
import json
from pathlib import Path
import re

from services.planning_parcel_catalog import ParcelCatalog
from services.planning_dongnai_parcels import DongNaiParcels, SOURCE, ID_OFFSET


def load_catalog(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'catalog.json').read_bytes())
    if not re.fullmatch(r'[a-f0-9]{64}', manifest['sha256']):
        raise ValueError('Invalid snapshot digest')
    target = directory/f"parcels-{manifest['sha256'][:16]}.sqlite"
    if (manifest['source'] != SOURCE or manifest['status'] != 'complete'
            or target.is_symlink() or target.stat().st_size != manifest['bytes']):
        raise ValueError('Invalid Bình Phước snapshot')
    with target.open('rb') as stream:
        if file_digest(stream, 'sha256').hexdigest() != manifest['sha256']:
            raise ValueError('Bình Phước snapshot hash mismatch')
    catalog = ParcelCatalog(target)
    refs = DongNaiParcels().by_area
    if ({a['area_id'] for a in catalog.areas} != set(refs)
            or sum(a['count'] for a in catalog.areas) != manifest['accepted']
            or any((a['ward'], a['city']) != (refs[a['area_id']]['ward'], refs[a['area_id']]['city'])
                   for a in catalog.areas)):
        raise ValueError('Bình Phước snapshot membership mismatch')
    with catalog.connect() as conn:
        count, minimum = conn.execute('SELECT count(*),min(id) FROM parcels').fetchone()
        if count != manifest['accepted'] or minimum <= ID_OFFSET:
            raise ValueError('Bình Phước snapshot totals/namespace mismatch')
    catalog.version = manifest['sha256']
    return catalog


class CombinedCatalog:
    def __init__(self, base, supplement):
        self.catalogs = (base, supplement)
        self.areas = base.areas + supplement.areas
        if len({a['area_id'] for a in self.areas}) != len(self.areas):
            raise ValueError('Overlapping snapshot areas')
        self.version = supplement.version

    def feature(self, identifier, area=None):
        return self.catalogs[identifier >= ID_OFFSET].feature(identifier, area)

    def _query(self, method, *args):
        rows, count = [], 0
        for catalog in self.catalogs:
            features, matched = getattr(catalog, method)(*args)
            rows.extend(features)
            count += matched
        return sorted(rows, key=lambda f: f['id'])[:1500], count

    def viewport(self, bbox):
        return self._query('viewport', bbox)

    def cell(self, bbox):
        return self._query('cell', bbox)

    def search(self, area, sheet, parcel):
        catalog = self.catalogs[area.startswith('bp-')]
        return catalog.search(area, sheet, parcel)

    def point(self, longitude, latitude):
        return [f for catalog in self.catalogs for f in catalog.point(longitude, latitude)]

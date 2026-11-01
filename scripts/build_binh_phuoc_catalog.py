"""Validate a complete offline capture and atomically publish its spatial index."""
import argparse
from contextlib import closing
from hashlib import sha256, file_digest
import json
import math
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.capture_binh_phuoc_parcels import encode
from services.planning_dongnai_parcels import DongNaiParcels, SOURCE, QUERY, ID_OFFSET


def administrative_index(path, references):
    """Verify the official administrative capture against the existing reference list."""
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    from services.planning_parcels import esri_geometry
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if data.get('spatialReference', {}).get('wkid') != 4326 or data.get('exceededTransferLimit'):
        raise ValueError('Invalid administrative coordinate system/completeness')
    refs, geometries = [], []
    for row in data['features']:
        attrs = row['attributes']
        key = f"bp-{attrs['MaQuanHuyen']}-{attrs['MaPhuongXa']}"
        ref = references.get(key)
        if not ref or (attrs['TenXa'], attrs['TenHuyen']) != (ref['ward'], ref['city']):
            raise ValueError('Administrative reference mismatch')
        geom = shape(esri_geometry(row['geometry']['rings']))
        if geom.is_empty or not geom.is_valid:
            raise ValueError('Invalid administrative polygon')
        refs.append(ref)
        geometries.append(geom)
    if len(refs) != len(references) or {r['area_id'] for r in refs} != set(references):
        raise ValueError('Incomplete administrative capture')
    return STRtree(geometries), refs, sha256(raw).hexdigest()


def resolve_locality(feature, administrative):
    from shapely.geometry import shape
    attrs = feature['properties']['source_attributes']
    geom = shape(feature['geometry'])
    if not geom.is_valid or geom.is_empty:
        raise ValueError('Invalid quarantined polygon')
    tree, refs, _ = administrative
    hits = tree.query(geom, predicate='within')
    if len(hits) != 1:
        return None
    ref = refs[int(hits[0])]
    if str(attrs['MaQuanHuyen']) != ref['district']:
        return None
    props = dict(id=ID_OFFSET+attrs['OBJECTID'], source_id=attrs['OBJECTID'], source=SOURCE,
                 area_id=ref['area_id'], ward=ref['ward'], city=ref['city'], province='binh-phuoc',
                 source_ward_code=str(attrs['MaPhuongXa']), source_district_code=str(attrs['MaQuanHuyen']),
                 membership_method='official_admin_full_containment')
    for field, key in [('sheet','SoTo'),('parcel','SoThua'),('area','DienTich')]:
        value = attrs[key]
        if value is not None and (type(value) not in (str, int, float)
                or isinstance(value, str) and (len(value)>100 or any(ord(c)<32 for c in value))
                or isinstance(value, (int, float)) and not math.isfinite(value)):
            raise ValueError('Invalid quarantined basic attribute')
        props[field] = value
    return dict(type='Feature', id=props['id'], properties=props, geometry=feature['geometry'])


def build(directory, administrative_path=None):
    from shapely.geometry import shape
    directory = Path(directory)
    manifest_raw = (directory/'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    ids_raw = (directory/'identifiers.json').read_bytes()
    ids = json.loads(ids_raw)
    size = manifest['batch_size']
    if (manifest['status'] != 'complete' or manifest['source'] != SOURCE
            or manifest['query_endpoint'] != QUERY or size != 500
            or sha256(ids_raw).hexdigest() != manifest['ids_sha256']
            or len(ids) != manifest['source_count'] or len(set(ids)) != len(ids)
            or manifest['accepted']+manifest['excluded'] != len(ids)
            or not 0 <= manifest.get('quarantined', 0) <= manifest['excluded']
            or ids != sorted(ids) or not ids
            or any(type(i) is not int or not 0 < i < 2**53-ID_OFFSET for i in ids)
            or set(manifest['batches']) != {str(i) for i in range(0, len(ids), size)}):
        raise ValueError('Incomplete or invalid parcel capture')
    provider = DongNaiParcels()
    if manifest['where'] != provider.all_where:
        raise ValueError('Unexpected capture scope')
    administrative = administrative_index(administrative_path, provider.by_area) if administrative_path else None
    areas = {key: dict(ref, count=0, excluded_count=0, source=SOURCE,
                       captured_at=manifest['finished_at'], sample_id=None)
             for key, ref in provider.by_area.items()}
    temporary = directory/'parcels.sqlite.download'
    if temporary.exists():
        temporary.unlink()
    accepted = excluded = quarantined = recovered = 0
    try:
        with closing(sqlite3.connect(temporary)) as conn:
            conn.executescript('''
                CREATE TABLE areas (code TEXT PRIMARY KEY, metadata TEXT NOT NULL);
                CREATE TABLE parcels (id INTEGER PRIMARY KEY, area TEXT NOT NULL, feature TEXT NOT NULL);
                CREATE VIRTUAL TABLE bounds USING rtree(id, west, east, south, north);
            ''')
            for offset in range(0, len(ids), size):
                record = manifest['batches'][str(offset)]
                raw = (directory/f'{offset:07d}.geojson').read_bytes()
                if sha256(raw).hexdigest() != record['sha256']:
                    raise ValueError('Captured batch hash mismatch')
                batch = json.loads(raw)
                requested = ids[offset:offset+size]
                source_ids = [f['properties']['source_id'] for f in batch['features']]
                excluded_ids = batch['excluded_ids']
                quarantine = batch.get('quarantined_features', [])
                if (batch['source'] != SOURCE or batch['query_endpoint'] != QUERY
                        or batch['requested_ids'] != requested
                        or len(source_ids) != record['accepted']
                        or len(excluded_ids) != record['excluded']
                        or len(quarantine) != record.get('quarantined', 0)
                        or len(source_ids)+len(excluded_ids) != len(requested)
                        or len(set(source_ids+excluded_ids)) != len(requested)
                        or set(source_ids+excluded_ids) != set(requested)
                        or not {f['id'] for f in quarantine} <= set(excluded_ids)):
                    raise ValueError('Captured batch membership mismatch')
                promoted = []
                if administrative:
                    for feature in quarantine:
                        if feature['id'] != feature['properties']['source_attributes']['OBJECTID']:
                            raise ValueError('Quarantined identifier mismatch')
                        resolved = resolve_locality(feature, administrative)
                        if resolved:
                            promoted.append(resolved)
                for feature in batch['features']+promoted:
                    props = feature['properties']
                    area = areas.get(props['area_id'])
                    if (not area or feature['id'] != props['id']
                            or props['id'] != ID_OFFSET+props['source_id']
                            or props['source'] != SOURCE or props['province'] != 'binh-phuoc'
                            or (props['ward'], props['city']) != (area['ward'], area['city'])
                            or set(props) - {'source_ward_code','source_district_code','membership_method'}
                                != {'id','area_id','source_id','source','province',
                                    'ward','city','sheet','parcel','area'}):
                        raise ValueError('Invalid captured feature membership/fields')
                    geom = shape(feature['geometry'])
                    if geom.is_empty or not geom.is_valid or geom.geom_type not in ('Polygon', 'MultiPolygon'):
                        raise ValueError('Invalid captured geometry')
                    w, s, e, n = geom.bounds
                    if not (106.25 <= w <= e <= 107.65 and 11.2 <= s <= n <= 12.4):
                        raise ValueError('Captured geometry outside Bình Phước')
                    conn.execute('INSERT INTO parcels VALUES (?,?,?)',
                                 (feature['id'], props['area_id'], encode(feature).decode()))
                    conn.execute('INSERT INTO bounds VALUES (?,?,?,?,?)', (feature['id'], w, e, s, n))
                    area['count'] += 1
                    area['sample_id'] = area['sample_id'] or feature['id']
                accepted += len(source_ids)
                excluded += len(excluded_ids)
                quarantined += len(quarantine)
                recovered += len(promoted)
            if (accepted, excluded, quarantined) != (manifest['accepted'], manifest['excluded'], manifest.get('quarantined', 0)):
                raise ValueError('Captured totals mismatch')
            for key, area in areas.items():
                conn.execute('INSERT INTO areas VALUES (?,?)', (key, json.dumps(area, ensure_ascii=False)))
            conn.execute("""CREATE INDEX parcel_lookup ON parcels(
                area,trim(CAST(json_extract(feature,'$.properties.sheet') AS TEXT)),
                trim(CAST(json_extract(feature,'$.properties.parcel') AS TEXT)))""")
            conn.commit()
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Parcel index integrity failure')
        if (directory/'manifest.json').read_bytes() != manifest_raw:
            raise ValueError('Capture changed during index build')
        with temporary.open('rb') as stream:
            digest = file_digest(stream, 'sha256').hexdigest()
        publication = dict(source=SOURCE, status='complete', sha256=digest,
                           bytes=temporary.stat().st_size, accepted=accepted+recovered, excluded=excluded-recovered,
                           quarantined=quarantined-recovered, recovered_localities=recovered, source_count=len(ids),
                           administrative_sha256=administrative[2] if administrative else None,
                           captured_at=manifest['finished_at'], capture_sha256=sha256(manifest_raw).hexdigest())
        target = directory/f'parcels-{digest[:16]}.sqlite'
        # Keep old immutable indexes usable until the manifest is atomically replaced.
        temporary.replace(target)
        from scripts.capture_binh_phuoc_parcels import write_json
        write_json(directory/'catalog.json', publication)
        return publication
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT/'data/planning/binh-phuoc-parcels')
    parser.add_argument('--administrative', type=Path, help='Verified public NenDiaChinh layer 3 capture, outSR=4326')
    args = parser.parse_args()
    print(json.dumps(build(args.directory, args.administrative), ensure_ascii=False))

"""Resume anonymous GIS parcel batches into a separate local spatial-data archive."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.planning_dongnai_parcels import DongNaiParcels, QUERY, SOURCE
from services.planning_parcels import FIELDS

BATCH_SIZE = 500
_last_query = 0


def _source_query_once(params):
    """One fixed public read-only endpoint; no credentials, redirects or concurrent requests."""
    global _last_query
    time.sleep(max(0, 1 - (time.monotonic() - _last_query)))
    _last_query = time.monotonic()
    with requests.post(SOURCE.rstrip('/')+QUERY, data=dict(params, f='json'),
                       timeout=(5, 25), stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('Unexpected GIS redirect')
        parts, size = [], 0
        for part in response.iter_content(65536):
            size += len(part)
            if size > 10_000_000:
                raise ValueError('Oversized GIS response')
            parts.append(part)
    data = json.loads(b''.join(parts))
    if not isinstance(data, dict) or data.get('error'):
        raise ValueError('GIS query failed')
    return data


def source_query(params):
    for attempt in range(3):
        try:
            return _source_query_once(params)
        except requests.HTTPError as error:
            if error.response is None or error.response.status_code not in (500, 502, 503, 504) or attempt == 2:
                raise
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
        time.sleep((2, 5)[attempt])


def encode(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def write_json(path, data):
    raw = encode(data)
    temporary = path.with_suffix(path.suffix+'.download')
    temporary.write_bytes(raw)
    temporary.replace(path)
    return sha256(raw).hexdigest()


def identifiers(where):
    count = source_query(dict(where=where, returnCountOnly='true')).get('count')
    if type(count) is not int or not 0 < count <= 2_000_000:
        raise ValueError('Invalid GIS count')
    ids = source_query(dict(where=where, returnIdsOnly='true')).get('objectIds')
    if (not isinstance(ids, list) or len(ids) != count
            or any(type(i) is not int or not 0 < i < 2**53-1_000_000_000_000 for i in ids)
            or len(set(ids)) != count):
        raise ValueError('Incomplete GIS identifiers')
    return sorted(ids)


def normalise_batch(data, requested):
    rows = data.get('features')
    if not isinstance(rows, list) or len(rows) != len(requested) or data.get('exceededTransferLimit'):
        raise ValueError('Incomplete GIS batch')
    returned = [row.get('attributes', {}).get('OBJECTID') for row in rows]
    if any(type(i) is not int for i in returned) or len(set(returned)) != len(requested) or set(returned) != set(requested):
        raise ValueError('GIS batch identifier mismatch')
    if data.get('spatialReference', {}).get('wkid') != 4326:
        raise ValueError('Unexpected GIS coordinate system')
    references = DongNaiParcels().by_area
    eligible, unverified = [], []
    for row in rows:
        attrs = row['attributes']
        key = f"bp-{attrs.get('MaQuanHuyen')}-{attrs.get('MaPhuongXa')}"
        (eligible if key in references else unverified).append(row)
    checked = dict(data, features=eligible)

    class CapturedResponse:
        def request(self, path, *, params):
            return checked

    # Reuse the live adapter's CRS, original-ring, field and administrative guards.
    provider = DongNaiParcels(client=CapturedResponse())
    result = provider._query(('offline-batch',), {}, limit=1000)
    accepted = {f['properties']['source_id'] for f in result['features']}
    excluded = sorted(set(requested)-accepted)
    if not accepted <= set(requested) or len(excluded) != result['excluded_count']+len(unverified):
        raise ValueError('Incomplete geometry validation')
    reasons = {str(i): 'invalid_source_geometry' for i in excluded}
    quarantined = []
    from services.planning_dongnai_info import _polygon
    from shapely.geometry import mapping
    from shapely.errors import GEOSException
    for row in unverified:
        identifier = row['attributes']['OBJECTID']
        reasons[str(identifier)] = 'unverified_source_locality'
        try:
            geometry = mapping(_polygon((row.get('geometry') or {}).get('rings')))
        except (ValueError, TypeError, GEOSException):
            reasons[str(identifier)] += '_and_invalid_geometry'
            continue
        attrs = {k: row['attributes'].get(k) for k in FIELDS.split(',')}
        if any(v is not None and type(v) not in (str, int, float) for v in attrs.values()):
            raise ValueError('Invalid quarantined source attributes')
        quarantined.append(dict(type='Feature', id=identifier, geometry=geometry,
                                properties=dict(source=SOURCE, source_attributes=attrs,
                                                locality_verified=False)))
    return dict(type='FeatureCollection', source=SOURCE, query_endpoint=QUERY,
                captured_at=datetime.now(timezone.utc).isoformat(), requested_ids=requested,
                excluded_ids=excluded, excluded_reasons=reasons, quarantined_features=quarantined,
                features=result['features'])


def download(directory, max_batches=1):
    # shortcut: one writer per archive; add a process lease before parallel workers.
    if type(max_batches) is not int or max_batches < 0:
        raise ValueError('Invalid batch limit')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path, ids_path = directory/'manifest.json', directory/'identifiers.json'
    where = DongNaiParcels().all_where
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_bytes())
        raw_ids = ids_path.read_bytes()
        if (manifest.get('source') != SOURCE or manifest.get('query_endpoint') != QUERY
                or manifest.get('where') != where or manifest.get('batch_size') != BATCH_SIZE
                or sha256(raw_ids).hexdigest() != manifest['ids_sha256']):
            raise ValueError('Archive source or identifier hash mismatch')
        ids = json.loads(raw_ids)
    else:
        ids = identifiers(where)
        manifest = dict(source=SOURCE, query_endpoint=QUERY, where=where,
                        started_at=datetime.now(timezone.utc).isoformat(), source_count=len(ids),
                        ids_sha256=write_json(ids_path, ids), batch_size=BATCH_SIZE,
                        status='collecting', accepted=0, excluded=0, batches={})
        write_json(manifest_path, manifest)
    downloaded = 0
    manifest.setdefault('quarantined', 0)
    for offset in range(0, len(ids), BATCH_SIZE):
        key = str(offset)
        target = directory/f'{offset:07d}.geojson'
        if key in manifest['batches']:
            if not target.is_file() or sha256(target.read_bytes()).hexdigest() != manifest['batches'][key]['sha256']:
                raise ValueError('Cached batch hash mismatch')
            continue
        if max_batches and downloaded >= max_batches:
            break
        requested = ids[offset:offset+BATCH_SIZE]
        raw = source_query(dict(where=where, objectIds=','.join(map(str, requested)),
                                outFields=FIELDS, returnGeometry='true', outSR=4326,
                                orderByFields='OBJECTID ASC', resultRecordCount=1000))
        batch = normalise_batch(raw, requested)
        digest = write_json(target, batch)
        accepted, excluded = len(batch['features']), len(batch['excluded_ids'])
        quarantine = len(batch['quarantined_features'])
        manifest['batches'][key] = dict(sha256=digest, accepted=accepted, excluded=excluded, quarantined=quarantine)
        manifest['accepted'] += accepted
        manifest['excluded'] += excluded
        manifest['quarantined'] += quarantine
        write_json(manifest_path, manifest)
        downloaded += 1
        print(f"Captured {manifest['accepted']}; excluded {manifest['excluded']}; quarantined {manifest['quarantined']}; source {len(ids)}", flush=True)
    if len(manifest['batches']) == (len(ids)+BATCH_SIZE-1)//BATCH_SIZE and manifest['status'] != 'complete':
        current_ids = identifiers(where)
        if sha256(encode(current_ids)).hexdigest() != manifest['ids_sha256']:
            manifest['status'] = 'source_changed'
            write_json(manifest_path, manifest)
            raise ValueError('Source identifiers changed; partial archive retained')
        manifest.update(status='complete', finished_at=datetime.now(timezone.utc).isoformat())
        write_json(manifest_path, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'data/planning/binh-phuoc-parcels')
    parser.add_argument('--max-batches', type=int, default=1, help='0: all remaining; default: one bounded test batch')
    args = parser.parse_args()
    result = download(args.output, args.max_batches)
    print(json.dumps({k: result[k] for k in ('status', 'source_count', 'accepted', 'excluded')}))


if __name__ == '__main__':
    main()

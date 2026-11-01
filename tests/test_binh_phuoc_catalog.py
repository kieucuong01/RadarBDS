from copy import deepcopy
import json
import sqlite3

from flask import Flask
import pytest

from scripts import build_binh_phuoc_catalog as builder
from scripts.capture_binh_phuoc_parcels import write_json, normalise_batch
from services.planning_binh_phuoc_catalog import load_catalog
from services.planning_dongnai_parcels import DongNaiParcels, RegionalParcels, SOURCE, QUERY, ID_OFFSET


@pytest.fixture
def archive(tmp_path):
    ids = [49268, 49269]
    row = dict(attributes=dict(OBJECTID=49268, SoTo='10', SoThua='281', DienTich=31.5,
                               MaPhuongXa='25201', MaQuanHuyen='689', Owner='PRIVATE'),
               geometry=dict(rings=[[[106.89, 11.53], [106.8901, 11.53],
                                    [106.8901, 11.5301], [106.89, 11.5301], [106.89, 11.53]]]))
    unknown = deepcopy(row)
    unknown['attributes'].update(OBJECTID=49269, MaPhuongXa='99999')
    batch = normalise_batch(dict(spatialReference=dict(wkid=4326), features=[row, unknown]), ids)
    digest = write_json(tmp_path/'0000000.geojson', batch)
    manifest = dict(status='complete', source=SOURCE, query_endpoint=QUERY,
                    where=DongNaiParcels().all_where, source_count=2,
                    ids_sha256=write_json(tmp_path/'identifiers.json', ids), batch_size=500,
                    accepted=1, excluded=1, quarantined=1, finished_at='2026-11-02T00:00:00Z',
                    batches={'0': dict(sha256=digest, accepted=1, excluded=1, quarantined=1)})
    write_json(tmp_path/'manifest.json', manifest)
    return tmp_path


def test_verified_catalog_reads_original_corners_and_never_publishes_quarantine(archive):
    result = builder.build(archive)
    catalog = load_catalog(archive)
    feature = catalog.feature(ID_OFFSET+49268)
    assert feature['properties']['sheet'] == '10'
    assert catalog.search('bp-689-25201', '10', '281') == ([feature], 1)
    assert catalog.point(106.89005, 11.53005) == [feature]
    assert catalog.cell((106.8899, 11.5299, 106.8902, 11.5302)) == ([feature], 1)
    assert catalog.feature(ID_OFFSET+49269) is None
    assert 'PRIVATE' not in json.dumps(feature)
    assert result['accepted']+result['excluded'] == result['source_count'] == 2
    assert feature['geometry']['coordinates'][0][1] == [106.8901, 11.53]


def test_incomplete_or_corrupt_capture_preserves_previous_publication(archive):
    builder.build(archive)
    published = (archive/'catalog.json').read_bytes()
    batch = archive/'0000000.geojson'
    batch.write_bytes(batch.read_bytes()+b' ')
    with pytest.raises(ValueError, match='hash mismatch'):
        builder.build(archive)
    assert (archive/'catalog.json').read_bytes() == published
    assert load_catalog(archive).feature(ID_OFFSET+49268)
    manifest = json.loads((archive/'manifest.json').read_bytes())
    manifest['status'] = 'collecting'
    write_json(archive/'manifest.json', manifest)
    with pytest.raises(ValueError, match='Incomplete'):
        builder.build(archive)
    assert (archive/'catalog.json').read_bytes() == published


def test_snapshot_hash_tampering_fails_closed(archive):
    publication = builder.build(archive)
    index = archive/f"parcels-{publication['sha256'][:16]}.sqlite"
    with index.open('r+b') as stream:
        stream.seek(100); stream.write(b'TAMPER')
    with pytest.raises(ValueError, match='hash mismatch'):
        load_catalog(archive)


def administrative_capture(archive, target='bp-689-25201', west=106.889):
    rows = []
    for key, ref in DongNaiParcels().by_area.items():
        w, s = (west, 11.529) if key == target else (106.3, 12.2)
        rows.append(dict(attributes=dict(MaPhuongXa=ref['code'], MaQuanHuyen=ref['district'],
                                         TenXa=ref['ward'], TenHuyen=ref['city']),
                         geometry=dict(rings=[[[w,s],[w+.002,s],[w+.002,s+.002],[w,s+.002],[w,s]]])))
    path = archive/'admin.json'
    write_json(path, dict(spatialReference=dict(wkid=4326), features=rows))
    return path


def test_unknown_code_requires_unique_full_polygon_containment_in_same_district(archive):
    path = administrative_capture(archive)
    result = builder.build(archive, path)
    assert result['accepted'] == 2 and result['recovered_localities'] == 1
    assert result['excluded'] == result['quarantined'] == 0
    feature = load_catalog(archive).feature(ID_OFFSET+49269)
    assert feature['properties']['area_id'] == 'bp-689-25201'
    assert feature['properties']['source_ward_code'] == '99999'
    assert feature['properties']['membership_method'] == 'official_admin_full_containment'
    # Crossing a boundary or matching another district never guesses a locality.
    result = builder.build(archive, administrative_capture(archive, west=106.89005))
    assert result['recovered_localities'] == 0
    result = builder.build(archive, administrative_capture(archive, target='bp-688-25216'))
    assert result['recovered_localities'] == 0


def test_partial_admin_capture_cannot_promote_unknown_localities(archive):
    path = administrative_capture(archive)
    data = json.loads(path.read_bytes());data['features'].pop()
    write_json(path, data)
    with pytest.raises(ValueError, match='Incomplete administrative'):
        builder.build(archive, path)


def test_snapshot_routes_and_shared_cells_work_without_dongnai_requests(archive, monkeypatch):
    from services.planning_parcel_catalog import install_catalog
    from services.planning_parcel_tiles import install as install_cells
    builder.build(archive)
    # A separate minimal historic-HCM index exercises the real two-catalogue routes.
    base = archive/'base.sqlite'
    with sqlite3.connect(base) as conn:
        conn.executescript('''CREATE TABLE areas(code TEXT PRIMARY KEY, metadata TEXT);
            CREATE TABLE parcels(id INTEGER PRIMARY KEY, area TEXT, feature TEXT);
            CREATE VIRTUAL TABLE bounds USING rtree(id, west, east, south, north);''')
        conn.execute('INSERT INTO areas VALUES (?,?)', ('25765', json.dumps(dict(
            area_id='25765', code='25765', ward='Tân An', city='Thủ Dầu Một',
            count=0, excluded_count=0, sample_id=1))))
    def forbidden(*args, **kwargs):
        raise AssertionError('Local Bình Phước must not query upstream GIS')
    monkeypatch.setattr(DongNaiParcels, '_query', forbidden)
    app = Flask(__name__)
    catalog, expanded = install_catalog(app, base, expanded=True, supplemental=archive)
    assert not expanded.needs_viewport((106.8899, 11.5299, 106.8902, 11.5302), catalog.areas)
    install_cells(app, catalog, expanded, archive/'cache', 'snapshot-test')
    client = app.test_client()
    config = client.get('/local-planning/parcels/config.json').json
    area = next(a for a in config['areas'] if a.get('area_id') == 'bp-689-25201')
    assert area['count'] == 1 and config['count'] == 1
    empty_area = next(a for a in config['areas'] if a.get('area_id', '').startswith('bp-') and not a['count'])
    assert client.get('/local-planning/parcels/sample.json?area='+empty_area['area_id']).status_code == 404
    assert client.get('/local-planning/parcels/search.json?area=bp-689-25201&sheet=10&parcel=281').json['matched'] == 1
    assert client.get('/local-planning/parcels/viewport.json?bbox=106.8899,11.5299,106.8902,11.5302').json['matched'] == 1
    assert client.get(f'/api/planning/parcel-original/snapshot-test/{ID_OFFSET+49268}.json').json['id'] == ID_OFFSET+49268
    from math import asinh, tan, radians, pi
    x = int((106.89005+180)/360*2**17)
    y = int((1-asinh(tan(radians(11.53005)))/pi)/2*2**17)
    cell = client.get(f'/api/planning/parcel-cells/snapshot-test/snapshot/{x}/{y}.json')
    assert cell.status_code == 200 and cell.json['needs_live'] is False
    assert [f['id'] for f in cell.json['features']] == [ID_OFFSET+49268]

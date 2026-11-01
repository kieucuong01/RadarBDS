import json
from copy import deepcopy

import pytest
import requests

from scripts import capture_binh_phuoc_parcels as capture


class Source:
    def __init__(self):
        self.ids = [49268, 49269, 49270, 49271, 49272]
        self.batches = []
        self.fail = False
        self.duplicate = False
        self.invalid = False
        self.unverified = False

    def __call__(self, params):
        if params.get('returnCountOnly'):
            return {'count': len(self.ids)}
        if params.get('returnIdsOnly'):
            return {'objectIds': self.ids}
        ids = list(map(int, params['objectIds'].split(',')))
        self.batches.append(ids)
        assert params['outFields'] == 'OBJECTID,SoTo,SoThua,DienTich,MaPhuongXa,MaQuanHuyen'
        if self.fail:
            raise RuntimeError('temporary source failure')
        rows = []
        for identifier in ids:
            row = {'attributes': {'OBJECTID': identifier, 'SoTo': '10', 'SoThua': str(identifier),
                                 'DienTich': 31.5, 'MaPhuongXa': '25201', 'MaQuanHuyen': '689',
                                 'TenChuSoHuu': 'PRIVATE'},
                   'geometry': {'rings': [[[106.89, 11.53], [106.8901, 11.53],
                                          [106.8901, 11.5301], [106.89, 11.5301], [106.89, 11.53]]]}}
            if self.invalid and identifier == self.ids[0]:
                row['geometry'] = None
            if self.unverified and identifier == self.ids[0]:
                row['attributes']['MaPhuongXa'] = '99999'
            rows.append(row)
        if self.duplicate:
            rows[-1] = deepcopy(rows[0])
        return {'spatialReference': {'wkid': 4326}, 'features': rows}


def configure(monkeypatch):
    source = Source()
    monkeypatch.setattr(capture, 'source_query', source)
    monkeypatch.setattr(capture, 'BATCH_SIZE', 2)
    monkeypatch.setattr(capture.time, 'sleep', lambda *_: None)
    return source


def test_resumes_only_missing_batches_and_strips_private_fields(tmp_path, monkeypatch):
    source = configure(monkeypatch)
    assert capture.download(tmp_path, max_batches=1)['status'] == 'collecting'
    assert source.batches == [[49268, 49269]]
    result = capture.download(tmp_path, max_batches=0)
    assert result['status'] == 'complete'
    assert source.batches == [[49268, 49269], [49270, 49271], [49272]]
    assert result['accepted'] == 5 and result['excluded'] == 0
    assert all('PRIVATE' not in p.read_text() for p in tmp_path.glob('*.geojson'))
    capture.download(tmp_path, max_batches=0)
    assert len(source.batches) == 3


def test_failed_batch_keeps_previous_checkpoint(tmp_path, monkeypatch):
    source = configure(monkeypatch)
    capture.download(tmp_path, max_batches=1)
    before = (tmp_path/'manifest.json').read_bytes()
    source.fail = True
    with pytest.raises(RuntimeError):
        capture.download(tmp_path, max_batches=1)
    assert (tmp_path/'manifest.json').read_bytes() == before
    source.fail = False
    assert capture.download(tmp_path, max_batches=0)['status'] == 'complete'


def test_truncated_or_duplicate_batch_is_not_recorded_as_success(tmp_path, monkeypatch):
    source = configure(monkeypatch)
    source.duplicate = True
    with pytest.raises(ValueError):
        capture.download(tmp_path, max_batches=1)
    manifest = json.loads((tmp_path/'manifest.json').read_text())
    assert not manifest['batches']


def test_invalid_geometry_has_explicit_exclusion_not_repaired_corners(tmp_path, monkeypatch):
    source = configure(monkeypatch)
    source.invalid = True
    result = capture.download(tmp_path, max_batches=0)
    assert result['accepted'] == 4 and result['excluded'] == 1
    batch = json.loads((tmp_path/'0000000.geojson').read_text())
    assert batch['excluded_ids'] == [49268]


def test_corrupted_cached_file_stops_resume(tmp_path, monkeypatch):
    configure(monkeypatch)
    capture.download(tmp_path, max_batches=1)
    (tmp_path/'0000000.geojson').write_text('{}')
    with pytest.raises(ValueError, match='hash'):
        capture.download(tmp_path, max_batches=0)


def test_unknown_locality_is_quarantined_without_guessing_names_or_losing_geometry(tmp_path, monkeypatch):
    source = configure(monkeypatch)
    source.unverified = True
    result = capture.download(tmp_path, max_batches=0)
    assert result['accepted'] == 4 and result['excluded'] == result['quarantined'] == 1
    batch = json.loads((tmp_path/'0000000.geojson').read_text())
    assert batch['excluded_reasons']['49268'] == 'unverified_source_locality'
    feature = batch['quarantined_features'][0]
    assert feature['geometry']['type'] == 'Polygon'
    assert feature['properties']['locality_verified'] is False
    assert feature['properties']['source_attributes']['MaPhuongXa'] == '99999'
    assert 'PRIVATE' not in json.dumps(batch)


def test_unknown_locality_cannot_bypass_the_crs_guard(tmp_path, monkeypatch):
    source = configure(monkeypatch)
    source.unverified = True
    def wrong_crs(params):
        result = source(params)
        if 'features' in result:
            result['spatialReference'] = {'wkid': 3857}
        return result
    monkeypatch.setattr(capture, 'source_query', wrong_crs)
    with pytest.raises(ValueError, match='coordinate system'):
        capture.download(tmp_path, max_batches=1)


def test_transient_reads_retry_only_twice(monkeypatch):
    attempts = []
    def read(params):
        attempts.append(params)
        if len(attempts) < 3:
            raise requests.ReadTimeout()
        return {'count': 10}
    monkeypatch.setattr(capture, '_source_query_once', read)
    monkeypatch.setattr(capture.time, 'sleep', lambda *_: None)
    assert capture.source_query({}) == {'count': 10}
    assert len(attempts) == 3


@pytest.mark.parametrize('status', [403, 419, 429])
def test_access_and_rate_denials_do_not_retry_or_change_routes(monkeypatch, status):
    calls = []
    def denied(params):
        calls.append(params)
        response = requests.Response()
        response.status_code = status
        raise requests.HTTPError(response=response)
    monkeypatch.setattr(capture, '_source_query_once', denied)
    with pytest.raises(requests.HTTPError):
        capture.source_query({})
    assert len(calls) == 1

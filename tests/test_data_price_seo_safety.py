"""Additional provenance and reader-copy regressions for the resumed foundation."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_private_packet_preserves_reproducible_inputs_without_unneeded_pii(monkeypatch, tmp_path):
    from tests.test_data_price_seo import row
    spec = importlib.util.spec_from_file_location('refresh_safety', ROOT/'scripts/refresh_data_price_seo.py')
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    today = script.datetime.now(script.TZ).date().isoformat()
    rows = [row(i, last_seen_at=today, contact_phone='0909999999', title='UNNEEDED_PRIVATE') for i in range(15)]
    rows += [row(99, review_hidden=1, last_seen_at=today)]
    monkeypatch.setattr(script, 'read_current_rows', lambda *args: rows)
    monkeypatch.setattr(script, 'source_commit', lambda: 'a'*40)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://not-used')
    result = script.refresh(tmp_path)
    private = json.loads((tmp_path/'private'/f"{result['snapshot_id']}.json").read_text())
    records = private.get('cohort_records')
    assert records is not None, 'A hash plus IDs cannot reproduce frozen statistics after live rows change'
    assert len(records) == 15
    assert all(r['price_ty'] == 2 and r['price_per_m2'] == 20 and r['area_m2'] == 100 and r['last_seen_at'] == today for r in records)
    assert private['cohort_input_sha256'] == script.digest(records)
    assert private['generated_at'] and private['data_as_of'] == today
    assert '0909999999' not in json.dumps(private) and 'UNNEEDED_PRIVATE' not in json.dumps(private)
    public = json.loads(Path(result['path']).read_text())
    assert 'cohort_records' not in public


def test_reader_copy_does_not_expose_internal_field_syntax(monkeypatch, tmp_path):
    from tests.test_data_price_seo import make_app
    app, _ = make_app(monkeypatch, tmp_path)
    html = app.test_client().get('/gia-dat/phu-loi').get_data(as_text=True)
    assert 'is_active=1' not in html
    assert 'tin còn hoạt động trong mẫu' in html

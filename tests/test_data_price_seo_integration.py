"""Integration/CLI contracts for the data-price foundation (no production writes)."""
from datetime import date
import importlib.util
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]


def publisher():
    spec=importlib.util.spec_from_file_location('refresh_data_price',ROOT/'scripts/refresh_data_price_seo.py')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_refresh_freezes_actual_readonly_cohort_and_separate_private_provenance(monkeypatch,tmp_path):
    from tests.test_data_price_seo import row
    script=publisher()
    now=script.datetime.now(script.TZ)
    rows=[row(i,last_seen_at=now.date().isoformat()) for i in range(15)]
    monkeypatch.setattr(script,'read_current_rows',lambda database_url,as_of:rows)
    monkeypatch.setattr(script,'source_commit',lambda:'a'*40)
    monkeypatch.setenv('DATABASE_URL','postgresql://not-used')
    result=script.refresh(tmp_path)
    assert result['status']=='FROZEN'
    assert result['read_only'] is True
    assert result['scopes']['phu-loi']['sample_count']==15
    snapshot=json.loads(Path(result['path']).read_text())
    private=json.loads((tmp_path/'private'/f"{snapshot['snapshot_id']}.json").read_text())
    assert private['snapshot_sha256']==snapshot['sha256']
    assert private['scope_listing_ids']['phu-loi']==list(range(1,16))
    assert private['cohort_input_sha256']
    assert 'scope_listing_ids' not in snapshot
    assert (tmp_path/'private').stat().st_mode & 0o777 == 0o700
    second=script.refresh(tmp_path)
    assert second['status']=='FROZEN'
    assert len(list(tmp_path.glob('20*.json'))) in (1,2)


def test_refresh_failure_does_not_replace_existing_latest(monkeypatch,tmp_path):
    script=publisher()
    (tmp_path/'latest.json').write_text('original-pointer')
    monkeypatch.setenv('DATABASE_URL','postgresql://not-used')
    def failed(*args):
        raise RuntimeError('DB unavailable')
    monkeypatch.setattr(script,'read_current_rows',failed)
    with pytest.raises(RuntimeError,match='DB unavailable'):
        script.refresh(tmp_path)
    assert (tmp_path/'latest.json').read_text()=='original-pointer'


def test_actual_flask_app_registers_new_price_route_without_overwriting_existing_owner():
    import app as radar_app
    rules={rule.rule for rule in radar_app.app.url_map.iter_rules()}
    assert '/gia-dat/<slug>' in rules
    assert '/binh-duong/<path:location_slug>' in rules


def test_actual_sitemap_includes_only_validated_price_entries(monkeypatch):
    import app as radar_app
    from services import data_price_seo
    monkeypatch.setattr(data_price_seo,'sitemap_entries',lambda:[dict(path='/gia-dat/phu-loi',updated_at='2026-10-21')])
    monkeypatch.setattr(radar_app._public_content_repository,'list_published',lambda **kwargs:[])
    with radar_app.app.test_request_context('/sitemap.xml'):
        xml=radar_app.sitemap_xml().get_data(as_text=True)
    assert xml.count('<loc>https://radarbds.vn/gia-dat/phu-loi</loc>')==1
    assert '<lastmod>2026-10-21</lastmod>' in xml
    assert '/gia-dat/Other' not in xml

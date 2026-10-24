from copy import deepcopy

from config.seo_pages import SEO_PAGES


def test_legacy_small_sample_has_no_false_trend_or_selected_percentages():
    from services.report_buyer import prepare_buyer_report
    raw = SEO_PAGES['bao-cao/tan-an-thang-09-2026']
    original = deepcopy(raw)
    page = prepare_buyer_report(raw, pages=SEO_PAGES)
    assert raw == original
    assert page['buyer']['segments'][0]['n'] == 7
    assert page['buyer']['segments'][0]['median_display'] == 'Chưa đủ mẫu'
    assert '16.4%' not in str(page['report']['indicators'])
    assert '100.0%' not in str(page['report']['under_value'])
    assert page['buyer']['budget_snapshot_available'] is False
    assert page['buyer']['budgets'][0]['href'].startswith('/?')
    assert 'source=facebook' in page['buyer']['budgets'][0]['href']
    assert 'price_max=1.5' in page['buyer']['budgets'][0]['href']
    assert page['report']['under_value']['links'] == original['report']['under_value']['links']


def test_master_uses_each_segment_n_and_never_weighted_median_as_pooled_price():
    from services.report_buyer import prepare_buyer_report
    raw = SEO_PAGES['bao-cao/bds-binh-duong-thang-09-2026']
    page = prepare_buyer_report(raw, pages=SEO_PAGES)
    assert len(page['buyer']['comparisons']) == 13
    tan_an = next(r for r in page['buyer']['comparisons'] if r['scope'] == 'Tân An')
    assert tan_an['land_n'] == 7
    assert tan_an['land_price'] == 'Chưa đủ mẫu'
    assert all(m['value'] != '21.5 tr/m²' for m in page['report']['metrics'])


def test_web_renders_unified_buyer_flow_and_historical_data_limits():
    import app
    html = app.app.test_client().get('/bao-cao/tan-an-thang-09-2026').get_data(as_text=True)
    for section in ['report-buyer-summary', 'report-budget', 'report-price-ranges', 'report-checklist']:
        assert f'id="{section}"' in html
    assert '100.0%' not in html
    assert 'Chưa đủ mẫu' in html
    assert 'chưa lưu phân bố' in html.lower()
    assert 'Đặt cọc' in html or 'đặt cọc' in html


def test_new_snapshot_has_budget_facts_and_correct_price_distribution():
    from services.report_buyer import prepare_buyer_report
    from services.report_buyer_snapshot import build_buyer_snapshot
    raw = deepcopy(SEO_PAGES['bao-cao/tan-an-thang-09-2026'])
    raw['report']['buyer_snapshot'] = build_buyer_snapshot([
        dict(id=i+1, source='facebook', tx_type='ban', ward='Tân An', property_type='dat_nen',
             area_m2=100, price_ty=1+i/10, price_per_m2=10+i) for i in range(20)
    ], period_start='2026-09-01', period_end='2026-10-01', generated_at='2026-10-01T08:00:00+07:00')
    page = prepare_buyer_report(raw, pages=SEO_PAGES)
    assert page['buyer']['budget_snapshot_available'] is True
    assert page['buyer']['segments'][0]['n'] == 20
    assert page['buyer']['segments'][0]['median_display'] != 'Chưa đủ mẫu'


def test_publisher_preserves_published_reports_and_only_enriches_new_capture():
    from pathlib import Path
    source = Path('scripts/enhance_monthly_report_rich.py').read_text(encoding='utf-8')
    assert 'buyer_snapshot' in source
    assert 'generated_at' in source
    assert 'preserve_published_snapshot' in source


def test_enhancer_never_requeries_a_published_snapshot(monkeypatch):
    from scripts import enhance_monthly_report_rich as enhancer
    monkeypatch.setattr(enhancer, 'query_trends', lambda *_: (_ for _ in ()).throw(AssertionError('historical query')))
    page = deepcopy(SEO_PAGES['bao-cao/tan-an-thang-09-2026'])
    assert enhancer.update_ward_page(page, 'Tân An', 9, 2026) == page
    master = deepcopy(SEO_PAGES['bao-cao/bds-binh-duong-thang-09-2026'])
    assert enhancer.update_master_page(master, {}, 9, 2026) == master


def test_trend_history_is_read_from_frozen_snapshots_without_backfill(monkeypatch):
    from scripts import enhance_monthly_report_rich as enhancer
    calls = []
    def current(ward, start, end):
        calls.append((start, end))
        return dict(total=20, hot=0, dropped=0, signals=0, by_type={})
    monkeypatch.setattr(enhancer, 'query_ward_stats', current)
    from services.report_buyer_snapshot import build_buyer_snapshot
    facts = build_buyer_snapshot([], period_start='2026-09-01', period_end='2026-10-01',
                                 generated_at='2026-10-01T08:00:00+07:00')
    result = enhancer.query_trends('Tân An', 9, 2026, facts)
    assert calls == [('2026-09-01','2026-10-01')]
    assert result[0]['row']['total'] == 'Chưa lưu'
    assert result[-1]['row']['total'] == '0'


def test_trend_uses_same_quality_cohort_and_never_invents_history_counts(monkeypatch):
    from scripts import enhance_monthly_report_rich as enhancer
    from services.report_buyer_snapshot import build_buyer_snapshot
    def rows():
        return [dict(id=i+1, source='facebook', tx_type='ban', ward='Phú Mỹ',
                     property_type='dat_nen', area_m2=100, price_ty=2, price_per_m2=20)
                for i in range(20)]
    items = rows()
    for row in items[:13]:
        row['extraction_quality_flags'] = 'ambiguous_price_text'
    facts = build_buyer_snapshot(items, period_start='2026-09-01', period_end='2026-10-01',
                                 generated_at='2026-10-01T08:00:00+07:00')
    old = build_buyer_snapshot(rows(), period_start='2026-08-01', period_end='2026-09-01',
                               generated_at='2026-09-01T08:00:00+07:00')
    monkeypatch.setattr(enhancer, 'query_ward_stats', lambda *_: dict(total=20, by_type={
        'dat_nen': dict(count=20, median_m2=20)}, hot=0, dropped=0, signals=0))
    monkeypatch.setattr(enhancer, 'load_seo_pages', lambda *_: {
        'bao-cao/phu-my-thang-08-2026': {'report': {'buyer_snapshot': old, 'price_drop_count': 3}}})
    trends = enhancer.query_trends('Phú Mỹ', 9, 2026, facts)
    assert trends[-1]['row']['dat_nen_count'] == '7'
    assert trends[-1]['stats']['by_type']['dat_nen']['median_m2'] is None
    assert trends[-2]['row']['dropped'] == '3'
    assert trends[-2]['row']['hot'] == 'Chưa lưu'


def test_ward_comparisons_do_not_treat_other_property_types_as_places():
    from services.report_buyer import prepare_buyer_report
    page = prepare_buyer_report(SEO_PAGES['bao-cao/phu-my-thang-09-2026'], pages=SEO_PAGES)
    rows = page['buyer']['comparisons']
    assert len(rows) == 4
    assert rows[0]['scope'] == 'Phú Mỹ' and rows[0]['land_n'] == 24
    assert not any(r['scope'] in {'Nhà trọ','Đất nền','Nhà đất'} for r in rows)


def test_invalid_snapshot_is_not_rendered_as_known_historical_budget():
    from services.report_buyer import prepare_buyer_report
    raw = deepcopy(SEO_PAGES['bao-cao/tan-an-thang-09-2026'])
    raw['report']['buyer_snapshot'] = dict(schema_version=1, qualified_count=100, segments=[], budgets=[], comparisons=[])
    assert prepare_buyer_report(raw, pages=SEO_PAGES)['buyer']['budget_snapshot_available'] is False


def test_new_master_with_zero_sale_prices_still_has_a_valid_empty_snapshot(monkeypatch):
    from contextlib import nullcontext
    from scripts import enhance_monthly_report_rich as enhancer
    from services.report_buyer_snapshot import build_buyer_snapshot
    page = deepcopy(SEO_PAGES['bao-cao/bds-binh-duong-thang-09-2026'])
    page['report']['generated_at'] = '2026-10-01T08:00:00+07:00'
    wards = {ward: {'report': dict(raw_listing_count=0, basis_count=0,
             actionable_signal_count=0, price_drop_count=0, data_contract_version='test', metrics=[])}
             for ward in enhancer.TDM_WARDS}
    monkeypatch.setattr(enhancer, 'get_conn', lambda: nullcontext(None))
    monkeypatch.setattr(enhancer, 'query_buyer_snapshot', lambda *a, **kw:
        build_buyer_snapshot([], period_start=a[2], period_end=a[3], generated_at=kw['generated_at']))
    result = enhancer.update_master_page(page, wards, 9, 2026)
    assert result['report']['buyer_snapshot']['qualified_count'] == 0
    assert result['report']['basis_count'] == 0


def test_monthly_live_verifier_accepts_all_new_buyer_pages(monkeypatch):
    from types import SimpleNamespace
    import app
    from scripts import radar_monthly_report_publish as publisher
    client = app.app.test_client()
    monkeypatch.setattr(app, 'pdf_download_href', lambda page: page['path'] + '/pdf?v=test')
    monkeypatch.setattr(publisher, 'http_html', lambda path:
        ('200', client.get(path).get_data(as_text=True)))
    monkeypatch.setattr(publisher, 'run', lambda *a, **kw:
        SimpleNamespace(stdout=client.get('/sitemap.xml').get_data(as_text=True)))
    assert publisher.verify_live(9, 2026) == 0


def test_new_ward_generation_uses_qualified_counts_even_with_canonical_flags(monkeypatch):
    from contextlib import nullcontext
    from scripts import enhance_monthly_report_rich as enhancer
    from services.report_buyer_snapshot import build_buyer_snapshot
    from services.report_buyer import prepare_buyer_report
    page = deepcopy(SEO_PAGES['bao-cao/tan-an-thang-09-2026'])
    page['report']['generated_at'] = '2026-10-01T08:00:00+07:00'
    canonical = dict(raw_total=30, basis_count=20, total=20, hot=1, dropped=3,
                     signals=2, actionable_signal_count=2, data_contract_version='test',
                     by_type={'dat_nen': dict(count=20, median_m2=20)})
    monkeypatch.setattr(enhancer, 'get_conn', lambda: nullcontext(None))
    monkeypatch.setattr(enhancer, 'query_ward_stats', lambda *_: deepcopy(canonical))
    monkeypatch.setattr(enhancer, 'query_valuation_records', lambda *_: [])
    for n in (0, 7, 20):
        items = [dict(id=i+1, source='facebook', tx_type='ban', ward='Tân An', property_type='dat_nen',
                      area_m2=100, price_ty=2, price_per_m2=20) for i in range(n)]
        facts = build_buyer_snapshot(items, period_start='2026-09-01', period_end='2026-10-01',
                                     generated_at='2026-10-01T08:00:00+07:00')
        monkeypatch.setattr(enhancer, 'query_buyer_snapshot', lambda *a, **kw: facts)
        result = enhancer.update_ward_page(deepcopy(page), 'Tân An', 9, 2026)
        assert result['report']['trend_rows'][-1]['dat_nen_count'] == str(n)
        prepared = prepare_buyer_report(result, pages=SEO_PAGES)
        assert prepared['buyer']['qualified_count'] == n
        if n == 0:
            assert prepared['buyer']['examples'] == []
        else:
            assert 'chọn theo nhóm ngân sách' in prepared['report']['under_value']['body'][0]
        if n < 15:
            assert prepared['report']['trend_rows'][-1]['dat_nen_price'] == 'Chưa đủ mẫu'

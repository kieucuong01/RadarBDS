from services.listing_evidence import build_listing_evidence


def test_evidence_uses_basis_of_displayed_mos_and_not_other_models_sample():
    evidence = build_listing_evidence({
        'fair_ppm2_old': 30, 'fair_ppm2_new': 25,
        'fair_ppm2_display': 25, 'valuation_actual_ppm2': 20,
        'evidence_old_samples': 80, 'evidence_new_samples': 12,
        'evidence_old_computed_at': '2026-10-01T00:00:00Z',
        'evidence_new_computed_at': '2026-10-04T00:00:00Z',
    }, None)
    assert '20.0%' in evidence['reason']
    assert evidence['sample_count'] == 12
    assert evidence['valued_at'] == '04/10/2026 07:00'
    assert evidence['thin_sample'] is True
    assert 'giá giao dịch' in evidence['method_note']


def test_missing_evidence_does_not_invent_samples_dates_or_legal_verification():
    evidence = build_listing_evidence({'has_so': True}, None)
    assert evidence['sample_count'] is None
    assert evidence['valued_at'] is None
    assert 'Chưa đủ' in evidence['reason']
    assert any('giấy tờ' in item for item in evidence['unverified'])
    assert any('còn bán' in item for item in evidence['unverified'])
    assert any('Vị trí' in item for item in evidence['unverified'])


def test_invalid_numbers_and_dates_never_become_positive_evidence():
    evidence = build_listing_evidence({
        'fair_ppm2_display': float('nan'), 'valuation_actual_ppm2': 20,
        'evidence_old_samples': -3, 'crawled_at': 'not-a-date',
    }, None)
    assert evidence['sample_count'] is None
    assert evidence['crawled_at'] is None
    assert 'nan' not in evidence['reason'].lower()


def test_above_reference_price_is_not_called_cheap_and_text_is_allowlisted():
    evidence = build_listing_evidence({
        'fair_ppm2_old': 20, 'fair_ppm2_display': 20,
        'valuation_actual_ppm2': 25, 'evidence_old_samples': 45,
        'source_quality_flags': 'area_dimension_conflict,https://private.example/0901234567',
    }, {'precision': 'road'})
    assert 'cao hơn' in evidence['reason']
    assert any('diện tích' in item for item in evidence['unverified'])
    assert 'private.example' not in str(evidence)
    assert '0901234567' not in str(evidence)


def test_exact_map_does_not_imply_verified_title_or_sale():
    evidence = build_listing_evidence({}, {'precision': 'exact'})
    assert not any(item.startswith('Vị trí') for item in evidence['unverified'])
    assert any('giấy tờ' in item for item in evidence['unverified'])
    assert any('còn bán' in item for item in evidence['unverified'])


def test_detail_route_renders_evidence_for_guest_and_escapes_source_text(monkeypatch):
    import app as app_module

    listing = {
        'id': 42, 'title': 'Lô đối chiếu <script>alert(1)</script>',
        'description': 'Nội dung tin', 'ward': 'Phú Lợi', 'source': 'facebook',
        'price_ty': 2, 'area_m2': 100, 'price_per_m2': 20,
        'fair_ppm2': 25, 'fair_ppm2_display': 25, 'fair_ppm2_old': 25,
        'valuation_actual_ppm2': 20, 'mos_pct': 20,
        'evidence_old_samples': 40,
        'evidence_old_computed_at': '2026-10-04T00:00:00Z',
    }
    monkeypatch.setattr(app_module, 'load_listing_detail', lambda *args, **kwargs: {
        'listing': listing, 'images': [], 'history': [], 'map_location': None,
    })
    response = app_module.app.test_client().get('/listing/42')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Bằng chứng định giá' in html
    assert '40 mẫu' in html
    assert '04/10/2026 07:00' in html
    assert 'Thông tin cần xác minh' in html
    assert '<script>alert(1)</script>' not in html
    assert html.index('Bằng chứng định giá') < html.index('Nguyên văn tin rao')

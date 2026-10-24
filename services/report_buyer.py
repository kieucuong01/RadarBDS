"""Pure presentation of saved report facts; no DB reads or historical backfills."""
from copy import deepcopy
import re
from urllib.parse import urlencode

from services.report_buyer_snapshot import BUDGETS, MIN_SAMPLES, TYPE_LABELS, valid_snapshot


def count(value):
    match = re.search(r'\d+', str(value or '').replace('.', '').replace(',', ''))
    return int(match.group()) if match else 0


def number(value):
    match = re.search(r'\d+(?:[.,]\d+)?', str(value or ''))
    return float(match.group().replace(',', '.')) if match else None


def fmt(value, unit=''):
    return 'Chưa đủ mẫu' if value is None else f'{value:,.2f}'.rstrip('0').rstrip('.').replace(',', '_').replace('.', ',').replace('_', '.') + unit


def dashboard(scope, **params):
    query = dict(tab='all', source='facebook', date_range='1m')
    if scope not in {'Thủ Dầu Một', 'Bến Cát'}:
        query['ward'] = scope
    query['city'] = 'BẾN CÁT' if scope == 'Bến Cát' else 'THỦ DẦU MỘT'
    query.update({k: v for k, v in params.items() if v is not None})
    return '/?' + urlencode(query)


def _legacy_segments(report):
    segments = []
    for pt, label in TYPE_LABELS.items():
        row = next((r for r in report.get('area_rows', []) if r.get('area') == label), {})
        metric = next((m for m in report.get('metrics', []) if label.lower() in m.get('label', '').lower()), {})
        n = count(row.get('new_listings') or metric.get('note'))
        if not row and not metric:
            continue
        value = number(row.get('median_price') or metric.get('value')) if n >= MIN_SAMPLES else None
        segments.append(dict(property_type=pt, label=label, n=n, ppm2={'median': value},
                             asking_ty={}, area_m2={}))
    return segments


def _segment_view(segment):
    result = deepcopy(segment)
    n = int(segment.get('n') or 0)
    eligible = n >= MIN_SAMPLES
    price = segment.get('ppm2', {})
    area = segment.get('area_m2', {})
    total = segment.get('asking_ty', {})
    result.update(median_display=fmt(price.get('median') if eligible else None, ' tr/m²'),
                  total_display=(fmt(total['median'], ' tỷ') if eligible and total.get('median') is not None
                                 else 'Chưa lưu tổng giá' if eligible else 'Chưa đủ mẫu'),
                  range_display=(fmt(price['p25']) + '–' + fmt(price['p75']) + ' tr/m²'
                                 if eligible and price.get('p25') is not None else 'Chưa lưu khoảng giá'),
                  area_display=(fmt(area['p25']) + '–' + fmt(area['p75']) + ' m²'
                                if eligible and area.get('p25') is not None else
                                'Chưa lưu khoảng diện tích' if eligible else 'Chưa đủ mẫu'),
                  median_value=price.get('median') if eligible else None)
    return result


def _scope(page):
    return page.get('scope_label') or str(page.get('map_label') or '').rsplit(' / ', 1)[-1] or 'Thủ Dầu Một'


def _period(page):
    match = re.search(r'-thang-(\d{2})-(\d{4})$', page.get('path', ''))
    return match.groups() if match else (page.get('report', {}).get('period'), '')


def _snapshot(page):
    saved = page.get('report', {}).get('buyer_snapshot') or {}
    mm, yyyy = _period(page)
    if not valid_snapshot(saved) or saved.get('period_start') != f'{yyyy}-{mm}-01':
        return {}
    scope = _scope(page)
    if scope not in {'Thủ Dầu Một', 'Bến Cát'} and any(r['scope'] != scope for r in saved['comparisons']):
        return {}
    return saved


def _saved_segments(page):
    facts = _snapshot(page)
    return facts['segments'] if facts else _legacy_segments(page.get('report') or {})


def _comparisons(page, pages, snapshot):
    saved = snapshot.get('comparisons', []) if snapshot else []
    result = []
    scopes = sorted({r['scope'] for r in saved})
    by_scope = {_scope(p): p for p in pages.values() if p.get('variant') == 'report' and
                _period(p) == _period(page) and _scope(p) not in {'Thủ Dầu Một', 'Bến Cát'}}
    if not saved:
        scopes = [r.get('area') for r in page['report'].get('area_rows', []) if r.get('area') in by_scope]
        if not scopes:
            scopes = [r.get('area') for r in page['report'].get('comparison_rows', []) if r.get('area') in by_scope]
    if _scope(page) not in {'Thủ Dầu Một', 'Bến Cát'}:
        ranked = sorted(by_scope, key=lambda name: max((r['n'] for r in _saved_segments(by_scope[name])
                                                       if r['property_type'] == 'dat_nen'), default=0), reverse=True)
        scopes = list(dict.fromkeys([_scope(page), *scopes, *ranked]))[:4]
    for scope in scopes:
        other = next((p for p in pages.values() if p.get('variant') == 'report'
                      and _period(p) == _period(page) and _scope(p) == scope), None)
        raw_segments = [r for r in saved if r['scope'] == scope]
        if not raw_segments and not (snapshot and scope == _scope(page)) and (other or scope == _scope(page)):
            raw_segments = _saved_segments(other or page)
        segments = [_segment_view(r) for r in raw_segments]
        land = next((s for s in segments if s['property_type'] == 'dat_nen'), {})
        house = next((s for s in segments if s['property_type'] == 'nha_dat'), {})
        source = (other or {}).get('report', {})
        result.append(dict(scope=scope, land_n=land.get('n', 0), house_n=house.get('n', 0),
                           land_price=land.get('median_display', 'Chưa đủ mẫu'),
                           house_price=house.get('median_display', 'Chưa đủ mẫu'),
                           land_value=land.get('median_value'),
                           basis_count=source.get('basis_count', sum(s['n'] for s in segments)),
                           href=(other or {}).get('path') or dashboard(scope),
                           current_href=dashboard(scope)))
    return result


def _safe_charts(page, segments, comparisons):
    charts = deepcopy(page.get('charts') or [])
    counts = {s['label']: s['n'] for s in segments}
    values = {s['label']: s['median_value'] for s in segments}
    trends = {r.get('month'): r for r in page['report'].get('trend_rows', [])}
    comparable = {r['scope']: r for r in comparisons}
    for chart in charts:
        key = chart['id']
        if key == 'price-trend-6m-chart':
            chart['title'] = 'Giá rao trung vị theo kỳ · chỉ hiện nhóm từ 15 mẫu'
            for dataset in chart.get('datasets', []):
                prefix = 'dat_nen' if 'Đất' in dataset.get('label', '') else 'nha_dat'
                dataset['data'] = [v if count(trends.get(label, {}).get(prefix + '_count')) >= MIN_SAMPLES else None
                                   for label, v in zip(chart.get('labels', []), dataset.get('data', []))]
        elif key == 'ward-price-chart':
            chart['title'] = 'Giá rao đất nền trung vị · n riêng cho từng phường'
            for dataset in chart.get('datasets', []):
                dataset['data'] = [comparable.get(label, {}).get('land_value') for label in chart.get('labels', [])]
        elif key == 'type-price-chart':
            chart['title'] = 'Giá rao trung vị theo loại hình · từ 15 mẫu'
            for dataset in chart.get('datasets', []):
                dataset['data'] = [values.get(label) for label in chart.get('labels', [])]
        elif key == 'type-dist-chart':
            chart['title'] = 'Mẫu đủ giá/m² theo loại hình · không phải toàn bộ tin thu thập'
        elif key == 'under-value-scatter-chart':
            chart['title'] = 'Mẫu tín hiệu đã tuyển chọn · không đại diện toàn thị trường'
    return [chart for chart in charts if any(value is not None for dataset in chart.get('datasets', [])
                                            for value in dataset.get('data', []))]


def prepare_buyer_report(raw_page, *, pages=None):
    page = deepcopy(raw_page)
    if page.get('variant') != 'report':
        return page
    report = page['report']
    scope = _scope(page)
    pages = pages or {}
    snapshot = _snapshot(page)
    segments = [_segment_view(s) for s in (snapshot.get('segments') if snapshot else _legacy_segments(report))]
    raw_count = int(report.get('raw_listing_count') or 0)
    basis = int(report.get('basis_count') or 0)
    signals = int(report.get('actionable_signal_count') or 0)
    warnings = []
    if not snapshot:
        warnings.append('Bản lịch sử chưa lưu phân bố ngân sách và khoảng P25–P75. Không dùng giá hiện tại để điền lại kỳ cũ.')
    if any(s['n'] < MIN_SAMPLES for s in segments):
        warnings.append('Phân khúc dưới 15 mẫu được ghi “Chưa đủ mẫu”; không kết luận giá tăng/giảm từ nhóm nhỏ.')
    displayed = sum(s['n'] for s in segments)
    if segments and not snapshot and basis != displayed:
        warnings.append(f'{basis} mẫu sau lọc; bảng đất nền/nhà đất có {displayed} mẫu đủ giá. Phần còn lại chưa đủ trường hoặc ngoài hai nhóm; chưa thể phân rã thêm từ bản đã lưu.')
    if not report.get('generated_at'):
        warnings.append('Bản cũ chưa tách ngày tính mô hình và ngày quan sát giá; mốc cuối tháng mô tả kỳ dữ liệu, không xác nhận mọi trường tại đúng ngày đó.')
    comparisons = _comparisons(page, pages, snapshot)
    budgets = []
    for low, high, label in BUDGETS:
        facts = [r for r in snapshot.get('budgets', []) if r['low'] == low]
        budgets.append(dict(label=label, n=sum(r['n'] for r in facts) if snapshot else None,
                            facts=[_segment_view(r) for r in facts],
                            href=dashboard(scope, price_min=low or None, price_max=high),
                            land_href=dashboard(scope, price_min=low or None, price_max=high, prop_type='dat_nen'),
                            house_href=dashboard(scope, price_min=low or None, price_max=high, prop_type='nha_dat')))
    examples = []
    for item in (snapshot.get('examples', []) if snapshot else report.get('featured_listings') or []):
        if re.fullmatch(r'/listing/\d+', str(item.get('href') or '')):
            title = re.sub(r'[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u200d]', '', item.get('title') or 'Mẫu tin đã lưu')
            title = re.sub(r'\s+', ' ', title).strip()[:160]
            segment = next((s for s in segments if s['label'] == item.get('type')), {})
            note = (f'Phân khúc {item.get("type", "này")} có n={segment.get("n", 0)} mẫu đủ giá. '
                    + (f'Mốc trung vị {segment["median_display"]}; chưa hiệu chỉnh theo vị trí, đường và hiện trạng.'
                       if segment.get('median_value') is not None else 'Chưa đủ mẫu để kết luận mặt bằng giá của phân khúc.'))
            examples.append(dict(href=item['href'], title=title,
                                 id=item['href'].rsplit('/', 1)[-1],
                                 image=item.get('image') if re.match(r'^(?:/(?!/)|https?://)', str(item.get('image') or '')) else None,
                                 type=item.get('type'), price=item.get('price'), area=item.get('area'),
                                 ppm2=item.get('price_per_m2'),
                                 reason=item.get('selection_note') or note))
    summary = [f'{raw_count:,} tin thu thập, {basis:,} mẫu sau điều kiện lọc của bản báo cáo. Tin thu thập có thể gồm đăng lại.',
               f'{signals} tín hiệu đã lưu để kiểm tra thêm; số lượng này không phải giao dịch đã chốt.']
    for s in segments:
        summary.append(f'{s["label"]}: {s["n"]} mẫu đủ giá/m². ' +
                       (f'Giá rao trung vị {s["median_display"]}.' if s['median_value'] is not None else
                        'Chưa đủ mẫu để kết luận mặt bằng giá hoặc mức thay đổi toàn phân khúc.'))
    if not segments:
        summary.append(f'So sánh {len(comparisons)} phường theo đúng loại hình và cỡ mẫu; không gộp các trung vị thành giá đại diện toàn khu.')
    buyer = dict(scope=scope, summary=summary, warnings=warnings, segments=segments,
                 comparisons=comparisons, budgets=budgets, budget_snapshot_available=bool(snapshot),
                 raw_count=raw_count, basis_count=basis, signal_count=signals,
                 examples=examples[:6], generated_at=report.get('generated_at') or 'Chưa lưu riêng trong bản cũ',
                 price_time_basis=snapshot.get('price_time_basis'), history=snapshot.get('history'),
                 current_href=dashboard(scope), min_samples=MIN_SAMPLES)
    buyer['qualified_count'] = snapshot.get('qualified_count')
    buyer['excluded_count'] = snapshot.get('excluded_count')
    page['buyer'] = buyer
    page['charts'] = _safe_charts(page, segments, comparisons)
    page['scope_label'] = scope
    period = report.get('period') or ''
    if scope not in {'Thủ Dầu Một', 'Bến Cát'}:
        page['hero_title'] = f'Báo cáo nhà đất {scope} {period}: ngân sách và mẫu so sánh'
        page['title'] = page['hero_title'] + ' | Radar BDS'
    page['hero_text'] = (f'{scope} · {period}. {basis} mẫu theo điều kiện lọc đã lưu. '
                         'Đọc theo ngân sách, loại hình và cỡ mẫu để chọn thông tin cần kiểm chứng trước khi đi xem.')
    page['description'] = page['hero_text']
    report['metrics'] = [dict(label='Tin thu thập', value=f'{raw_count:,}'.replace(',', '.'), note='Có thể gồm đăng lại'),
                         dict(label='Mẫu hợp lệ', value=str(basis), note='Theo hợp đồng và điều kiện lọc của bản đã lưu'),
                         dict(label='Tin đáng kiểm tra', value=str(signals), note='Tín hiệu đã lưu, không phải số giao dịch')]
    report['metrics'] += [dict(label=f'Giá rao trung vị {s["label"].lower()}', value=s['median_display'],
                               note=f'{s["n"]} mẫu đủ giá/m²; ngưỡng trình bày 15 mẫu') for s in segments]
    report['indicators'] = []
    report['trend_intro'] = ['Giá trên đồ thị là trung vị của mẫu quan sát từng kỳ. Thay đổi cơ cấu diện tích, vị trí và loại đường có thể làm giá trung vị thay đổi.',
                            'Kỳ hoặc phân khúc dưới 15 mẫu được để trống; không nội suy hoặc thay dữ liệu thiếu bằng số 0.'] if report.get('trend_rows') else []
    report['type_analysis'] = [f'{s["label"]}: {s["n"]} mẫu đủ giá/m²; {s["median_display"]}.' for s in segments]
    report['source_note'] = f'Nguồn Facebook · {raw_count} tin thu thập / {basis} mẫu theo điều kiện lọc đã lưu. Giá rao dùng để đối chiếu; không thay thế giá giao dịch.'
    report['insights'] = [dict(title=f'{scope}: đọc đúng phạm vi mẫu', body=summary[0]),
                          dict(title=f'{signals} tín hiệu cần xác minh', body=summary[1]),
                          dict(title='Đối chiếu cùng loại tài sản', body=summary[2])]
    report['methodology'] = [report['source_note'],
        'Mỗi loại hình và bảng có cỡ mẫu riêng. Trung vị gộp phải được tính trên mẫu phù hợp, không lấy trung bình trung vị phường.',
        'Khoảng P25–P75 chứa 50% mẫu quan sát ở giữa, không phải khoảng tin cậy hay giá mua an toàn.',
        'Giá rao, số ngày Radar ghi nhận và mẫu có cờ giảm giá không chứng minh giá chốt hoặc thanh khoản.',
        'Giấy tờ, đất ở, đường vào và quy hoạch cần xác minh theo hồ sơ/vị trí thực tế. Dữ liệu tin đăng không xác nhận pháp lý.']
    report['methodology'] += warnings
    if report.get('under_value'):
        report['under_value'] = dict(title='Số tín hiệu và phạm vi minh họa',
            links=report['under_value'].get('links', []),
            metrics=[dict(label='Tin đáng kiểm tra đã lưu', value=str(signals), note='Theo bộ lọc tín hiệu tại lần biên soạn'),
                     dict(label='Mẫu tin minh họa', value=str(len(examples)), note='Đã tuyển chọn; không phải mẫu số tỷ lệ thị trường')],
            body=['Mẫu tin ở phần người mua được chọn theo nhóm ngân sách; số tín hiệu là thống kê riêng. Không suy ra tỷ lệ cơ hội toàn khu từ các mẫu minh họa.'
                  if snapshot else 'Nhóm minh họa đã đi qua bộ lọc tín hiệu. Không suy ra tỷ lệ cơ hội của toàn phường từ nhóm đã chọn MOS cao.'])
    for row in report.get('area_rows', []):
        segment = next((s for s in segments if s['label'] == row.get('area')), None)
        comparison = next((r for r in comparisons if r['scope'] == row.get('area')), None)
        row['median_price'] = segment['median_display'] if segment else comparison['land_price'] if comparison else 'Chưa đủ mẫu'
    for row in report.get('trend_rows', []):
        for prefix in ('dat_nen', 'nha_dat'):
            if count(row.get(prefix + '_count')) < MIN_SAMPLES:
                row[prefix + '_price'] = 'Chưa đủ mẫu'
    for row in report.get('comparison_rows', []):
        ref = next((r for r in comparisons if r['scope'] == row.get('area')), None)
        row['median_price'] = ref['land_price'] if ref else 'Chưa đủ mẫu'
    # Keep linked descriptions consistent with small-sample suppression in this report.
    for link in page.get('local_links', []):
        ref = next((r for r in comparisons if r['href'] == link.get('href')), None)
        if ref:
            link['description'] = f'{ref["basis_count"]} mẫu sau lọc; đất nền n={ref["land_n"]}: {ref["land_price"]}.'
    return page

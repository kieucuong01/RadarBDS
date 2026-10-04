"""Public explanation of existing detail data; no verification inferred."""
from datetime import datetime, timedelta, timezone
import math

from analytics.valuation import MIN_RELIABLE_N_FOR_SIGNAL


def _positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _date_label(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if len(str(value)) == 10:
            return parsed.strftime('%d/%m/%Y')
        # Legacy timestamp-without-zone values use the application's UTC+7 zone.
        local_zone = timezone(timedelta(hours=7))
        parsed = parsed.replace(tzinfo=local_zone) if parsed.tzinfo is None else parsed
        return parsed.astimezone(local_zone).strftime('%d/%m/%Y %H:%M')
    except (ValueError, TypeError, OverflowError):
        return None


def build_listing_evidence(listing, map_location):
    old = _positive(listing.get('fair_ppm2_old'))
    new = _positive(listing.get('fair_ppm2_new'))
    fair = _positive(listing.get('fair_ppm2_display')) or _positive(listing.get('fair_ppm2'))
    actual = _positive(listing.get('valuation_actual_ppm2'))
    basis = 'new' if new is not None and (old is None or new < old) else 'old'
    count = _positive(listing.get(f'evidence_{basis}_samples')) if fair else None
    sample_count = int(count) if count is not None and count.is_integer() else None
    reason = 'Chưa đủ dữ liệu để giải thích chênh lệch giá tham khảo.'
    if fair and actual:
        margin = (fair - actual) / fair * 100
        if margin > 0:
            reason = f'Giá rao {actual:.1f} tr/m² thấp hơn mức tham khảo {fair:.1f} tr/m² khoảng {margin:.1f}%.'
        elif margin < 0:
            reason = f'Giá rao {actual:.1f} tr/m² cao hơn mức tham khảo {fair:.1f} tr/m² khoảng {abs(margin):.1f}% (tính trên mức tham khảo).'
        else:
            reason = f'Giá rao ngang mức tham khảo {fair:.1f} tr/m².'
    unverified = [
        'Tình trạng còn bán và giá chốt cần xác nhận với người bán.',
        'Cần đối chiếu giấy tờ, quyền sở hữu, thổ cư và quy hoạch; nội dung tin rao chưa phải xác minh pháp lý.',
    ]
    if not map_location or map_location.get('precision') != 'exact':
        unverified.append('Vị trí chính xác của thửa đất cần xác nhận; marker theo đường/khu vực chỉ là điểm đại diện.')
    flags = set(str(listing.get('evidence_quality_flags') or listing.get('source_quality_flags') or '').split(','))
    if flags & {'area_dimension_conflict', 'price_area_inconsistent', 'missing_area_evidence'}:
        unverified.append('Có cảnh báo diện tích: cần đối chiếu diện tích trên giấy tờ và kích thước thực tế.')
    if not _positive(listing.get('road_tier')):
        unverified.append('Cấp đường chưa rõ; cần kiểm tra lối vào và bề rộng đường thực tế.')
    return {
        'reason': reason,
        'method_note': 'Mức tham khảo dựa trên dữ liệu tin rao, không phải giá giao dịch đã xác nhận. Chênh lệch giá là lý do kiểm tra thêm, không bảo đảm lợi nhuận.',
        'two_models': old is not None and new is not None,
        'sample_count': sample_count,
        'thin_sample': 'low_segment_confidence' in flags or (sample_count is not None and sample_count < MIN_RELIABLE_N_FOR_SIGNAL),
        'valued_at': _date_label(listing.get(f'evidence_{basis}_computed_at')) if fair else None,
        'posted_at': _date_label(listing.get('posted_at')),
        'crawled_at': _date_label(listing.get('crawled_at')),
        'seen_at': _date_label(listing.get('last_seen_at')),
        'unverified': unverified,
    }

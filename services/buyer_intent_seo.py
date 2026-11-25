"""One maintained buyer intent on its existing owner; guest results are not aggregates."""
from datetime import datetime
import math

from db.connection import get_conn
from services.data_price_seo import SCOPES, TZ
from services.listing_feed import load_listing_feed
from services.public_cache import get_durable_dataset_versions

OWNER_SLUG = 'dat-nen-ben-cat-duoi-2-ty-khu-nao-con-nhieu-tin'
OWNER_PATH = '/tin-tuc/' + OWNER_SLUG
INTENT_ID = 'dat-duoi-2-ty-ben-cat'
UPDATED_AT = '2026-11-25'
WARDS = SCOPES['ben-cat']['wards']
CANDIDATE_LIMIT = 30
RESULT_LIMIT = 20
MIN_RESULTS = 3


def select_public_results(candidates, current_rows):
    """Narrow existing guest candidates, never promote a private/current row alone."""
    current = {r['id']: r for r in current_rows if type(r.get('id')) is int and r['id'] > 0}
    cards = []
    seen = set()
    for candidate in candidates[:CANDIDATE_LIMIT]:
        identity = candidate.get('id')
        if type(identity) is not int or identity <= 0 or identity in seen:
            continue
        if candidate.get('source') != 'facebook' or candidate.get('ward') not in WARDS:
            continue
        row = current.get(identity)
        if not row or row.get('source') != 'facebook' or row.get('ward') not in WARDS:
            continue
        if row.get('property_type') != 'dat_nen' or row.get('tx_type') != 'ban':
            continue
        if row.get('is_active') != 1 or row.get('duplicate_of_id') is not None:
            continue
        if row.get('source_status') == 'inactive' or any(row.get(k) for k in (
                'review_hidden', 'is_blacklisted', 'possibly_duplicate', 'probably_sold')):
            continue
        try:
            price, area = float(row['price_ty']), float(row['area_m2'])
        except (TypeError, ValueError, KeyError):
            continue
        if not (math.isfinite(price) and 0 < price < 2 and math.isfinite(area) and area > 0):
            continue
        seen.add(identity)
        cards.append(dict(id=identity, ward=row['ward'], area_m2=area, price_ty=price))
        if len(cards) == RESULT_LIMIT:
            break
    return cards


def load_results():
    """At most 30 existing guest candidates plus one bounded read-only PK lookup."""
    generated_at = datetime.now(TZ).isoformat()
    try:
        version = get_durable_dataset_versions(('listings',)).get('listings', 0)
        payload = load_listing_feed(None, sources=['facebook'], wards=list(WARDS),
            prop_types=['dat_nen'], price_max=2, tier='guest', date_range='1m',
            limit=CANDIDATE_LIMIT, page=1, complete_only=True, listings_version=version)
        candidates = [r for r in payload['listings'][:CANDIDATE_LIMIT]
            if r.get('source') == 'facebook' and type(r.get('id')) is int and r['id'] > 0]
        rows = []
        if candidates:
            with get_conn() as conn:
                conn.execute('SET TRANSACTION READ ONLY')
                rows = conn.execute('SELECT id,source,ward,property_type,tx_type,price_ty,area_m2,'
                    'is_active,review_hidden,is_blacklisted,duplicate_of_id,possibly_duplicate,'
                    'source_status,probably_sold FROM listings WHERE id=ANY(?)',
                    ([r['id'] for r in candidates],)).fetchall()
        cards = select_public_results(candidates, rows)
        return dict(available=True, cards=cards, count=len(cards),
                    eligible=len(cards) >= MIN_RESULTS, generated_at=generated_at)
    except Exception:
        # Error text may contain driver/connection details. UNKNOWN is not zero.
        return dict(available=False, cards=[], count=None, eligible=False, generated_at=generated_at)


def prepare_page(page):
    """Preserve the exact canonical and dated analysis; update only maintained metadata."""
    updated = dict(page)
    updated['article'] = dict(page['article'], modified_at=UPDATED_AT)
    updated.update(
        title='Đất nền Bến Cát dưới 2 tỷ: tin rao đang công khai | Radar BDS',
        hero_title='Đất nền Bến Cát dưới 2 tỷ: tin rao đang công khai',
        description='Xem tin bán đất nền Bến Cát có tổng giá rao dưới 2 tỷ, tách khỏi nhà xây sẵn và tin cho thuê. Danh sách công khai được kiểm tra khi mở trang; bản phân tích cũ ghi riêng kỳ dữ liệu.',
        scope_label='Bến Cát · đất nền có giá rao dưới 2 tỷ',
        primary_href='#tin-dat-duoi-2-ty', primary_cta='Xem tin đất nền có giá rao dưới 2 tỷ')
    return updated

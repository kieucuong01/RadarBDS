"""SSR price facts from a frozen packet; cards remain a fresh guest-only feed."""
from flask import Blueprint, abort, current_app, make_response, render_template
from services.data_price_seo import SCOPES, page_snapshots, load_public_cards, snapshot_root

bp = Blueprint('data_price_seo', __name__)


@bp.get('/gia-dat/<slug>')
def price_page(slug):
    if slug not in SCOPES:
        abort(404)
    try:
        current_snapshot, selected = page_snapshots(snapshot_root())
        snapshot = selected[slug]
        scope = snapshot['scopes'][slug]
    except (OSError, ValueError, KeyError, TypeError):
        response = make_response('Dữ liệu giá tạm thời chưa sẵn sàng.',503)
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Robots-Tag'] = 'noindex'
        return response
    parent = scope.get('parent')
    fallback = parent if parent and snapshot['scopes'].get(parent,{}).get('eligible') else None
    cards_error = False
    try:
        cards = load_public_cards(slug)
    except Exception:
        current_app.logger.exception('Data SEO guest cards unavailable for %s',slug)
        cards, cards_error = [], True
    response = make_response(render_template('data_price_seo.html', snapshot=snapshot,
        current_snapshot=current_snapshot, retained=snapshot['sha256'] != current_snapshot['sha256'],
        scope=scope, slug=slug, fallback=fallback, cards=cards, cards_error=cards_error,
        title=f"Giá rao đất nền {scope['name']}: dữ liệu tháng {snapshot['data_as_of'][5:7]}/{snapshot['data_as_of'][:4]} | Radar BDS"))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Radar-Price-Snapshot'] = snapshot['sha256']
    response.headers['X-Radar-Price-Current-Snapshot'] = current_snapshot['sha256']
    if not scope['eligible']:
        response.headers['X-Robots-Tag'] = 'noindex, follow'
    return response

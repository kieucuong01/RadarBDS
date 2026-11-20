"""SSR price facts from a frozen packet; cards remain a fresh guest-only feed."""
from datetime import date
import json
import re

from flask import Blueprint, abort, current_app, make_response, render_template
from services.data_price_seo import SCOPES, page_snapshots, load_public_cards, snapshot_root, validate_snapshot

bp = Blueprint('data_price_seo', __name__)


@bp.get('/gia-dat/<slug>/ban-luu/<packet_id>')
def archived_price(slug, packet_id):
    if slug not in SCOPES or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-f]{16}', packet_id):
        abort(404)
    try:
        snapshot = validate_snapshot(json.loads((snapshot_root() / (packet_id + '.json')).read_text(encoding='utf-8')))
        if snapshot['snapshot_id'] != packet_id:
            raise ValueError('snapshot identity mismatch')
    except FileNotFoundError:
        abort(404)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        abort(503)
    if slug not in snapshot['scopes']:
        abort(404)
    scope = snapshot['scopes'][slug]
    response = make_response(render_template('data_price_archive.html', snapshot=snapshot, scope=scope, slug=slug))
    response.headers['X-Radar-Price-Snapshot'] = snapshot['sha256']
    return response


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
    location = f"{scope['name']}, {snapshot['scopes'][parent]['name']}" if parent else scope['name']
    from app import _latest_ward_report

    report = _latest_ward_report(slug if parent else 'bds-binh-duong',
                                 through=date.fromisoformat(snapshot['period_end']))
    fallback = parent if parent and snapshot['scopes'].get(parent,{}).get('eligible') else None
    cards_error = False
    try:
        cards = load_public_cards(slug)
    except Exception:
        current_app.logger.exception('Data SEO guest cards unavailable for %s',slug)
        cards, cards_error = [], True
    response = make_response(render_template('data_price_seo.html', snapshot=snapshot,
        current_snapshot=current_snapshot, retained=snapshot['sha256'] != current_snapshot['sha256'],
        scope=scope, location=location, report=report, slug=slug, fallback=fallback, cards=cards, cards_error=cards_error,
        title=f"Giá rao đất nền {location} đến {snapshot['period_end']} | Radar BDS"))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Radar-Price-Snapshot'] = snapshot['sha256']
    response.headers['X-Radar-Price-Current-Snapshot'] = current_snapshot['sha256']
    if not scope['eligible']:
        response.headers['X-Robots-Tag'] = 'noindex, follow'
    return response

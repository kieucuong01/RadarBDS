"""Dashboard, signal, listing detail, lead, market, and chat API routes."""
from __future__ import annotations

from flask import Blueprint

bp = Blueprint("market_api", __name__)


def _impl(name: str, **kwargs):
    import app as app_module

    return getattr(app_module, name)(**kwargs)


@bp.route("/api/dashboard")
def api_dashboard(**kwargs):
    return _impl("api_dashboard", **kwargs)


@bp.route("/api/counts")
def api_counts(**kwargs):
    return _impl("api_counts", **kwargs)


@bp.route("/api/signals")
def api_signals(**kwargs):
    return _impl("api_signals", **kwargs)


@bp.route("/api/tphcm-land-prices")
def api_tphcm_land_prices(**kwargs):
    return _impl("api_tphcm_land_prices", **kwargs)


@bp.route("/api/trends")
def api_trends(**kwargs):
    return _impl("api_trends", **kwargs)


@bp.route("/api/insights")
def api_insights(**kwargs):
    return _impl("api_insights", **kwargs)


@bp.route('/api/heatmap')
def api_heatmap(**kwargs):
    return _impl("api_heatmap", **kwargs)


@bp.route('/api/market-indicators')
def api_market_indicators(**kwargs):
    return _impl("api_market_indicators", **kwargs)


@bp.route("/api/valuation-tool/estimate", methods=["POST"])
def api_valuation_tool_estimate(**kwargs):
    return _impl("api_valuation_tool_estimate", **kwargs)


@bp.route('/api/listings')
def api_listings(**kwargs):
    return _impl("api_listings", **kwargs)


@bp.route('/api/listing/<int:listing_id>')
def api_listing_detail(**kwargs):
    return _impl("api_listing_detail", **kwargs)


@bp.route('/api/listing/<int:listing_id>/memo')
def api_listing_memo(**kwargs):
    return _impl("api_listing_memo", **kwargs)


@bp.route('/api/history/<int:listing_id>')
def get_price_history(**kwargs):
    return _impl("get_price_history", **kwargs)


@bp.route("/api/leads", methods=["POST"])
def api_create_lead(**kwargs):
    return _impl("api_create_lead", **kwargs)


@bp.route("/api/lead-capture-guest", methods=["POST"])
def api_create_guest_lead(**kwargs):
    return _impl("api_create_guest_lead", **kwargs)


@bp.route('/api/chat', methods=['POST'])
def api_chat(**kwargs):
    return _impl("api_chat", **kwargs)

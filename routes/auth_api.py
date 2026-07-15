"""Auth, watchlist, Telegram binding, and tracking API routes."""
from __future__ import annotations

from flask import Blueprint

bp = Blueprint("auth_api", __name__)


def _impl(name: str, **kwargs):
    import app as app_module

    return getattr(app_module, name)(**kwargs)


@bp.route("/api/auth/check", methods=["POST"])
def api_auth_check(**kwargs):
    return _impl("api_auth_check", **kwargs)


@bp.route("/api/auth/register", methods=["POST"])
def api_auth_register(**kwargs):
    return _impl("api_auth_register", **kwargs)


@bp.route("/api/auth/login", methods=["POST"])
def api_auth_login(**kwargs):
    return _impl("api_auth_login", **kwargs)


@bp.route("/api/auth/logout", methods=["POST"])
def api_auth_logout(**kwargs):
    return _impl("api_auth_logout", **kwargs)


@bp.route("/api/auth/me", methods=["GET"])
def api_auth_me(**kwargs):
    return _impl("api_auth_me", **kwargs)


@bp.route("/api/watchlists", methods=["GET"])
def api_list_watchlists(**kwargs):
    return _impl("api_list_watchlists", **kwargs)


@bp.route("/api/watchlists", methods=["POST"])
def api_create_watchlist(**kwargs):
    return _impl("api_create_watchlist", **kwargs)


@bp.route("/api/watchlists/<int:wid>", methods=["PATCH"])
def api_update_watchlist(**kwargs):
    return _impl("api_update_watchlist", **kwargs)


@bp.route("/api/favorites", methods=["GET"])
def api_list_favorites(**kwargs):
    return _impl("api_list_favorites", **kwargs)


@bp.route("/api/favorites/<int:listing_id>", methods=["POST"])
def api_add_favorite(**kwargs):
    return _impl("api_add_favorite", **kwargs)


@bp.route("/api/favorites/<int:listing_id>", methods=["DELETE"])
def api_remove_favorite(**kwargs):
    return _impl("api_remove_favorite", **kwargs)


@bp.route("/api/auth/telegram/start", methods=["POST"])
def api_telegram_start(**kwargs):
    return _impl("api_telegram_start", **kwargs)


@bp.route("/api/auth/telegram/unbind", methods=["POST"])
def api_telegram_unbind(**kwargs):
    return _impl("api_telegram_unbind", **kwargs)


@bp.route("/api/auth/telegram/sync", methods=["POST"])
def api_telegram_sync(**kwargs):
    return _impl("api_telegram_sync", **kwargs)


@bp.route("/api/auth/telegram/webhook", methods=["POST"])
def api_telegram_webhook(**kwargs):
    return _impl("api_telegram_webhook", **kwargs)


@bp.route("/api/track", methods=["POST"])
def api_track(**kwargs):
    return _impl("api_track", **kwargs)


@bp.route("/api/watchlists/<int:wid>", methods=["DELETE"])
def api_delete_watchlist(**kwargs):
    return _impl("api_delete_watchlist", **kwargs)

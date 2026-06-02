"""Public page and static asset routes."""
from __future__ import annotations

from flask import Blueprint

bp = Blueprint("public", __name__)


def _impl(name: str, **kwargs):
    import app as app_module

    return getattr(app_module, name)(**kwargs)


@bp.route("/data/images/<path:filename>")
def serve_local_image(**kwargs):
    return _impl("serve_local_image", **kwargs)


@bp.route("/")
def index(**kwargs):
    return _impl("index", **kwargs)


@bp.route("/robots.txt")
def robots_txt(**kwargs):
    return _impl("robots_txt", **kwargs)


@bp.route("/sitemap.xml")
def sitemap_xml(**kwargs):
    return _impl("sitemap_xml", **kwargs)


@bp.route('/listing/<int:listing_id>')
def listing_detail(**kwargs):
    return _impl("listing_detail", **kwargs)

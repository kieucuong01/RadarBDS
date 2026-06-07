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


@bp.route("/dashboard")
def dashboard(**kwargs):
    return _impl("dashboard", **kwargs)


@bp.route("/binh-duong")
def seo_binh_duong(**kwargs):
    return _impl("redirect_legacy_binh_duong", **kwargs)


@bp.route("/binh-duong/<path:location_slug>")
def seo_binh_duong_location(location_slug, **kwargs):
    return _impl("seo_landing_page", slug=f"binh-duong/{location_slug}", **kwargs)


@bp.route("/san-deal-bds")
def seo_san_deal_bds(**kwargs):
    return _impl("seo_landing_page", slug="san-deal-bds", **kwargs)


@bp.route("/robots.txt")
def robots_txt(**kwargs):
    return _impl("robots_txt", **kwargs)


@bp.route("/sitemap.xml")
def sitemap_xml(**kwargs):
    return _impl("sitemap_xml", **kwargs)


@bp.route('/listing/<int:listing_id>')
def listing_detail(**kwargs):
    return _impl("listing_detail", **kwargs)

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


@bp.route("/bds-da-luu")
def saved_listings_page(**kwargs):
    return _impl("saved_listings_page", **kwargs)


@bp.route("/dinh-gia-bds")
def valuation_tool_page(**kwargs):
    return _impl("valuation_tool_page", **kwargs)


@bp.route("/bang-gia-dat-tphcm")
def tphcm_land_price_tool_page(**kwargs):
    return _impl("tphcm_land_price_tool_page", **kwargs)


@bp.route("/binh-duong")
def seo_binh_duong(**kwargs):
    return _impl("seo_binh_duong_landing", **kwargs)


@bp.route("/binh-duong/<path:location_slug>")
def seo_binh_duong_location(location_slug, **kwargs):
    return _impl("seo_landing_page", slug=f"binh-duong/{location_slug}", **kwargs)


@bp.route("/binh-duong/thu-dau-mot/<ward_slug>")
def seo_thu_dau_mot_ward_redirect(ward_slug, **kwargs):
    return _impl("seo_tdm_ward_redirect", ward_slug=ward_slug, **kwargs)


@bp.route("/ban-dat-binh-duong")
def seo_ban_dat_binh_duong(**kwargs):
    return _impl("seo_landing_page", slug="ban-dat-binh-duong", **kwargs)


@bp.route("/bao-cao")
def seo_bao_cao_index(**kwargs):
    return _impl("seo_report_hub_page", **kwargs)


@bp.route("/bao-cao/<path:report_slug>")
def seo_market_report(report_slug, **kwargs):
    return _impl("seo_landing_page", slug=f"bao-cao/{report_slug}", **kwargs)


@bp.route("/san-deal-bds")
def seo_san_deal_bds(**kwargs):
    return _impl("seo_landing_page", slug="san-deal-bds", **kwargs)


@bp.route("/kien-thuc")
def seo_knowledge_index(**kwargs):
    return _impl("seo_knowledge_hub_page", **kwargs)


@bp.route("/kien-thuc/<path:article_slug>")
def seo_article(article_slug, **kwargs):
    return _impl("seo_article_page", slug=article_slug, **kwargs)


@bp.route("/robots.txt")
def robots_txt(**kwargs):
    return _impl("robots_txt", **kwargs)


@bp.route("/llms.txt")
def llms_txt(**kwargs):
    return _impl("llms_txt", **kwargs)


@bp.route("/sitemap.xml")
def sitemap_xml(**kwargs):
    return _impl("sitemap_xml", **kwargs)


@bp.route('/listing/<int:listing_id>')
def listing_detail(**kwargs):
    return _impl("listing_detail", **kwargs)

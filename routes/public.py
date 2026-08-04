"""Public page and static asset routes."""

from __future__ import annotations

from flask import Blueprint, abort, make_response

from auth.core import current_tier, current_user
from services.radar_ask.service import feature_enabled, tier_allowed

bp = Blueprint("public", __name__)


def _impl(name: str, **kwargs):
    import app as app_module

    return getattr(app_module, name)(**kwargs)


@bp.route("/hoi-radar-bds")
def radar_ask_page():
    if not feature_enabled():
        abort(404)
    user = current_user()
    tier = current_tier()
    if not user or tier == "guest":
        response = make_response("Dang nhap de dung Radar Ask.", 401)
    elif not tier_allowed(tier):
        response = make_response("Goi tai khoan chua duoc cap Radar Ask.", 403)
    else:
        response = make_response("<main><h1>Radar Ask</h1></main>", 200)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers.pop("X-Radar-Public-Cache", None)
    return response


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


@bp.route("/quy-hoach-binh-duong")
def planning_hub_page(**kwargs):
    return _impl("planning_hub_page", **kwargs)


@bp.route("/ban-do-binh-duong")
def binh_duong_map_page(**kwargs):
    return _impl("binh_duong_map_page", **kwargs)


@bp.route("/quy-hoach-binh-duong/<path:planning_slug>")
def planning_detail_page(planning_slug, **kwargs):
    return _impl("planning_detail_page", slug=planning_slug, **kwargs)


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
    return _impl("seo_report_or_article_page", report_slug=report_slug, **kwargs)


@bp.route("/san-deal-bds")
def seo_san_deal_bds(**kwargs):
    return _impl("seo_landing_page", slug="san-deal-bds", **kwargs)


@bp.route("/tin-tuc")
def seo_news_index(**kwargs):
    return _impl("seo_news_hub_page", **kwargs)


@bp.route("/tin-tuc/du-lieu-radarbds")
def seo_news_radar_archive(**kwargs):
    return _impl("seo_news_radar_archive_page", **kwargs)


@bp.route("/tin-tuc/chu-de-nong")
def seo_hot_topic_hub(**kwargs):
    return _impl("public_content_hub_page", kind="chu-de-nong", **kwargs)


@bp.route("/tin-tuc/quyet-dinh-van-ban")
def seo_legal_document_hub(**kwargs):
    return _impl(
        "public_content_hub_page", kind="quyet-dinh-van-ban", **kwargs
    )


@bp.route("/tin-tuc/quyet-dinh-van-ban/<slug>")
def seo_legal_document_detail(slug, **kwargs):
    return _impl("legal_document_page", slug=slug, **kwargs)


@bp.route("/tai-lieu/van-ban/<slug>.pdf")
def seo_legal_document_pdf(slug, **kwargs):
    return _impl("legal_document_pdf", slug=slug, **kwargs)


@bp.route("/tin-tuc/<path:article_slug>")
def seo_news_article(article_slug, **kwargs):
    return _impl("seo_news_article_page", slug=article_slug, **kwargs)


@bp.route("/kien-thuc")
def seo_knowledge_index(**kwargs):
    return _impl("seo_knowledge_legacy_redirect", **kwargs)


@bp.route("/kien-thuc/<path:article_slug>")
def seo_article(article_slug, **kwargs):
    return _impl("seo_knowledge_legacy_redirect", article_slug=article_slug, **kwargs)


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

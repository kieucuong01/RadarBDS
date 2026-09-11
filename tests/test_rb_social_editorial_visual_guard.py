"""Regression: legacy ward-card text must not leak into editorial visuals."""
import json
from pathlib import Path

from config.seo_articles import SEO_ARTICLES
from scripts import rb_social_editorial as e


def test_price_explainer_is_insight_not_tool_walkthrough():
    page = SEO_ARTICLES["bang-gia-dat-va-gia-rao-khac-nhau-the-nao"]
    assert e.pillar_for_page(page, "bang-gia-dat-va-gia-rao-khac-nhau-the-nao") == "radar_insight"


def test_legacy_ward_card_prompt_never_reaches_an_editorial_asset(tmp_path):
    for slug, page in SEO_ARTICLES.items():
        if not str(page.get("path", "")).startswith("/tin-tuc/"):
            continue
        visual = e.render_visual(page, slug, e.pillar_for_page(page, slug), asset_dir=tmp_path)
        blob = json.dumps(visual, ensure_ascii=False).lower()
        for leak in ("classic ward price card", "đang so giá", "khu vực này"):
            assert leak not in blob, f"{slug} leaked legacy prompt: {leak}"


def test_curated_headline_replaces_generic_pillar_default(tmp_path):
    slug = "bang-gia-dat-va-gia-rao-khac-nhau-the-nao"
    page = SEO_ARTICLES[slug]
    visual = e.render_visual(page, slug, e.pillar_for_page(page, slug), asset_dir=tmp_path)
    assert visual["headline"] == "Bảng giá đất ≠ giá chủ phải bán"
    assert Path(visual["path"]).exists()


def test_reader_links_never_expose_internal_filter_params():
    from config.seo_articles import SEO_ARTICLES
    for slug, page in SEO_ARTICLES.items():
        if not str(page.get("path", "")).startswith("/tin-tuc/"):
            continue
        comment = e.build_self_comment(page, "https://radarbds.vn" + page["path"], slug)
        for leak in ("mos_min", "mos_max", "tab=signals", "tb_min", "tb_max"):
            assert leak not in comment, f"{slug} leaked {leak}"

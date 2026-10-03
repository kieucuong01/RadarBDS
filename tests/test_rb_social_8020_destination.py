from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from scripts.rb_social_editorial import build_self_comment


ARTICLE = "https://radarbds.vn/tin-tuc/phu-loi-so-tin-rao"


def _links(text: str) -> list[str]:
    return [word.rstrip(")>,") for word in text.split() if word.startswith("https://radarbds.vn/")]


def test_area_article_uses_one_relevant_attributed_link_not_fake_filter_homepage():
    page = {
        "title": "Phú Lợi: xem tin rao",
        "path": "/tin-tuc/phu-loi-so-tin-rao",
        "social_editorial": {},
    }

    comment = build_self_comment(page, ARTICLE, "phu-loi-so-tin-rao")
    links = _links(comment)

    assert len(links) == 1
    parsed = urlsplit(links[0])
    assert parsed.path == "/tin-tuc/phu-loi-so-tin-rao"
    params = parse_qs(parsed.query)
    assert params["utm_source"] == ["facebook"]
    assert params["utm_medium"] == ["social"]
    assert params["utm_campaign"] == ["rb_content_v2"]
    assert params["utm_content"] == ["phu-loi-so-tin-rao"]
    assert not any(key in parsed.query for key in ("tab=", "ward=", "mos_min=", "tb_min="))
    assert "Bài Radar về Phú Lợi" in comment


def test_root_filter_with_internal_params_falls_back_to_article():
    page = {
        "title": "Phú Lợi: xem tin rao",
        "path": "/tin-tuc/phu-loi-so-tin-rao",
        "social_editorial": {"radar_url": "https://radarbds.vn/?tab=signals&ward=Phú+Lợi"},
    }

    comment = build_self_comment(page, ARTICLE, "phu-loi-so-tin-rao")
    links = _links(comment)

    assert len(links) == 1
    assert urlsplit(links[0]).path == "/tin-tuc/phu-loi-so-tin-rao"
    assert "tab=" not in links[0] and "ward=" not in links[0]


def test_specific_feature_destination_is_preserved_as_the_single_primary_link():
    page = {
        "title": "Định giá đất online",
        "path": "/tin-tuc/dinh-gia-huong-dan",
        "social_editorial": {"radar_url": "https://radarbds.vn/dinh-gia-bds"},
    }

    comment = build_self_comment(page, "https://radarbds.vn/tin-tuc/dinh-gia-huong-dan", "dinh-gia-huong-dan")
    links = _links(comment)

    assert len(links) == 1
    assert urlsplit(links[0]).path == "/dinh-gia-bds"
    assert "utm_content=dinh-gia-huong-dan" in links[0]


def test_news_lane_uses_shared_facebook_attribution_convention():
    from scripts.rb_page_news_workflow import utm_url as news_utm_url

    link = urlsplit(news_utm_url("https://radarbds.vn/tin-tuc/news", "news-slug"))
    params = parse_qs(link.query)

    assert link.path == "/tin-tuc/news"
    assert params["utm_source"] == ["facebook"]
    assert params["utm_medium"] == ["social"]
    assert params["utm_campaign"] == ["rb_content_v2"]
    assert params["utm_content"] == ["news-slug"]


def test_page_workflow_rejects_root_url_disguised_as_ward_filter():
    from scripts import rb_page_news_workflow as workflow

    queue = {
        "schema": workflow.QUEUE_SCHEMA,
        "status": "ready",
        "target": {"platform": "facebook", "surface": "page"},
        "content": {
            "generated_by": "rb_social_editorial",
            "self_comment": "Mở tin Phú Lợi: https://radarbds.vn/?tab=listings&ward=Phú+Lợi&utm_source=facebook",
        },
    }

    try:
        workflow.validate_publishable_reviewed_queue(queue, lane="radar")
    except ValueError as exc:
        assert "homepage" in str(exc)
    else:
        raise AssertionError("homepage filter URL should be blocked before publishing")

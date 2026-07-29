from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest


def _json_ld(html: str) -> list[dict]:
    payloads = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        html,
        re.S,
    )
    return [json.loads(payload) for payload in payloads]


def test_news_root_is_aggregate_hub_and_archive_moves_without_changing_articles():
    import app as radar_app
    from config.seo_articles import SEO_ARTICLES

    client = radar_app.app.test_client()
    aggregate = client.get("/tin-tuc")
    archive = client.get("/tin-tuc/du-lieu-radarbds")

    assert aggregate.status_code == 200
    assert archive.status_code == 200
    aggregate_html = aggregate.get_data(as_text=True)
    archive_html = archive.get_data(as_text=True)
    assert '<link rel="canonical" href="https://radarbds.vn/tin-tuc">' in aggregate_html
    assert "Trung tâm tin tức BĐS Bình Dương" in aggregate_html
    for path in (
        "/tin-tuc/chu-de-nong",
        "/tin-tuc/du-lieu-radarbds",
        "/tin-tuc/quyet-dinh-van-ban",
    ):
        assert f'href="{path}"' in aggregate_html
    assert (
        '<link rel="canonical" '
        'href="https://radarbds.vn/tin-tuc/du-lieu-radarbds">'
        in archive_html
    )
    expected_paths = {
        page["path"]
        for page in SEO_ARTICLES.values()
        if str(page.get("path") or "").startswith("/tin-tuc/")
    }
    assert expected_paths
    for path in expected_paths:
        response = client.get(path)
        assert response.status_code in {200, 301}
        if response.status_code == 200:
            assert (
                f'<link rel="canonical" href="https://radarbds.vn{path}">'
                in response.get_data(as_text=True)
            )


def test_existing_news_article_breadcrumb_includes_radar_data_archive():
    import app as radar_app
    from config.seo_articles import SEO_ARTICLES

    slug, page = next(
        (slug, page)
        for slug, page in SEO_ARTICLES.items()
        if str(page.get("path") or "").startswith("/tin-tuc/")
        and page["path"].rsplit("/", 1)[-1] == slug
    )

    html = radar_app.app.test_client().get(page["path"]).get_data(as_text=True)

    assert 'href="/tin-tuc"' in html
    assert 'href="/tin-tuc/du-lieu-radarbds"' in html
    assert "Tin từ dữ liệu Radar BDS" in html


@pytest.mark.parametrize(
    ("path", "heading", "filter_name"),
    (
        (
            "/tin-tuc/chu-de-nong",
            "Chủ đề nóng bất động sản Bình Dương",
            "Lọc theo nguồn",
        ),
        (
            "/tin-tuc/quyet-dinh-van-ban",
            "Quyết định và văn bản về Bình Dương",
            "Lọc theo cơ quan",
        ),
    ),
)
def test_external_content_hubs_are_indexable_progressive_pages(
    path, heading, filter_name
):
    import app as radar_app

    html = radar_app.app.test_client().get(path).get_data(as_text=True)

    assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
    assert f"<h1>{heading}</h1>" in html
    assert filter_name in html
    assert "data-public-content-results" in html
    assert "aria-live=\"polite\"" in html
    assert "public_content_hub.js" in html
    graphs = _json_ld(html)
    assert any(
        graph.get("@type") == "CollectionPage"
        or any(
            node.get("@type") == "CollectionPage"
            for node in graph.get("@graph", [])
        )
        for graph in graphs
    )


def test_hot_topic_cards_are_external_and_never_render_full_body(monkeypatch):
    import app as radar_app

    class Repository:
        @staticmethod
        def list_published(**_kwargs):
            return [
                {
                    "id": 1,
                    "item_type": "hot_topic",
                    "slug": "tin-moi",
                    "title": "Tin hạ tầng mới",
                    "summary": "Mô tả metadata ngắn.",
                    "source_name": "CafeLand",
                    "source_url": "https://cafeland.vn/tin-moi",
                    "topic": "ha-tang",
                    "published_at": datetime(2026, 7, 29, tzinfo=timezone.utc),
                    "updated_at": datetime(2026, 7, 30, tzinfo=timezone.utc),
                }
            ]

    monkeypatch.setattr(radar_app, "_public_content_repository", Repository())

    html = radar_app.app.test_client().get(
        "/tin-tuc/chu-de-nong"
    ).get_data(as_text=True)

    assert 'href="https://cafeland.vn/tin-moi"' in html
    assert 'rel="external noopener"' in html
    assert 'target="_blank"' in html
    assert "Mô tả metadata ngắn." in html
    assert "Lọc theo chủ đề" in html
    assert 'data-public-content-topic' in html
    assert 'data-content-topic="ha-tang"' in html
    assert "Nội dung toàn bài" not in html


def test_legal_detail_renders_legislation_schema_and_stable_pdf_route(
    monkeypatch,
):
    import app as radar_app

    item = {
        "id": 9,
        "item_type": "legal_document",
        "status": "published",
        "slug": "quyet-dinh-1703",
        "title": "Quyết định 1703/QĐ-UBND",
        "summary": "Phê duyệt hồ sơ khu vực phát triển đô thị Tân An.",
        "source_name": "Công báo TP.HCM",
        "source_url": "https://congbao.hochiminhcity.gov.vn/1703",
        "canonical_url": "https://congbao.hochiminhcity.gov.vn/1703",
        "published_at": datetime(2025, 6, 18, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 7, 30, tzinfo=timezone.utc),
        "document_number": "1703/QĐ-UBND",
        "issuing_authority": "UBND tỉnh Bình Dương",
        "document_type": "Quyết định",
        "document_scope": "Tân An, Thủ Dầu Một",
        "pdf_object_key": (
            "public/legal-documents/2025/quyet-dinh-1703-" + ("a" * 64) + ".pdf"
        ),
        "pdf_sha256": "a" * 64,
        "pdf_size_bytes": 1234,
        "pdf_content_type": "application/pdf",
    }

    class Repository:
        @staticmethod
        def list_published(**_kwargs):
            return [item]

        @staticmethod
        def get_published_by_slug(slug):
            return item if slug == item["slug"] else None

    monkeypatch.setattr(radar_app, "_public_content_repository", Repository())
    monkeypatch.setattr(
        radar_app,
        "public_pdf_url",
        lambda _key: "https://cdn.radarbds.vn/public/document.pdf",
    )
    client = radar_app.app.test_client()

    detail = client.get("/tin-tuc/quyet-dinh-van-ban/quyet-dinh-1703")
    download = client.get("/tai-lieu/van-ban/quyet-dinh-1703.pdf")

    assert detail.status_code == 200
    html = detail.get_data(as_text=True)
    assert "1703/QĐ-UBND" in html
    assert 'href="/tai-lieu/van-ban/quyet-dinh-1703.pdf"' in html
    graphs = _json_ld(html)
    flattened = [
        node
        for graph in graphs
        for node in (graph.get("@graph", [graph]))
    ]
    legislation = next(
        node for node in flattened if node.get("@type") == "Legislation"
    )
    assert legislation["legislationIdentifier"] == "1703/QĐ-UBND"
    assert legislation["encoding"]["@type"] == "MediaObject"
    assert download.status_code == 302
    assert download.headers["Location"] == (
        "https://cdn.radarbds.vn/public/document.pdf"
    )


@pytest.mark.parametrize(
    ("slug", "heading"),
    (
        ("quy-hoach-su-dung-dat", "Bản đồ quy hoạch sử dụng đất"),
        ("tuyen-duong", "Bản đồ quy hoạch tuyến đường"),
        ("quy-hoach-chi-tiet", "Bản đồ quy hoạch chi tiết"),
        ("quy-hoach-phan-khu", "Bản đồ quy hoạch phân khu"),
    ),
)
def test_planning_category_pages_have_canonical_and_non_dead_empty_state(
    slug, heading
):
    import app as radar_app

    path = f"/quy-hoach-binh-duong/{slug}"
    response = radar_app.app.test_client().get(path)

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'<link rel="canonical" href="https://radarbds.vn{path}">' in html
    assert f"<h1>{heading}</h1>" in html
    assert (
        "Đang cập nhật chuyên đề" in html
        or "data-planning-category-card" in html
    )
    assert "Nguồn đang theo dõi" in html


def test_new_hubs_and_categories_are_in_sitemap_and_llms_once():
    import app as radar_app

    client = radar_app.app.test_client()
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    llms = client.get("/llms.txt").get_data(as_text=True)
    paths = (
        "/tin-tuc",
        "/tin-tuc/chu-de-nong",
        "/tin-tuc/du-lieu-radarbds",
        "/tin-tuc/quyet-dinh-van-ban",
        "/quy-hoach-binh-duong/quy-hoach-su-dung-dat",
        "/quy-hoach-binh-duong/tuyen-duong",
        "/quy-hoach-binh-duong/quy-hoach-chi-tiet",
        "/quy-hoach-binh-duong/quy-hoach-phan-khu",
    )

    for path in paths:
        url = f"https://radarbds.vn{path}"
        assert sitemap.count(f"<loc>{url}</loc>") == 1
        assert url in llms


def test_new_hub_and_category_sitemap_entries_have_lastmod():
    import app as radar_app

    sitemap = radar_app.app.test_client().get("/sitemap.xml").get_data(
        as_text=True
    )
    paths = (
        "/tin-tuc",
        "/tin-tuc/chu-de-nong",
        "/tin-tuc/du-lieu-radarbds",
        "/tin-tuc/quyet-dinh-van-ban",
        "/quy-hoach-binh-duong/quy-hoach-su-dung-dat",
        "/quy-hoach-binh-duong/tuyen-duong",
        "/quy-hoach-binh-duong/quy-hoach-chi-tiet",
        "/quy-hoach-binh-duong/quy-hoach-phan-khu",
    )

    for path in paths:
        assert re.search(
            rf"<loc>https://radarbds\.vn{re.escape(path)}</loc>\s*"
            r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>",
            sitemap,
        )


def test_public_content_tracking_actions_are_allowlisted():
    import app as radar_app

    for action in (
        "public_content_filter_used",
        "public_content_card_clicked",
        "public_document_download_clicked",
    ):
        assert action in radar_app.ALLOWED_TRACK_ACTIONS


def test_public_content_tracking_context_drops_raw_search_text():
    import app as radar_app

    context = radar_app._safe_public_content_tracking_context(
        "public_content_filter_used",
        {
            "query": "nội dung riêng tư",
            "query_length": 18,
            "result_count": 4,
            "facet": "CafeLand",
            "path": "/tin-tuc/chu-de-nong",
        },
    )

    assert context == {
        "query_length": 18,
        "result_count": 4,
        "facet": "CafeLand",
        "path": "/tin-tuc/chu-de-nong",
    }

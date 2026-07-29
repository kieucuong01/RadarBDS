from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest


def test_source_registry_is_closed_and_official_documents_are_separate():
    from config.public_content_sources import PUBLIC_CONTENT_SOURCES

    assert PUBLIC_CONTENT_SOURCES
    assert {source.source_type for source in PUBLIC_CONTENT_SOURCES} == {
        "hot_topic",
        "legal_discovery",
        "official_document",
    }
    assert any(source.key == "cafeland-binh-duong" for source in PUBLIC_CONTENT_SOURCES)
    assert all(source.discovery_url.startswith("https://") for source in PUBLIC_CONTENT_SOURCES)
    assert all(source.allowed_hosts for source in PUBLIC_CONTENT_SOURCES)
    assert all(
        source.can_publish_pdf is (source.source_type == "official_document")
        for source in PUBLIC_CONTENT_SOURCES
    )


def test_normalize_content_url_removes_tracking_and_fragment():
    from services.public_content import normalize_content_url

    assert normalize_content_url(
        "https://cafeland.vn/path/?utm_source=x&b=2&a=1#section"
    ) == "https://cafeland.vn/path?a=1&b=2"


@pytest.mark.parametrize(
    "url",
    (
        "http://cafeland.vn/path",
        "https://user:pass@cafeland.vn/path",
        "https://cafeland.vn:8443/path",
        "file:///etc/passwd",
    ),
)
def test_validate_source_url_rejects_unsafe_shapes(url):
    from services.public_content import UnsafeSourceUrl, validate_source_url

    with pytest.raises(UnsafeSourceUrl):
        validate_source_url(
            url,
            allowed_hosts={"cafeland.vn"},
            resolver=lambda _host: ["1.1.1.1"],
        )


def test_validate_source_url_rejects_private_or_mixed_dns_answers():
    from services.public_content import UnsafeSourceUrl, validate_source_url

    with pytest.raises(UnsafeSourceUrl):
        validate_source_url(
            "https://cafeland.vn/path",
            allowed_hosts={"cafeland.vn"},
            resolver=lambda _host: ["1.1.1.1", "127.0.0.1"],
        )


def test_validate_source_url_accepts_exact_host_and_public_dns():
    from services.public_content import validate_source_url

    assert validate_source_url(
        "https://cafeland.vn/path",
        allowed_hosts={"cafeland.vn"},
        resolver=lambda _host: ["1.1.1.1", "2606:4700:4700::1111"],
    ) == "https://cafeland.vn/path"


def test_validate_pdf_payload_checks_declared_and_actual_size_mime_and_magic():
    from services.public_content import (
        MAX_PDF_BYTES,
        InvalidPdf,
        validate_pdf_payload,
    )

    payload = b"%PDF-1.7\nfixture"
    asset = validate_pdf_payload(
        payload,
        content_type="application/pdf; charset=binary",
        declared_length=len(payload),
    )

    assert asset.size_bytes == len(payload)
    assert len(asset.sha256) == 64
    assert asset.content_type == "application/pdf"

    with pytest.raises(InvalidPdf):
        validate_pdf_payload(b"<html>not pdf</html>", content_type="application/pdf")
    with pytest.raises(InvalidPdf):
        validate_pdf_payload(b"%PDFnot-a-header", content_type="application/pdf")
    with pytest.raises(InvalidPdf):
        validate_pdf_payload(payload, content_type="text/html")
    with pytest.raises(InvalidPdf):
        validate_pdf_payload(
            payload,
            content_type="application/pdf",
            declared_length=MAX_PDF_BYTES + 1,
        )
    with pytest.raises(InvalidPdf):
        validate_pdf_payload(
            b"%PDF" + (b"x" * MAX_PDF_BYTES),
            content_type="application/pdf",
        )


def test_pdf_object_key_is_immutable_and_path_safe():
    from services.public_content import pdf_object_key

    sha256 = "a" * 64
    assert pdf_object_key(2026, "QD 1703/../Tân An", sha256) == (
        "public/legal-documents/2026/qd-1703-tan-an-" + sha256 + ".pdf"
    )


def test_publication_gate_fails_closed_for_legal_documents_without_official_pdf():
    from services.public_content import (
        PdfAsset,
        PublicContentCandidate,
        publication_decision,
    )

    candidate = PublicContentCandidate(
        item_type="legal_document",
        slug="quyet-dinh-1703-tan-an",
        title="Quyết định 1703/QĐ-UBND",
        summary="Phê duyệt hồ sơ đề xuất khu vực phát triển đô thị Tân An.",
        source_key="thuviennhadat-binh-duong",
        source_name="Thư Viện Nhà Đất",
        source_url="https://thuviennhadat.vn/phap-luat/example.html",
        canonical_url="https://thuviennhadat.vn/phap-luat/example.html",
        topic="quy-hoach",
        published_at=datetime(2025, 6, 18, tzinfo=timezone.utc),
        document_number="1703/QĐ-UBND",
        issuing_authority="UBND tỉnh Bình Dương",
        document_type="Quyết định",
        document_scope="Tân An, Thủ Dầu Một",
        pdf_source_url="https://cdn.thuviennhadat.vn/example.pdf",
    )
    pdf = PdfAsset(
        sha256="b" * 64,
        size_bytes=128,
        content_type="application/pdf",
    )

    assert publication_decision(candidate, pdf=None, official_pdf=False) == (
        "draft",
        "official_pdf_required",
    )
    assert publication_decision(candidate, pdf=pdf, official_pdf=False) == (
        "draft",
        "official_pdf_required",
    )
    assert publication_decision(candidate, pdf=pdf, official_pdf=True) == (
        "published",
        "",
    )


def test_hot_topic_parser_keeps_metadata_only():
    from config.public_content_sources import get_public_content_source
    from services.public_content import parse_cafeland_topic

    html = """
    <html><body>
      <h2>Bất động sản Bình Dương</h2>
      <article>
        <h3><a href="/tin-tuc/bai-moi.html">Tin mới Bình Dương</a></h3>
        <time datetime="2026-07-29T08:30:00+07:00">29/07/2026</time>
        <p>Thông tin hạ tầng mới nhất tại khu vực Bình Dương cũ.</p>
      </article>
    </body></html>
    """
    source = get_public_content_source("cafeland-binh-duong")

    candidates = parse_cafeland_topic(html, source)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.item_type == "hot_topic"
    assert candidate.title == "Tin mới Bình Dương"
    assert candidate.summary.startswith("Thông tin hạ tầng")
    assert candidate.canonical_url == "https://cafeland.vn/tin-tuc/bai-moi.html"
    assert not hasattr(candidate, "body")


def test_hot_topic_parser_handles_heading_lists_without_article_wrappers():
    from config.public_content_sources import get_public_content_source
    from services.public_content import parse_cafeland_topic

    html = """
    <div class="item">
      <h3><a href="/tin/ha-tang-moi.html">Hạ tầng mới tại Bình Dương</a></h3>
      <div>Cập nhật: 29/07/2026 08:30 AM</div>
      <p>Mô tả ngắn do nguồn công khai cung cấp.</p>
    </div>
    """

    candidates = parse_cafeland_topic(
        html, get_public_content_source("cafeland-binh-duong")
    )

    assert [item.title for item in candidates] == [
        "Hạ tầng mới tại Bình Dương"
    ]
    assert candidates[0].published_at is not None


def test_hot_topic_parser_rejects_links_outside_source_allowlist():
    from config.public_content_sources import get_public_content_source
    from services.public_content import parse_cafeland_topic

    markup = """
    <article>
      <h3><a href="https://evil.example/fake-news">Tin bị chèn link ngoài</a></h3>
      <time datetime="2026-07-29T08:30:00+07:00">29/07/2026</time>
    </article>
    """

    candidates = parse_cafeland_topic(
        markup, get_public_content_source("cafeland-binh-duong")
    )

    assert candidates == []


def test_legal_parser_extracts_metadata_but_third_party_stays_discovery_only():
    from config.public_content_sources import get_public_content_source
    from services.public_content import parse_legal_document_page

    html = """
    <html><head>
      <meta name="description" content="Phê duyệt hồ sơ phát triển đô thị Tân An.">
    </head><body>
      <h1>Phê duyệt hồ sơ đề xuất Khu vực phát triển đô thị Tân An</h1>
      <p>Ngày 18 tháng 6 năm 2025, UBND tỉnh Bình Dương ban hành
      Quyết định 1703/QĐ-UBND.</p>
      <a href="https://cdn.thuviennhadat.vn/qd-1703.pdf">Quyết định gốc</a>
    </body></html>
    """
    source = get_public_content_source("thuviennhadat-binh-duong")

    candidates = parse_legal_document_page(html, source)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.item_type == "legal_document"
    assert candidate.document_number == "1703/QĐ-UBND"
    assert candidate.issuing_authority == "UBND tỉnh Bình Dương"
    assert candidate.pdf_source_url.endswith("qd-1703.pdf")
    assert publication_decision_for_source(candidate, source, None)[0] == "draft"


def publication_decision_for_source(candidate, source, pdf):
    from services.public_content import publication_decision

    return publication_decision(
        candidate,
        pdf=pdf,
        official_pdf=source.can_publish_pdf,
    )


def test_stream_response_enforces_limit_even_without_content_length():
    from services.public_content import InvalidPdf, read_limited_response

    class Response:
        headers = {"Content-Type": "application/pdf"}

        @staticmethod
        def iter_content(_chunk_size):
            yield b"%PDF"
            yield b"x" * 8

    with pytest.raises(InvalidPdf):
        read_limited_response(Response(), max_bytes=10)


def test_pdf_upload_uses_single_part_put_object_and_document_metadata(
    monkeypatch, tmp_path
):
    from services import public_content

    path = tmp_path / "document.pdf"
    path.write_bytes(b"%PDF-1.7\nfixture")
    captured = {}

    class Client:
        def put_object(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(public_content, "s3_client", lambda: Client())
    monkeypatch.setattr(public_content, "s3_bucket", lambda: "radarbds")
    monkeypatch.setattr(public_content, "s3_object_acl", lambda: "public-read")
    monkeypatch.setattr(public_content, "s3_object_exists", lambda _key: False)

    key = public_content.upload_public_pdf(
        path,
        "public/legal-documents/2026/document-" + ("c" * 64) + ".pdf",
        download_name="quyet-dinh-1703.pdf",
    )

    assert key.endswith(".pdf")
    assert captured["Bucket"] == "radarbds"
    assert captured["Key"] == key
    assert captured["ContentType"] == "application/pdf"
    assert captured["ContentDisposition"] == (
        'inline; filename="quyet-dinh-1703.pdf"'
    )
    assert captured["CacheControl"] == "public, max-age=31536000, immutable"
    assert bytes(captured["Body"]) == path.read_bytes()


def test_pdf_upload_reuses_existing_immutable_object(monkeypatch, tmp_path):
    from services import public_content

    path = tmp_path / "document.pdf"
    path.write_bytes(b"%PDF-1.7\nfixture")
    monkeypatch.setattr(public_content, "s3_object_exists", lambda _key: True)
    monkeypatch.setattr(
        public_content,
        "s3_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("existing immutable object must not be overwritten")
        ),
    )

    result = public_content.upload_public_pdf(
        path,
        "public/legal-documents/2026/document-" + ("c" * 64) + ".pdf",
        download_name="quyet-dinh-1703.pdf",
    )

    assert result.created is False
    assert result.endswith(".pdf")


def test_repository_upsert_is_parameterized_and_idempotent():
    from services.public_content import (
        PostgresPublicContentRepository,
        PublicContentCandidate,
    )

    class Cursor:
        lastrowid = 41

    class Connection:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            return Cursor()

    class Context:
        def __init__(self, conn):
            self.conn = conn

        def __enter__(self):
            return self.conn

        def __exit__(self, *_args):
            return False

    conn = Connection()
    repository = PostgresPublicContentRepository(
        connection_factory=lambda: Context(conn)
    )
    candidate = PublicContentCandidate(
        item_type="hot_topic",
        slug="tin-moi",
        title="Tin 'mới' Bình Dương",
        summary="Mô tả",
        source_key="cafeland-binh-duong",
        source_name="CafeLand",
        source_url="https://cafeland.vn/tin-moi",
        canonical_url="https://cafeland.vn/tin-moi",
        topic="ha-tang",
        published_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )

    assert repository.upsert_candidate(
        candidate, status="published", status_reason=""
    ) == 41
    sql, params = conn.calls[0]
    assert "canonical_url = ? OR fingerprint = ? OR slug = ?" in sql
    assert (
        "CASE WHEN status = 'published' AND ? = 'draft' "
        "THEN status ELSE ? END"
    ) in sql
    assert (
        "CASE WHEN status = 'published' AND ? = 'draft' "
        "THEN status_reason ELSE ? END"
    ) in sql
    assert candidate.title not in sql
    assert candidate.title in params


def test_official_index_discovers_and_parses_multiple_detail_pages():
    from config.public_content_sources import PublicContentSource
    from services.public_content import run_public_content_sync

    source = PublicContentSource(
        key="official-fixture",
        name="Official Fixture",
        source_type="official_document",
        discovery_url="https://official.example/van-ban/",
        allowed_hosts=frozenset({"official.example"}),
        parser="official_document",
        can_publish_pdf=True,
    )
    index_html = """
      <a href="/van-ban/quyet-dinh-1">Quyết định 1</a>
      <a href="/van-ban/quyet-dinh-2">Quyết định 2</a>
    """

    def detail(number):
        return f"""
          <h1>Quyết định {number}/QĐ-UBND về Bình Dương</h1>
          <p>Ngày 18 tháng 6 năm 2025, UBND tỉnh Bình Dương ban hành.</p>
          <a href="/pdf/{number}.pdf">Tải PDF</a>
        """

    class Response:
        status_code = 200
        headers = {"Content-Type": "text/html"}

        def __init__(self, text="", payload=b""):
            self.text = text
            self.payload = payload

        def iter_content(self, _chunk_size):
            yield self.payload

    class Session:
        @staticmethod
        def get(url, **_kwargs):
            if url.endswith("/van-ban"):
                return Response(index_html)
            if "quyet-dinh-1" in url:
                return Response(detail(1))
            if "quyet-dinh-2" in url:
                return Response(detail(2))
            response = Response(
                payload=b"%PDF-1.7\nfixture",
            )
            response.headers = {"Content-Type": "application/pdf"}
            return response

    class Repository:
        def __init__(self):
            self.rows = {}

        def upsert_candidate(self, candidate, *, status, status_reason):
            self.rows[candidate.fingerprint] = (candidate, status, status_reason)
            return len(self.rows)

        def attach_pdf_and_publish(self, item_id, **_kwargs):
            return item_id

    repository = Repository()
    summary = run_public_content_sync(
        sources=(source,),
        session=Session(),
        repository=repository,
        resolver=lambda _host: ["1.1.1.1"],
        uploader=lambda *_args, **_kwargs: None,
    )

    assert summary["candidates"] == 2
    assert summary["published"] == 2
    assert len(repository.rows) == 2


def test_missing_legal_metadata_never_uploads_public_pdf():
    from config.public_content_sources import PublicContentSource
    from services.public_content import run_public_content_sync

    source = PublicContentSource(
        key="official-fixture",
        name="Official Fixture",
        source_type="official_document",
        discovery_url="https://official.example/doc",
        allowed_hosts=frozenset({"official.example"}),
        parser="official_document",
        can_publish_pdf=True,
    )
    markup = """
      <h1>Quyết định 1703/QĐ-UBND về Bình Dương</h1>
      <a href="/1703.pdf">Tải PDF</a>
    """

    class Response:
        status_code = 200

        def __init__(self, pdf=False):
            self.text = "" if pdf else markup
            self.headers = {
                "Content-Type": "application/pdf" if pdf else "text/html"
            }
            self.pdf = pdf

        def iter_content(self, _chunk_size):
            if self.pdf:
                yield b"%PDF-1.7\nfixture"

    class Session:
        @staticmethod
        def get(url, **_kwargs):
            return Response(pdf=url.endswith(".pdf"))

    class Repository:
        rows = []

        def upsert_candidate(self, candidate, *, status, status_reason):
            self.rows.append((status, status_reason))
            return 1

        def attach_pdf_and_publish(self, *_args, **_kwargs):
            raise AssertionError("missing metadata must never publish")

    uploads = []
    summary = run_public_content_sync(
        sources=(source,),
        session=Session(),
        repository=Repository(),
        resolver=lambda _host: ["1.1.1.1"],
        uploader=lambda *_args, **_kwargs: uploads.append(True),
    )

    assert uploads == []
    assert summary["published"] == 0
    assert summary["draft"] == 1


def test_publish_failure_keeps_new_immutable_pdf_for_safe_retry():
    from config.public_content_sources import PublicContentSource
    from services.public_content import run_public_content_sync

    source = PublicContentSource(
        key="official-fixture",
        name="Official Fixture",
        source_type="official_document",
        discovery_url="https://official.example/doc",
        allowed_hosts=frozenset({"official.example"}),
        parser="official_document",
        can_publish_pdf=True,
    )
    markup = """
      <h1>Quyết định 1703/QĐ-UBND về Bình Dương</h1>
      <p>Ngày 18 tháng 6 năm 2025, UBND tỉnh Bình Dương ban hành.</p>
      <a href="/1703.pdf">Tải PDF</a>
    """

    class Response:
        status_code = 200

        def __init__(self, pdf=False):
            self.text = "" if pdf else markup
            self.headers = {
                "Content-Type": "application/pdf" if pdf else "text/html"
            }
            self.pdf = pdf

        def iter_content(self, _chunk_size):
            if self.pdf:
                yield b"%PDF-1.7\nfixture"

    class Session:
        @staticmethod
        def get(url, **_kwargs):
            return Response(pdf=url.endswith(".pdf"))

    class Repository:
        def upsert_candidate(self, *_args, **_kwargs):
            return 1

        def attach_pdf_and_publish(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    uploaded = []
    deleted = []
    summary = run_public_content_sync(
        sources=(source,),
        session=Session(),
        repository=Repository(),
        resolver=lambda _host: ["1.1.1.1"],
        uploader=lambda _path, key, **_kwargs: uploaded.append(key),
    )

    assert len(uploaded) == 1
    assert deleted == []
    assert summary["published"] == 0
    assert summary["pdf_uploaded"] == 1


def test_publish_failure_keeps_preexisting_immutable_pdf_object():
    from config.public_content_sources import PublicContentSource
    from services.public_content import PdfUploadResult, run_public_content_sync

    source = PublicContentSource(
        key="official-fixture",
        name="Official Fixture",
        source_type="official_document",
        discovery_url="https://official.example/doc",
        allowed_hosts=frozenset({"official.example"}),
        parser="official_document",
        can_publish_pdf=True,
    )
    markup = """
      <h1>Quyết định 1703/QĐ-UBND về Bình Dương</h1>
      <p>Ngày 18 tháng 6 năm 2025, UBND tỉnh Bình Dương ban hành.</p>
      <a href="/1703.pdf">Tải PDF</a>
    """

    class Response:
        status_code = 200

        def __init__(self, pdf=False):
            self.text = "" if pdf else markup
            self.headers = {
                "Content-Type": "application/pdf" if pdf else "text/html"
            }
            self.pdf = pdf

        def iter_content(self, _chunk_size):
            if self.pdf:
                yield b"%PDF-1.7\nfixture"

    class Session:
        @staticmethod
        def get(url, **_kwargs):
            return Response(pdf=url.endswith(".pdf"))

    class Repository:
        def upsert_candidate(self, *_args, **_kwargs):
            return 1

        def attach_pdf_and_publish(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    deleted = []
    summary = run_public_content_sync(
        sources=(source,),
        session=Session(),
        repository=Repository(),
        resolver=lambda _host: ["1.1.1.1"],
        uploader=lambda _path, key, **_kwargs: PdfUploadResult(
            key, created=False
        ),
    )

    assert deleted == []
    assert summary["published"] == 0
    assert summary["pdf_uploaded"] == 0


def test_sync_keeps_invalid_official_pdf_draft_and_reports_source_error():
    from config.public_content_sources import PublicContentSource
    from services.public_content import run_public_content_sync

    source = PublicContentSource(
        key="official-fixture",
        name="Official Fixture",
        source_type="official_document",
        discovery_url="https://official.example/doc",
        allowed_hosts=frozenset({"official.example"}),
        parser="official_document",
        can_publish_pdf=True,
    )
    html = """
    <h1>Quyết định 1703/QĐ-UBND về khu vực Tân An</h1>
    <p>Ngày 18 tháng 6 năm 2025, UBND tỉnh Bình Dương ban hành văn bản.</p>
    <a href="https://official.example/1703.pdf">Tải PDF</a>
    """

    class Response:
        status_code = 200
        url = "https://official.example/doc"
        headers = {"Content-Type": "text/html"}
        text = html

        @staticmethod
        def iter_content(_chunk_size):
            yield b"<html>not pdf</html>"

    class Session:
        @staticmethod
        def get(url, **_kwargs):
            response = Response()
            if url.endswith(".pdf"):
                response.headers = {"Content-Type": "application/pdf"}
            return response

    class Repository:
        def __init__(self):
            self.rows = []

        def upsert_candidate(self, candidate, *, status, status_reason, **_kwargs):
            self.rows.append((candidate, status, status_reason))
            return len(self.rows)

        def attach_pdf_and_publish(self, *_args, **_kwargs):
            raise AssertionError("invalid PDF must never publish")

    repository = Repository()
    summary = run_public_content_sync(
        kind="official-document",
        sources=(source,),
        session=Session(),
        repository=repository,
        resolver=lambda _host: ["1.1.1.1"],
        uploader=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid PDF must never upload")
        ),
    )

    assert summary["sources"] == 1
    assert summary["published"] == 0
    assert summary["draft"] == 1
    assert summary["errors"] == 1
    assert repository.rows[-1][1:] == ("draft", "pdf_ingest_failed")


def test_cli_sync_initializes_schema_locks_and_prints_summary(
    monkeypatch, capsys
):
    from cli import public_content

    events = []

    class Lock:
        def __enter__(self):
            events.append("locked")

        def __exit__(self, *_args):
            events.append("unlocked")

    monkeypatch.setattr(
        public_content, "init_schema", lambda: events.append("schema")
    )
    monkeypatch.setattr(
        public_content, "advisory_lock", lambda name: Lock()
    )
    monkeypatch.setattr(
        public_content,
        "run_public_content_sync",
        lambda **kwargs: {"kind": kwargs["kind"], "published": 2},
    )

    result = public_content.cmd_public_content_sync(
        type("Args", (), {"kind": "all"})()
    )

    assert events == ["schema", "locked", "unlocked"]
    assert result["published"] == 2
    assert '"published": 2' in capsys.readouterr().out


def test_public_content_schema_is_closed_and_indexed():
    import db.schema as schema

    class RecordingConn:
        def __init__(self):
            self.executed = []

        def execute(self, sql, params=None):
            self.executed.append(sql)

    conn = RecordingConn()
    schema._migrate_public_content_items(conn)
    sql = "\n".join(conn.executed)

    assert "CREATE TABLE IF NOT EXISTS public_content_items" in sql
    assert "item_type IN ('hot_topic', 'legal_document')" in sql
    assert "status IN ('draft', 'published')" in sql
    assert "UNIQUE (slug)" in sql
    assert "UNIQUE (canonical_url)" in sql
    assert "UNIQUE (fingerprint)" in sql
    assert "idx_public_content_status_date" in sql
    assert "idx_public_content_legal_filters" in sql
    assert "official_pdf_required" in sql


def test_public_content_table_participates_in_generated_id_adapter():
    from db.connection import _add_returning_id

    sql = _add_returning_id(
        "INSERT INTO public_content_items (slug) VALUES (?)"
    )

    assert sql.endswith("RETURNING id")


def test_repository_can_list_all_published_items_without_a_hidden_cap():
    from services.public_content import PostgresPublicContentRepository

    class Cursor:
        @staticmethod
        def fetchall():
            return []

    class Connection:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            return Cursor()

    class Context:
        def __init__(self, conn):
            self.conn = conn

        def __enter__(self):
            return self.conn

        def __exit__(self, *_args):
            return False

    connection = Connection()
    repository = PostgresPublicContentRepository(
        connection_factory=lambda: Context(connection)
    )

    assert repository.list_published(limit=None) == []
    sql, params = connection.calls[0]
    assert " LIMIT " not in sql
    assert params == ("published",)


def test_cli_registers_public_content_sync_contract():
    import radar

    parser = radar.build_parser()
    args = radar._parse_args(
        parser, ["public-content-sync", "--kind", "official-document"]
    )

    assert args.cmd == "public-content-sync"
    assert args.kind == "official-document"


def test_systemd_timer_runs_daily_at_0615():
    root = Path(__file__).resolve().parents[1]
    service = (
        root / "deployment/ubuntu24/radar-bds-public-content.service"
    ).read_text(encoding="utf-8")
    timer = (
        root / "deployment/ubuntu24/radar-bds-public-content.timer"
    ).read_text(encoding="utf-8")

    assert "radar.py public-content-sync --kind all" in service
    assert "OnCalendar=*-*-* 06:15:00 Asia/Ho_Chi_Minh" in timer
    assert "Persistent=true" in timer

"""Safe ingestion and persistence helpers for public news and legal documents."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import socket
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

from config.public_content_sources import PublicContentSource
from db.connection import get_conn
from services.s3_image_storage import (
    object_exists as s3_object_exists,
    s3_bucket,
    s3_client,
    s3_object_acl,
)


MAX_PDF_BYTES = 50 * 1024 * 1024
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}
ITEM_TYPES = {"hot_topic", "legal_document"}
ITEM_STATUSES = {"draft", "published"}


class PublicContentError(RuntimeError):
    pass


class UnsafeSourceUrl(PublicContentError):
    pass


class InvalidPdf(PublicContentError):
    pass


class UpsertResult(int):
    """Integer row id carrying a non-breaking created/updated outcome."""

    def __new__(cls, value: int, outcome: str):
        instance = int.__new__(cls, value)
        instance.outcome = outcome
        return instance


class PdfUploadResult(str):
    """Object key plus whether this sync created the immutable object."""

    def __new__(cls, value: str, *, created: bool):
        instance = str.__new__(cls, value)
        instance.created = bool(created)
        return instance


@dataclass(frozen=True)
class PdfAsset:
    sha256: str
    size_bytes: int
    content_type: str = "application/pdf"


@dataclass(frozen=True)
class PublicContentCandidate:
    item_type: str
    slug: str
    title: str
    summary: str
    source_key: str
    source_name: str
    source_url: str
    canonical_url: str
    topic: str
    published_at: datetime | None
    document_number: str = ""
    issuing_authority: str = ""
    document_type: str = ""
    document_scope: str = ""
    pdf_source_url: str = ""

    @property
    def fingerprint(self) -> str:
        basis = "|".join(
            (
                self.item_type,
                _fold_text(self.title),
                self.published_at.date().isoformat()
                if self.published_at
                else "",
                _fold_text(self.document_number),
            )
        )
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", str(value or ""))
    return "".join(
        char
        for char in normalized.casefold()
        if unicodedata.category(char) != "Mn"
    )


def safe_slug(value: str) -> str:
    folded = _fold_text(value).replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:180]


def normalize_content_url(raw_url: str) -> str:
    parsed = urlsplit(str(raw_url or "").strip())
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise UnsafeSourceUrl("https source URL required")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise UnsafeSourceUrl("source URL credentials and custom ports are forbidden")
    host = parsed.hostname.casefold().rstrip(".")
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in TRACKING_QUERY_KEYS
    ]
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def _default_resolver(host: str) -> list[str]:
    return list(
        {
            item[4][0]
            for item in socket.getaddrinfo(
                host,
                443,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        }
    )


def validate_source_url(
    raw_url: str,
    *,
    allowed_hosts: Iterable[str],
    resolver: Callable[[str], Iterable[str]] = _default_resolver,
) -> str:
    normalized = normalize_content_url(raw_url)
    parsed = urlsplit(normalized)
    host = (parsed.hostname or "").casefold().rstrip(".")
    allowed = {str(item).casefold().rstrip(".") for item in allowed_hosts}
    if host not in allowed:
        raise UnsafeSourceUrl("source host is not allowlisted")
    try:
        addresses = tuple(resolver(host))
    except OSError as exc:
        raise UnsafeSourceUrl("source host could not be resolved") from exc
    if not addresses:
        raise UnsafeSourceUrl("source host has no addresses")
    try:
        if any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise UnsafeSourceUrl("source host resolves to a non-public address")
    except ValueError as exc:
        raise UnsafeSourceUrl("source host returned an invalid address") from exc
    return normalized


def validate_pdf_payload(
    payload: bytes,
    *,
    content_type: str,
    declared_length: int | None = None,
    max_bytes: int = MAX_PDF_BYTES,
) -> PdfAsset:
    media_type = str(content_type or "").split(";", 1)[0].strip().casefold()
    if media_type != "application/pdf":
        raise InvalidPdf("unexpected PDF content type")
    if declared_length is not None and int(declared_length) > max_bytes:
        raise InvalidPdf("PDF exceeds the declared size limit")
    if len(payload) > max_bytes:
        raise InvalidPdf("PDF exceeds the streamed size limit")
    if not payload.startswith(b"%PDF-"):
        raise InvalidPdf("PDF magic bytes are missing")
    return PdfAsset(
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def read_limited_response(response, *, max_bytes: int = MAX_PDF_BYTES) -> bytes:
    headers = getattr(response, "headers", {}) or {}
    raw_length = headers.get("Content-Length") or headers.get("content-length")
    if raw_length:
        try:
            if int(raw_length) > max_bytes:
                raise InvalidPdf("PDF exceeds the declared size limit")
        except ValueError as exc:
            raise InvalidPdf("invalid PDF content length") from exc
    body = bytearray()
    for chunk in response.iter_content(64 * 1024):
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > max_bytes:
            raise InvalidPdf("PDF exceeds the streamed size limit")
    return bytes(body)


def pdf_object_key(year: int, slug: str, sha256: str) -> str:
    normalized_sha = str(sha256 or "").casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized_sha):
        raise ValueError("invalid PDF sha256")
    normalized_slug = safe_slug(slug)
    if not normalized_slug:
        raise ValueError("invalid PDF slug")
    return (
        f"public/legal-documents/{int(year):04d}/"
        f"{normalized_slug}-{normalized_sha}.pdf"
    )


def publication_decision(
    candidate: PublicContentCandidate,
    *,
    pdf: PdfAsset | None,
    official_pdf: bool,
) -> tuple[str, str]:
    if candidate.item_type not in ITEM_TYPES:
        return ("draft", "invalid_item_type")
    if not candidate.title.strip() or candidate.published_at is None:
        return ("draft", "required_metadata_missing")
    if candidate.item_type == "hot_topic":
        return ("published", "")
    required = (
        candidate.document_number,
        candidate.issuing_authority,
        candidate.document_type,
    )
    if not all(str(item or "").strip() for item in required):
        return ("draft", "legal_metadata_missing")
    if not official_pdf or pdf is None:
        return ("draft", "official_pdf_required")
    return ("published", "")


def upload_public_pdf(
    path: Path,
    object_key: str,
    *,
    download_name: str,
) -> PdfUploadResult:
    local_path = Path(path)
    if not local_path.is_file():
        raise FileNotFoundError(str(local_path))
    key = str(object_key or "").strip().replace("\\", "/").lstrip("/")
    if not key.startswith("public/legal-documents/") or not key.endswith(".pdf"):
        raise ValueError("invalid public PDF object key")
    if s3_object_exists(key):
        return PdfUploadResult(key, created=False)
    filename = safe_slug(Path(download_name).stem) + ".pdf"
    extra = {
        "Bucket": s3_bucket(),
        "Key": key,
        "Body": local_path.read_bytes(),
        "CacheControl": "public, max-age=31536000, immutable",
        "ContentType": "application/pdf",
        "ContentDisposition": f'inline; filename="{filename}"',
    }
    acl = s3_object_acl()
    if acl:
        extra["ACL"] = acl
    s3_client().put_object(**extra)
    return PdfUploadResult(key, created=True)


def delete_public_pdf(object_key: str) -> None:
    key = str(object_key or "").strip().replace("\\", "/").lstrip("/")
    if not key.startswith("public/legal-documents/") or not key.endswith(".pdf"):
        raise ValueError("invalid public PDF object key")
    s3_client().delete_object(Bucket=s3_bucket(), Key=key)


class _ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.articles: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.capture = ""
        self.buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "article":
            self.current = {}
        if self.current is None:
            return
        if tag == "a" and not self.current.get("href"):
            self.current["href"] = attributes.get("href", "")
        if tag == "time":
            self.current["datetime"] = attributes.get("datetime", "")
        if tag in {"h2", "h3", "p", "time"}:
            self.capture = tag
            self.buffer = []

    def handle_data(self, data):
        if self.current is not None and self.capture:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if tag == self.capture:
            value = re.sub(r"\s+", " ", "".join(self.buffer)).strip()
            if self.capture in {"h2", "h3"} and value:
                self.current.setdefault("title", value)
            elif self.capture == "p" and value:
                self.current.setdefault("summary", value)
            elif self.capture == "time" and value:
                self.current.setdefault("date_text", value)
            self.capture = ""
            self.buffer = []
        if tag == "article":
            if self.current.get("title") and self.current.get("href"):
                self.articles.append(self.current)
            self.current = None


def _parse_datetime(value: str) -> datetime | None:
    cleaned = re.sub(
        r"^(?:cập nhật|ngày đăng)\s*:\s*",
        "",
        str(value or "").strip(),
        flags=re.I,
    )
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for pattern in (
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %I:%M %p",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(cleaned, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_cafeland_topic(
    markup: str, source: PublicContentSource
) -> list[PublicContentCandidate]:
    parser = _ArticleParser()
    parser.feed(str(markup or ""))
    articles = list(parser.articles)
    if not articles:
        heading_pattern = re.compile(
            r"<h3\b[^>]*>\s*<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>"
            r"(.*?)</a>\s*</h3>(.*?)(?=<h3\b|$)",
            re.I | re.S,
        )
        for href, raw_title, tail in heading_pattern.findall(str(markup or "")):
            title = re.sub(r"<[^>]+>", " ", raw_title)
            summary_match = re.search(
                r"<p\b[^>]*>(.*?)</p>", tail, re.I | re.S
            )
            date_match = re.search(
                r"(?:Cập nhật\s*:\s*)?"
                r"(\d{1,2}/\d{1,2}/\d{4}"
                r"(?:\s+\d{1,2}:\d{2}(?:\s*[AP]M)?)?)",
                tail,
                re.I,
            )
            articles.append(
                {
                    "href": href,
                    "title": re.sub(r"\s+", " ", html.unescape(title)).strip(),
                    "summary": (
                        re.sub(
                            r"\s+",
                            " ",
                            html.unescape(
                                re.sub(
                                    r"<[^>]+>",
                                    " ",
                                    summary_match.group(1),
                                )
                            ),
                        ).strip()
                        if summary_match
                        else ""
                    ),
                    "date_text": date_match.group(1) if date_match else "",
                }
            )
    candidates = []
    for article in articles:
        title = html.unescape(article.get("title", "")).strip()
        canonical = normalize_content_url(
            urljoin(source.discovery_url, article.get("href", ""))
        )
        canonical_host = (urlsplit(canonical).hostname or "").casefold()
        if canonical_host not in {
            host.casefold() for host in source.allowed_hosts
        }:
            continue
        published_at = _parse_datetime(
            article.get("datetime") or article.get("date_text", "")
        )
        candidates.append(
            PublicContentCandidate(
                item_type="hot_topic",
                slug=safe_slug(title),
                title=title,
                summary=html.unescape(article.get("summary", "")).strip()[:500],
                source_key=source.key,
                source_name=source.name,
                source_url=canonical,
                canonical_url=canonical,
                topic="bat-dong-san-binh-duong",
                published_at=published_at,
            )
        )
    return candidates


def _page_text(markup: str) -> str:
    without_script = re.sub(
        r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>",
        " ",
        str(markup or ""),
        flags=re.I | re.S,
    )
    return re.sub(
        r"\s+",
        " ",
        html.unescape(re.sub(r"<[^>]+>", " ", without_script)),
    ).strip()


def parse_official_document_links(
    markup: str,
    source: PublicContentSource,
    *,
    page_url: str | None = None,
    limit: int = 50,
) -> list[str]:
    """Return bounded, unique detail links from an official index page."""

    base_url = page_url or source.discovery_url
    links = []
    seen = set()
    for href in re.findall(
        r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>",
        str(markup or ""),
        re.I,
    ):
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        try:
            candidate_url = normalize_content_url(urljoin(base_url, href))
        except UnsafeSourceUrl:
            continue
        host = (urlsplit(candidate_url).hostname or "").casefold().rstrip(".")
        if host not in source.allowed_hosts or candidate_url.casefold().endswith(".pdf"):
            continue
        folded = _fold_text(candidate_url)
        if not any(
            marker in folded
            for marker in (
                "van-ban",
                "quyet-dinh",
                "nghi-quyet",
                "document",
                "cong-bao",
            )
        ):
            continue
        if candidate_url == normalize_content_url(base_url) or candidate_url in seen:
            continue
        seen.add(candidate_url)
        links.append(candidate_url)
        if len(links) >= max(1, min(int(limit), 100)):
            break
    return links


def parse_legal_document_page(
    markup: str,
    source: PublicContentSource,
    *,
    page_url: str | None = None,
) -> list[PublicContentCandidate]:
    raw = str(markup or "")
    canonical_page_url = normalize_content_url(page_url or source.discovery_url)
    title_match = re.search(r"<h1\b[^>]*>(.*?)</h1>", raw, re.I | re.S)
    if not title_match:
        title_match = re.search(r"<title\b[^>]*>(.*?)</title>", raw, re.I | re.S)
    if not title_match:
        return []
    title = re.sub(
        r"\s+",
        " ",
        html.unescape(re.sub(r"<[^>]+>", " ", title_match.group(1))),
    ).strip()
    page_text = _page_text(raw)
    number_match = re.search(
        r"\b(\d{1,5}/(?:QĐ|QD|NQ|KH|TB)-[A-ZÀ-Ỹ0-9Đ]+)\b",
        page_text,
        re.I,
    )
    if not number_match:
        return []
    document_number = number_match.group(1).upper().replace("/QD-", "/QĐ-")
    authority_match = re.search(
        r"(UBND\s+(?:tỉnh|thành phố)\s+"
        r"[A-ZÀ-Ỹ][^,.;<]{0,80}?)(?=\s+(?:đã\s+)?ban hành|[,.;<])",
        page_text,
        re.I,
    )
    issuing_authority = (
        re.sub(r"\s+", " ", authority_match.group(1)).strip()
        if authority_match
        else ""
    )
    date_match = re.search(
        r"Ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
        page_text,
        re.I,
    )
    published_at = None
    if date_match:
        published_at = datetime(
            int(date_match.group(3)),
            int(date_match.group(2)),
            int(date_match.group(1)),
            tzinfo=timezone.utc,
        )
    description_match = re.search(
        r"<meta\b[^>]*(?:name=[\"']description[\"'][^>]*content|"
        r"content=[\"']([^\"']*)[\"'][^>]*name=[\"']description[\"'])"
        r"=[\"']([^\"']*)[\"']",
        raw,
        re.I,
    )
    if description_match:
        summary = next(
            (
                value.strip()
                for value in description_match.groups()
                if value and value.strip()
            ),
            "",
        )
    else:
        summary = page_text[:500]
    pdf_matches = re.findall(
        r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>",
        raw,
        re.I,
    )
    pdf_source_url = next(
        (
            normalize_content_url(urljoin(canonical_page_url, href))
            for href in pdf_matches
            if ".pdf" in href.casefold()
        ),
        "",
    )
    scope_match = re.search(
        r"\b(Tân An|Thủ Dầu Một|Dĩ An|Thuận An|Bến Cát|Bình Dương)\b",
        title,
        re.I,
    )
    slug = safe_slug(f"{document_number}-{title}")[:180]
    return [
        PublicContentCandidate(
            item_type="legal_document",
            slug=slug,
            title=title,
            summary=summary[:500],
            source_key=source.key,
            source_name=source.name,
            source_url=canonical_page_url,
            canonical_url=canonical_page_url,
            topic="quyet-dinh-van-ban",
            published_at=published_at,
            document_number=document_number,
            issuing_authority=issuing_authority,
            document_type=(
                "Quyết định"
                if document_number.split("/", 1)[1].startswith("QĐ-")
                else "Văn bản"
            ),
            document_scope=scope_match.group(1) if scope_match else "",
            pdf_source_url=pdf_source_url,
        )
    ]


def public_pdf_url(object_key: str) -> str:
    from services.s3_image_storage import s3_public_base_url

    base = s3_public_base_url()
    if not base:
        return ""
    return f"{base}/{quote(object_key, safe='/-_.~')}"


class PostgresPublicContentRepository:
    """Small repository with parameterized SQL and short transactions."""

    def __init__(self, connection_factory=get_conn):
        self._connection_factory = connection_factory
        self._should_ensure_schema = connection_factory is get_conn
        self._schema_ready = False

    def _ensure_schema(self) -> None:
        if not self._should_ensure_schema or self._schema_ready:
            return
        from db.schema import init_schema

        init_schema()
        self._schema_ready = True

    def list_published(
        self,
        *,
        item_type: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[dict]:
        safe_offset = max(int(offset), 0)
        clauses = ["status = ?"]
        params: list[object] = ["published"]
        if item_type:
            if item_type not in ITEM_TYPES:
                return []
            clauses.append("item_type = ?")
            params.append(item_type)
        sql = (
            "SELECT * FROM public_content_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY published_at DESC, id DESC"
        )
        if limit is not None:
            safe_limit = min(max(int(limit), 1), 5000)
            params.extend((safe_limit, safe_offset))
            sql += " LIMIT ? OFFSET ?"
        elif safe_offset:
            params.append(safe_offset)
            sql += " OFFSET ?"
        try:
            self._ensure_schema()
            with self._connection_factory() as conn:
                rows = conn.execute(sql, tuple(params)).fetchall()
        except Exception:
            return []
        return [dict(row.items()) for row in rows]

    def upsert_candidate(
        self,
        candidate: PublicContentCandidate,
        *,
        status: str,
        status_reason: str,
    ) -> int:
        if status not in ITEM_STATUSES:
            raise ValueError("invalid public content status")
        update_values = (
            status,
            status,
            status,
            str(status_reason or "")[:120],
            candidate.item_type,
            candidate.slug,
            candidate.title,
            candidate.summary,
            candidate.source_key,
            candidate.source_name,
            candidate.source_url,
            candidate.canonical_url,
            candidate.topic,
            candidate.published_at,
            candidate.fingerprint,
            candidate.document_number,
            candidate.issuing_authority,
            candidate.document_type,
            candidate.document_scope,
            candidate.pdf_source_url,
            candidate.canonical_url,
            candidate.fingerprint,
            candidate.slug,
        )
        update_sql = """
            UPDATE public_content_items SET
                status = CASE WHEN status = 'published' AND ? = 'draft' THEN status ELSE ? END,
                status_reason = CASE WHEN status = 'published' AND ? = 'draft' THEN status_reason ELSE ? END,
                item_type = ?,
                slug = ?,
                title = ?,
                summary = ?,
                source_key = ?,
                source_name = ?,
                source_url = ?,
                canonical_url = ?,
                topic = ?,
                published_at = ?,
                fingerprint = ?,
                document_number = ?,
                issuing_authority = ?,
                document_type = ?,
                document_scope = ?,
                pdf_source_url = ?,
                last_seen_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE canonical_url = ? OR fingerprint = ? OR slug = ?
            RETURNING id
        """

        insert_values = (
            candidate.item_type,
            status,
            str(status_reason or "")[:120],
            candidate.slug,
            candidate.title,
            candidate.summary,
            candidate.source_key,
            candidate.source_name,
            candidate.source_url,
            candidate.canonical_url,
            candidate.topic,
            candidate.published_at,
            candidate.fingerprint,
            candidate.document_number,
            candidate.issuing_authority,
            candidate.document_type,
            candidate.document_scope,
            candidate.pdf_source_url,
        )
        insert_sql = """
            INSERT INTO public_content_items (
                item_type, status, status_reason, slug, title, summary,
                source_key, source_name, source_url, canonical_url, topic,
                published_at, fingerprint, document_number,
                issuing_authority, document_type, document_scope,
                pdf_source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            RETURNING id
        """
        self._ensure_schema()
        with self._connection_factory() as conn:
            cursor = conn.execute(update_sql, update_values)
            if getattr(cursor, "rowcount", -1) > 1:
                raise PublicContentError(
                    "candidate keys match multiple public content rows"
                )
            if cursor.lastrowid is not None:
                return UpsertResult(cursor.lastrowid, "updated")
            cursor = conn.execute(insert_sql, insert_values)
            if cursor.lastrowid is not None:
                return UpsertResult(cursor.lastrowid, "created")
            cursor = conn.execute(update_sql, update_values)
            if getattr(cursor, "rowcount", -1) > 1:
                raise PublicContentError(
                    "candidate keys match multiple public content rows"
                )
            if cursor.lastrowid is not None:
                return UpsertResult(cursor.lastrowid, "updated")
        raise PublicContentError("public content upsert did not return an id")

    def attach_pdf_and_publish(
        self,
        item_id: int,
        *,
        candidate: PublicContentCandidate,
        asset: PdfAsset,
        object_key: str,
    ) -> None:
        self._ensure_schema()
        with self._connection_factory() as conn:
            cursor = conn.execute(
                """
                UPDATE public_content_items
                SET status = 'published',
                    status_reason = '',
                    document_number = ?,
                    issuing_authority = ?,
                    document_type = ?,
                    document_scope = ?,
                    pdf_source_url = ?,
                    pdf_object_key = ?,
                    pdf_sha256 = ?,
                    pdf_size_bytes = ?,
                    pdf_content_type = ?,
                    pdf_uploaded_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND item_type = 'legal_document'
                """,
                (
                    candidate.document_number,
                    candidate.issuing_authority,
                    candidate.document_type,
                    candidate.document_scope,
                    candidate.pdf_source_url,
                    object_key,
                    asset.sha256,
                    asset.size_bytes,
                    asset.content_type,
                    int(item_id),
                ),
            )
            if cursor.rowcount != 1:
                raise PublicContentError("legal document publish update failed")

    def get_published_by_slug(self, slug: str) -> dict | None:
        normalized = safe_slug(slug)
        if not normalized:
            return None
        try:
            self._ensure_schema()
            with self._connection_factory() as conn:
                row = conn.execute(
                    "SELECT * FROM public_content_items "
                    "WHERE slug = ? AND status = 'published' LIMIT 1",
                    (normalized,),
                ).fetchone()
        except Exception:
            return None
        return dict(row.items()) if row else None


def _safe_get(
    session,
    url: str,
    *,
    source: PublicContentSource,
    resolver,
    stream: bool,
):
    current = url
    for _redirect in range(4):
        safe_url = validate_source_url(
            current,
            allowed_hosts=source.allowed_hosts,
            resolver=resolver,
        )
        response = session.get(
            safe_url,
            timeout=(5, 20),
            allow_redirects=False,
            stream=stream,
            headers={
                "User-Agent": (
                    "RadarBDS-PublicContent/1.0 "
                    "(+https://radarbds.vn/tin-tuc)"
                )
            },
        )
        status = int(getattr(response, "status_code", 0))
        if status in {301, 302, 303, 307, 308}:
            location = (getattr(response, "headers", {}) or {}).get("Location")
            if not location:
                raise PublicContentError("redirect response has no location")
            current = urljoin(safe_url, location)
            continue
        if status != 200:
            raise PublicContentError(f"source returned HTTP {status}")
        return response
    raise PublicContentError("source exceeded redirect limit")


def run_public_content_sync(
    *,
    kind: str = "all",
    sources: tuple[PublicContentSource, ...] | None = None,
    session=None,
    repository: PostgresPublicContentRepository | None = None,
    resolver: Callable[[str], Iterable[str]] = _default_resolver,
    uploader=upload_public_pdf,
) -> dict:
    from config.public_content_sources import public_content_sources_for

    if sources is None:
        sources = public_content_sources_for(kind)
    if session is None:
        import requests

        session = requests.Session()
    repository = repository or PostgresPublicContentRepository()
    summary = {
        "kind": kind,
        "sources": len(sources),
        "candidates": 0,
        "created": 0,
        "updated": 0,
        "published": 0,
        "draft": 0,
        "pdf_uploaded": 0,
        "errors": 0,
        "errors_by_source": {},
    }
    for source in sources:
        try:
            response = _safe_get(
                session,
                source.discovery_url,
                source=source,
                resolver=resolver,
                stream=False,
            )
            if source.parser == "cafeland_topic":
                candidates = parse_cafeland_topic(response.text, source)
            elif source.parser == "official_document":
                candidates = parse_legal_document_page(
                    response.text,
                    source,
                    page_url=source.discovery_url,
                )
                detail_links = parse_official_document_links(
                    response.text,
                    source,
                    page_url=source.discovery_url,
                )
                for detail_url in detail_links:
                    try:
                        detail_response = _safe_get(
                            session,
                            detail_url,
                            source=source,
                            resolver=resolver,
                            stream=False,
                        )
                        candidates.extend(
                            parse_legal_document_page(
                                detail_response.text,
                                source,
                                page_url=detail_url,
                            )
                        )
                    except Exception:
                        summary["errors"] += 1
                        summary["errors_by_source"][source.key] = (
                            summary["errors_by_source"].get(source.key, 0) + 1
                        )
            else:
                candidates = parse_legal_document_page(response.text, source)
        except Exception:
            summary["errors"] += 1
            summary["errors_by_source"][source.key] = (
                summary["errors_by_source"].get(source.key, 0) + 1
            )
            continue
        candidates = list(
            {
                (candidate.canonical_url, candidate.fingerprint): candidate
                for candidate in candidates
            }.values()
        )
        for candidate in candidates:
            summary["candidates"] += 1
            status, reason = publication_decision(
                candidate,
                pdf=None,
                official_pdf=False,
            )
            if candidate.item_type == "hot_topic":
                try:
                    upsert_result = repository.upsert_candidate(
                        candidate,
                        status=status,
                        status_reason=reason,
                    )
                    outcome = getattr(upsert_result, "outcome", "updated")
                    summary[outcome] = summary.get(outcome, 0) + 1
                    summary[status] += 1
                except Exception:
                    summary["errors"] += 1
                    summary["errors_by_source"][source.key] = (
                        summary["errors_by_source"].get(source.key, 0) + 1
                    )
                continue
            try:
                item_id = repository.upsert_candidate(
                    candidate,
                    status="draft",
                    status_reason=reason or "pdf_pending",
                )
                outcome = getattr(item_id, "outcome", "updated")
                summary[outcome] = summary.get(outcome, 0) + 1
            except Exception:
                summary["errors"] += 1
                summary["errors_by_source"][source.key] = (
                    summary["errors_by_source"].get(source.key, 0) + 1
                )
                continue
            if not source.can_publish_pdf or not candidate.pdf_source_url:
                summary["draft"] += 1
                continue
            try:
                pdf_response = _safe_get(
                    session,
                    candidate.pdf_source_url,
                    source=source,
                    resolver=resolver,
                    stream=True,
                )
                payload = read_limited_response(pdf_response)
                headers = getattr(pdf_response, "headers", {}) or {}
                raw_length = headers.get("Content-Length")
                asset = validate_pdf_payload(
                    payload,
                    content_type=headers.get("Content-Type", ""),
                    declared_length=int(raw_length) if raw_length else None,
                )
                publish_status, publish_reason = publication_decision(
                    candidate,
                    pdf=asset,
                    official_pdf=source.can_publish_pdf,
                )
                if publish_status != "published":
                    repository.upsert_candidate(
                        candidate,
                        status="draft",
                        status_reason=publish_reason,
                    )
                    summary["draft"] += 1
                    continue
                year = candidate.published_at.year if candidate.published_at else 0
                key = pdf_object_key(year, candidate.slug, asset.sha256)
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                        suffix=".pdf", delete=False
                    ) as handle:
                        handle.write(payload)
                        temp_path = Path(handle.name)
                    upload_result = uploader(
                        temp_path,
                        key,
                        download_name=f"{candidate.slug}.pdf",
                    )
                    if getattr(upload_result, "created", True):
                        summary["pdf_uploaded"] += 1
                finally:
                    if temp_path is not None:
                        temp_path.unlink(missing_ok=True)
                repository.attach_pdf_and_publish(
                    item_id,
                    candidate=candidate,
                    asset=asset,
                    object_key=key,
                )
                summary["published"] += 1
            except Exception:
                try:
                    repository.upsert_candidate(
                        candidate,
                        status="draft",
                        status_reason="pdf_ingest_failed",
                    )
                except Exception:
                    pass
                summary["draft"] += 1
                summary["errors"] += 1
                summary["errors_by_source"][source.key] = (
                    summary["errors_by_source"].get(source.key, 0) + 1
                )
    return summary

"""Validate and import curated local Radar Ask knowledge documents.

This command never fetches a URL. Canonical URLs are citation metadata and
must pass a small trust-class-specific HTTPS allowlist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from uuid import UUID, NAMESPACE_URL, uuid5

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config.settings  # noqa: F401  # load project-local environment
from db.connection import get_conn


TRUST_CLASSES = frozenset({"official", "radar_method", "editorial"})
TRUSTED_SOURCE_HOSTS = {
    "official": frozenset(
        {
            "congbao.hochiminhcity.gov.vn",
            "hochiminhcity.gov.vn",
            "vanban.chinhphu.vn",
            "vbpl.vn",
            "moc.gov.vn",
        }
    ),
    "radar_method": frozenset({"radarbds.vn", "www.radarbds.vn"}),
    "editorial": frozenset({"radarbds.vn", "www.radarbds.vn"}),
}
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_DOCUMENT_CHARS = 1_000_000
MAX_CHUNK_CHARS = 1_600
MAX_CHUNKS = 2_000


@dataclass(frozen=True)
class SourceDefinition:
    source_id: UUID
    slug: str
    title: str
    canonical_url: str
    trust_class: str
    jurisdiction: str


@dataclass(frozen=True)
class ChunkDefinition:
    chunk_id: UUID
    chunk_index: int
    text: str
    normalized_text: str
    token_count: int
    content_sha256: str


@dataclass(frozen=True)
class ValidatedDocument:
    document_id: UUID
    source_slug: str
    title: str
    version: str
    published_at: date | None
    effective_from: date | None
    effective_to: date | None
    content: str
    content_sha256: str
    chunks: tuple[ChunkDefinition, ...]

    @property
    def chunk_ids(self) -> tuple[UUID, ...]:
        return tuple(chunk.chunk_id for chunk in self.chunks)


@dataclass(frozen=True)
class ImportResult:
    document_id: UUID
    chunk_ids: tuple[UUID, ...]
    inserted_chunks: int
    supersedes_document_id: UUID | None


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "").lower().replace("đ", "d")
    ascii_text = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_text)).strip()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iso_date(value: Any, *, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def validate_source_definition(payload: Mapping[str, Any]) -> SourceDefinition:
    slug = str(payload.get("slug") or "").strip().lower()
    title = " ".join(str(payload.get("title") or "").split())
    canonical_url = str(payload.get("canonical_url") or "").strip()
    trust_class = str(payload.get("trust_class") or "").strip().lower()
    jurisdiction = " ".join(str(payload.get("jurisdiction") or "").split())
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", slug):
        raise ValueError("source slug is invalid")
    if not title or len(title) > 300:
        raise ValueError("source title is invalid")
    if trust_class not in TRUST_CLASSES:
        raise ValueError("source trust_class is invalid")
    if not jurisdiction or len(jurisdiction) > 160:
        raise ValueError("source jurisdiction is invalid")
    parsed = urlparse(canonical_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("source canonical URL must be a credential-free HTTPS URL")
    if parsed.hostname.lower() not in TRUSTED_SOURCE_HOSTS[trust_class]:
        raise ValueError("source canonical URL host is not on the trust-class allowlist")
    return SourceDefinition(
        source_id=uuid5(NAMESPACE_URL, f"radar-ask-source:{slug}:{canonical_url}"),
        slug=slug,
        title=title,
        canonical_url=canonical_url,
        trust_class=trust_class,
        jurisdiction=jurisdiction,
    )


def _split_long_paragraph(paragraph: str) -> list[str]:
    words = paragraph.split()
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for word in words:
        added = len(word) + (1 if current else 0)
        if current and current_size + added > MAX_CHUNK_CHARS:
            chunks.append(" ".join(current))
            current = [word]
            current_size = len(word)
        else:
            current.append(word)
            current_size += added
    if current:
        chunks.append(" ".join(current))
    return chunks


def _chunk_text(content: str) -> list[str]:
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", content)
        if paragraph.strip()
    ]
    chunks: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= MAX_CHUNK_CHARS:
            chunks.append(paragraph)
        else:
            chunks.extend(_split_long_paragraph(paragraph))
    if not chunks or len(chunks) > MAX_CHUNKS:
        raise ValueError("document must produce between 1 and 2000 chunks")
    return chunks


def validate_document_payload(payload: Mapping[str, Any]) -> ValidatedDocument:
    source_slug = str(payload.get("source_slug") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", source_slug):
        raise ValueError("document source_slug is invalid")
    embedded_source = payload.get("source")
    if embedded_source is not None:
        if not isinstance(embedded_source, Mapping):
            raise ValueError("embedded source must be an object")
        source = validate_source_definition(embedded_source)
        if source.slug != source_slug:
            raise ValueError("embedded source slug does not match source_slug")
    title = " ".join(str(payload.get("title") or "").split())
    version = " ".join(str(payload.get("version") or "").split())
    if not title or len(title) > 500:
        raise ValueError("document title is invalid")
    if not version or len(version) > 120:
        raise ValueError("document version is invalid")
    published_at = _iso_date(payload.get("published_at"), field="published_at")
    effective_from = _iso_date(payload.get("effective_from"), field="effective_from")
    effective_to = _iso_date(payload.get("effective_to"), field="effective_to")
    if effective_from and effective_to and effective_to < effective_from:
        raise ValueError("effective_to cannot be before effective_from")
    content = str(payload.get("content") or "").replace("\r\n", "\n").strip()
    if not content or len(content) > MAX_DOCUMENT_CHARS:
        raise ValueError("document content is empty or too large")
    content_sha256 = _sha256(content)
    document_id = uuid5(
        NAMESPACE_URL,
        f"radar-ask-document:{source_slug}:{content_sha256}",
    )
    chunks = []
    for index, text in enumerate(_chunk_text(content)):
        chunk_hash = _sha256(text)
        chunks.append(
            ChunkDefinition(
                chunk_id=uuid5(document_id, f"chunk:{index}:{chunk_hash}"),
                chunk_index=index,
                text=text,
                normalized_text=_fold(text),
                token_count=max(1, len(text.split())),
                content_sha256=chunk_hash,
            )
        )
    return ValidatedDocument(
        document_id=document_id,
        source_slug=source_slug,
        title=title,
        version=version,
        published_at=published_at,
        effective_from=effective_from,
        effective_to=effective_to,
        content=content,
        content_sha256=content_sha256,
        chunks=tuple(chunks),
    )


def _parse_markdown(path: Path, text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        raise ValueError("Markdown knowledge files require simple YAML front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("Markdown knowledge front matter is not closed")
    metadata: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError("Markdown front matter entries must use key: value")
        metadata[key.strip()] = value.strip().strip('"').strip("'") or None
    metadata["content"] = text[end + 5 :].strip()
    return metadata


def load_document_file(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if resolved.suffix.lower() not in {".json", ".md", ".markdown"}:
        raise ValueError("knowledge file must be JSON or Markdown")
    if not resolved.is_file() or resolved.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("knowledge file is missing or too large")
    text = resolved.read_text(encoding="utf-8")
    if resolved.suffix.lower() == ".json":
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("knowledge JSON root must be an object")
        return payload
    return _parse_markdown(resolved, text)


def register_source(conn, payload: Mapping[str, Any]) -> UUID:
    source = validate_source_definition(payload)
    existing = conn.execute(
        "SELECT id, canonical_url, trust_class FROM knowledge_sources WHERE slug=?",
        (source.slug,),
    ).fetchone()
    if existing is not None and (
        str(existing["canonical_url"]) != source.canonical_url
        or str(existing["trust_class"]) != source.trust_class
    ):
        raise ValueError("source slug is already bound to different trust metadata")
    conn.execute(
        """
        INSERT INTO knowledge_sources (
            id, slug, title, canonical_url, trust_class, jurisdiction
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (slug) DO UPDATE SET
            title=EXCLUDED.title,
            jurisdiction=EXCLUDED.jurisdiction,
            active=TRUE,
            updated_at=NOW()
        """,
        (
            source.source_id,
            source.slug,
            source.title,
            source.canonical_url,
            source.trust_class,
            source.jurisdiction,
        ),
    )
    return source.source_id


def import_document_payload(conn, payload: Mapping[str, Any]) -> ImportResult:
    document = validate_document_payload(payload)
    source = conn.execute(
        """
        SELECT id, canonical_url, trust_class
        FROM knowledge_sources
        WHERE slug=? AND active
        LIMIT 1
        """,
        (document.source_slug,),
    ).fetchone()
    if source is None:
        raise ValueError("source_slug must already exist as an active curated source")
    # Revalidate DB-owned citation metadata on every import.
    validate_source_definition(
        {
            "slug": document.source_slug,
            "title": "registered source",
            "canonical_url": source["canonical_url"],
            "trust_class": source["trust_class"],
            "jurisdiction": "registered jurisdiction",
        }
    )
    existing = conn.execute(
        """
        SELECT id, supersedes_document_id, title, version,
               published_at, effective_from, effective_to
        FROM knowledge_documents
        WHERE source_id=? AND content_sha256=?
        LIMIT 1
        """,
        (source["id"], document.content_sha256),
    ).fetchone()
    if existing is not None:
        existing_metadata = (
            str(existing["title"]),
            str(existing["version"]),
            existing["published_at"],
            existing["effective_from"],
            existing["effective_to"],
        )
        requested_metadata = (
            document.title,
            document.version,
            document.published_at,
            document.effective_from,
            document.effective_to,
        )
        if existing_metadata != requested_metadata:
            raise ValueError(
                "document content already exists with different immutable metadata"
            )
        rows = conn.execute(
            "SELECT id FROM knowledge_chunks WHERE document_id=? ORDER BY chunk_index",
            (existing["id"],),
        ).fetchall()
        return ImportResult(
            document_id=existing["id"],
            chunk_ids=tuple(row["id"] for row in rows),
            inserted_chunks=0,
            supersedes_document_id=existing["supersedes_document_id"],
        )

    version_match = conn.execute(
        """
        SELECT id, content_sha256
        FROM knowledge_documents
        WHERE source_id=? AND version=?
        LIMIT 1
        """,
        (source["id"], document.version),
    ).fetchone()
    if version_match is not None:
        raise ValueError("document version is already bound to different content")

    # One source slug/canonical URL represents one versioned document lineage.
    previous = conn.execute(
        """
        SELECT id FROM knowledge_documents
        WHERE source_id=? AND is_current
        ORDER BY imported_at DESC, id DESC
        LIMIT 1
        """,
        (source["id"],),
    ).fetchone()
    previous_id = previous["id"] if previous is not None else None
    conn.execute(
        "UPDATE knowledge_documents SET is_current=FALSE WHERE source_id=? AND is_current",
        (source["id"],),
    )
    conn.execute(
        """
        INSERT INTO knowledge_documents (
            id, source_id, title, version, published_at,
            effective_from, effective_to, content_sha256,
            document_text, is_current, supersedes_document_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?)
        """,
        (
            document.document_id,
            source["id"],
            document.title,
            document.version,
            document.published_at,
            document.effective_from,
            document.effective_to,
            document.content_sha256,
            document.content,
            previous_id,
        ),
    )
    conn.executemany(
        """
        INSERT INTO knowledge_chunks (
            id, document_id, chunk_index, chunk_text,
            normalized_text, token_count, content_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                chunk.chunk_id,
                document.document_id,
                chunk.chunk_index,
                chunk.text,
                chunk.normalized_text,
                chunk.token_count,
                chunk.content_sha256,
            )
            for chunk in document.chunks
        ],
    )
    return ImportResult(
        document_id=document.document_id,
        chunk_ids=document.chunk_ids,
        inserted_chunks=len(document.chunks),
        supersedes_document_id=previous_id,
    )


def _summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    document = validate_document_payload(payload)
    source = payload.get("source")
    if source is not None:
        validate_source_definition(source)
    return {
        "ok": True,
        "source_slug": document.source_slug,
        "document_id": str(document.document_id),
        "content_sha256": document.content_sha256,
        "chunk_count": len(document.chunks),
        "rejected_documents": 0,
        "rejected_chunks": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "register-source", "import"):
        command = subparsers.add_parser(name)
        command.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    payload = load_document_file(args.path)
    if args.command == "validate":
        print(json.dumps(_summary(payload), ensure_ascii=False, sort_keys=True))
        return 0
    with get_conn() as conn:
        if args.command == "register-source":
            source_payload = payload.get("source")
            if not isinstance(source_payload, Mapping):
                raise ValueError("document file must contain a source object")
            source_id = register_source(conn, source_payload)
            result = {"ok": True, "source_id": str(source_id)}
        else:
            imported = import_document_payload(conn, payload)
            result = {
                "ok": True,
                "document_id": str(imported.document_id),
                "inserted_chunks": imported.inserted_chunks,
                "supersedes_document_id": str(imported.supersedes_document_id)
                if imported.supersedes_document_id
                else None,
            }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

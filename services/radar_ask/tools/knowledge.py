"""Curated official-price and PostgreSQL full-text knowledge retrieval."""
from __future__ import annotations

import os
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..contracts import EvidenceItem, SourceKind
from ..evidence import EvidenceBuilder, stable_evidence_id
from ..registry import (
    OfficialLandPriceArgs,
    SearchOfficialDocumentsArgs,
    ToolContext,
)
from .entities import _as_of, _read_context, _row_dict
from .valuation import _configure_timeout, _number, _settings


TRUST_KIND = {
    "official": SourceKind.OFFICIAL_DOCUMENT,
    "radar_method": SourceKind.RADAR_METHOD,
    "editorial": SourceKind.EDITORIAL,
}
VECTOR_MODEL_DIMENSIONS = {
    "intfloat/multilingual-e5-small": 384,
    "BAAI/bge-m3": 1024,
}
VECTOR_CONTRACT_VERSION = "radar-ask-vector-v1"


class VectorRetrievalNotReady(RuntimeError):
    """Raised when an explicitly enabled vector path fails its readiness gate."""


@dataclass(frozen=True)
class RankedChunk:
    chunk_id: str
    rank: int
    payload: Mapping[str, Any] = field(default_factory=dict)
    score: float = 0.0

    def __post_init__(self) -> None:
        if not self.chunk_id or self.rank < 1:
            raise ValueError("ranked chunk requires a non-empty ID and positive rank")


def fuse_ranked_results(
    *,
    fts: list[RankedChunk],
    semantic: list[RankedChunk],
    limit: int,
    rank_constant: int = 60,
) -> list[RankedChunk]:
    """Fuse bounded lexical/semantic ranks without weakening exact chunk IDs."""
    if not 1 <= int(limit) <= 10:
        raise ValueError("fused result limit must be between 1 and 10")
    if rank_constant < 1:
        raise ValueError("RRF rank constant must be positive")
    scores: dict[str, float] = {}
    payloads: dict[str, Mapping[str, Any]] = {}
    best_rank: dict[str, int] = {}
    for ranked_list in (fts, semantic):
        seen: set[str] = set()
        for item in ranked_list[:10]:
            if item.chunk_id in seen:
                continue
            seen.add(item.chunk_id)
            scores[item.chunk_id] = scores.get(item.chunk_id, 0.0) + 1.0 / (
                rank_constant + item.rank
            )
            payloads.setdefault(item.chunk_id, item.payload)
            best_rank[item.chunk_id] = min(
                item.rank,
                best_rank.get(item.chunk_id, item.rank),
            )
    ordered_ids = sorted(
        scores,
        key=lambda chunk_id: (
            -scores[chunk_id],
            best_rank[chunk_id],
            chunk_id,
        ),
    )[:limit]
    return [
        RankedChunk(
            chunk_id=chunk_id,
            rank=index,
            payload=payloads[chunk_id],
            score=scores[chunk_id],
        )
        for index, chunk_id in enumerate(ordered_ids, start=1)
    ]


def _vector_environment() -> tuple[Path, str, int]:
    raw_path = os.getenv("RADAR_ASK_KNOWLEDGE_VECTOR_MODEL_PATH", "").strip()
    model_id = os.getenv("RADAR_ASK_KNOWLEDGE_VECTOR_MODEL_ID", "").strip()
    raw_dimension = os.getenv("RADAR_ASK_KNOWLEDGE_VECTOR_DIMENSION", "").strip()
    if not raw_path or not model_id or not raw_dimension:
        raise VectorRetrievalNotReady("vector model readiness settings are incomplete")
    try:
        dimension = int(raw_dimension)
    except ValueError as exc:
        raise VectorRetrievalNotReady("vector model dimension is invalid") from exc
    if VECTOR_MODEL_DIMENSIONS.get(model_id) != dimension:
        raise VectorRetrievalNotReady("vector model readiness settings are invalid")
    return Path(raw_path).expanduser().resolve(), model_id, dimension


@lru_cache(maxsize=2)
def _load_local_encoder(model_path: str):
    path = Path(model_path)
    if not path.is_dir() or not (
        (path / "modules.json").is_file() or (path / "config.json").is_file()
    ):
        raise VectorRetrievalNotReady("local vector model assets are missing")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise VectorRetrievalNotReady(
            "sentence-transformers retrieval dependency is not installed"
        ) from exc
    try:
        return SentenceTransformer(
            str(path),
            local_files_only=True,
            trust_remote_code=False,
        )
    except Exception as exc:  # pragma: no cover - model-library specific
        raise VectorRetrievalNotReady("local vector model could not be loaded") from exc


@dataclass
class SemanticRetriever:
    conn: Any
    encoder: Any
    model_id: str
    dimension: int

    @classmethod
    def from_environment(cls, conn) -> "SemanticRetriever":
        model_path, model_id, dimension = _vector_environment()
        try:
            readiness_cursor = conn.execute(
                "SELECT * FROM public.radar_ask_vector_readiness()"
            )
            readiness = _row_dict(readiness_cursor, readiness_cursor.fetchone())
        except Exception as exc:
            raise VectorRetrievalNotReady(
                "database vector readiness check failed"
            ) from exc
        if (
            not readiness
            or not bool(readiness.get("extension_ready"))
            or not bool(readiness.get("index_ready"))
            or str(readiness.get("model_id") or "") != model_id
            or int(readiness.get("dimension") or 0) != dimension
            or str(readiness.get("contract_version") or "")
            != VECTOR_CONTRACT_VERSION
            or int(readiness.get("embedded_chunks") or 0)
            != int(readiness.get("total_chunks") or -1)
            or int(readiness.get("total_chunks") or 0) < 1
        ):
            raise VectorRetrievalNotReady("database vector readiness gate did not pass")
        return cls(
            conn=conn,
            encoder=_load_local_encoder(str(model_path)),
            model_id=model_id,
            dimension=dimension,
        )

    def search(self, query: str, *, limit: int) -> list[RankedChunk]:
        bounded_limit = min(max(int(limit), 1), 10)
        encoded_query = (
            f"query: {query}"
            if self.model_id == "intfloat/multilingual-e5-small"
            else query
        )
        try:
            encoded = self.encoder.encode(
                [encoded_query],
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0]
            vector = [float(value) for value in encoded]
        except Exception as exc:
            raise VectorRetrievalNotReady("semantic query encoding failed") from exc
        if len(vector) != self.dimension:
            raise VectorRetrievalNotReady("semantic query vector dimension mismatched")
        if not all(math.isfinite(value) for value in vector):
            raise VectorRetrievalNotReady("semantic query vector is not finite")
        vector_literal = "[" + ",".join(f"{value:.9g}" for value in vector) + "]"
        try:
            cursor = self.conn.execute(
                """
                SELECT *
                FROM public.radar_ask_semantic_search(%s::vector, %s, %s)
                """,
                (vector_literal, self.model_id, bounded_limit),
            )
            rows = _rows(cursor)
        except Exception as exc:
            raise VectorRetrievalNotReady("semantic database query failed") from exc
        return [
            RankedChunk(
                chunk_id=str(row["chunk_id"]),
                rank=rank,
                payload=row,
                score=float(row.get("rank") or 0.0),
            )
            for rank, row in enumerate(rows, start=1)
        ]


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "").lower().replace("đ", "d")
    ascii_text = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_text)).strip()


def _rows(cursor) -> list[dict[str, Any]]:
    return [_row_dict(cursor, raw) for raw in cursor.fetchall()]


def _lexical_pattern(query: str) -> str:
    tokens = [token for token in _fold(query).split() if len(token) >= 2][:20]
    return "%" + "%".join(tokens) + "%" if tokens else "%"


def _knowledge_item(row: Mapping[str, Any]) -> EvidenceItem:
    chunk_id = str(row["chunk_id"])
    trust_class = str(row.get("trust_class") or "editorial")
    version = str(row.get("version") or "unknown")
    imported_at = _as_of(
        row.get("imported_at")
        or row.get("effective_from")
        or row.get("published_at")
    )
    dataset_version = f"knowledge:{version}:{chunk_id}"
    source_ref = f"knowledge:{chunk_id}"
    return EvidenceItem(
        evidence_id=stable_evidence_id(
            TRUST_KIND.get(trust_class, SourceKind.EDITORIAL).value,
            source_ref,
            dataset_version,
        ),
        source_kind=TRUST_KIND.get(trust_class, SourceKind.EDITORIAL),
        source_ref=source_ref,
        value={
            "chunk_ref": source_ref,
            "chunk_index": int(row.get("chunk_index") or 0),
            "text": str(row.get("chunk_text") or ""),
            "document_title": str(row.get("document_title") or ""),
            "document_version": version,
            "published_at": str(row.get("published_at") or "") or None,
            "effective_from": str(row.get("effective_from") or "") or None,
            "effective_to": str(row.get("effective_to") or "") or None,
            "source_title": str(row.get("source_title") or ""),
            "trust_class": trust_class,
            "jurisdiction": str(row.get("jurisdiction") or ""),
            "retrieval_rank": _number(row.get("rank")),
        },
        calculation_method="postgres_fts_simple_with_accent_folded_lexical_fallback",
        as_of=imported_at,
        dataset_version=dataset_version,
        provenance={
            "source_url": str(row.get("source_url") or ""),
            "source_slug": str(row.get("source_slug") or ""),
            "trust_class": trust_class,
            "jurisdiction": str(row.get("jurisdiction") or ""),
            "chunk_id": chunk_id,
        },
    )


def _search_rows(
    conn,
    *,
    query: str,
    limit: int,
    marker: str = "knowledge_search",
    source_url: str | None = None,
) -> list[dict[str, Any]]:
    cursor = conn.execute(
        f"""
        /* radar_ask:{marker} */
        WITH query_terms AS (
            SELECT websearch_to_tsquery('simple', %s) AS query
        )
        SELECT k.chunk_id, k.chunk_index, k.chunk_text,
               k.document_title, k.version, k.published_at,
               k.effective_from, k.effective_to, k.imported_at,
               k.source_slug, k.source_title, k.source_url,
               k.trust_class, k.jurisdiction,
               GREATEST(
                   ts_rank_cd(k.search_vector, query_terms.query),
                   CASE WHEN k.normalized_text LIKE %s THEN 0.05 ELSE 0 END
               )::double precision AS rank
        FROM public.radar_ask_v_knowledge_chunks k
        CROSS JOIN query_terms
        WHERE (
                k.search_vector @@ query_terms.query
                OR k.normalized_text LIKE %s
              )
          AND (k.effective_from IS NULL OR k.effective_from<=CURRENT_DATE)
          AND (k.effective_to IS NULL OR k.effective_to>=CURRENT_DATE)
          AND (CAST(%s AS text) IS NULL OR k.source_url=%s)
        ORDER BY CASE k.trust_class
                     WHEN 'official' THEN 0
                     WHEN 'radar_method' THEN 1
                     ELSE 2
                 END,
                 rank DESC,
                 COALESCE(k.effective_from,k.published_at) DESC NULLS LAST,
                 k.source_slug,
                 k.chunk_index
        LIMIT %s
        """,
        (
            query,
            _lexical_pattern(query),
            _lexical_pattern(query),
            source_url,
            source_url,
            limit,
        ),
    )
    return _rows(cursor)


def search_official_documents(
    *,
    args: SearchOfficialDocumentsArgs,
    context: ToolContext,
):
    question = f"curated knowledge {args.query}"
    settings = _settings()
    limit = min(args.limit, settings.evidence_row_limit, 10)
    vector_warning: str | None = None
    retrieval_method = "postgres_fts_simple_plus_accent_folded_lexical"
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        rows = _search_rows(conn, query=args.query, limit=limit)
        if settings.knowledge_vector_enabled:
            try:
                semantic = SemanticRetriever.from_environment(conn).search(
                    args.query,
                    limit=limit,
                )
                lexical = [
                    RankedChunk(
                        chunk_id=str(row["chunk_id"]),
                        rank=rank,
                        payload=row,
                        score=float(row.get("rank") or 0.0),
                    )
                    for rank, row in enumerate(rows, start=1)
                ]
                rows = [
                    dict(item.payload)
                    for item in fuse_ranked_results(
                        fts=lexical,
                        semantic=semantic,
                        limit=limit,
                    )
                ]
                retrieval_method = "postgres_fts_plus_local_semantic_rrf"
            except VectorRetrievalNotReady:
                vector_warning = "semantic_retrieval_unavailable_using_fts"
    if not rows:
        missing_builder = EvidenceBuilder(question_snapshot=question).missing(
            "curated_document_evidence_not_found"
        )
        if vector_warning:
            missing_builder.warn(vector_warning)
        return missing_builder.build()
    builder = (
        EvidenceBuilder(question_snapshot=question, row_limit=limit)
        .calculate(
            retrieval=retrieval_method,
            result_count=len(rows),
            trust_classes=sorted({str(row.get("trust_class")) for row in rows}),
        )
    )
    if vector_warning:
        builder.warn(vector_warning)
    for row in rows:
        builder.add(_knowledge_item(row))
    return builder.build()


def lookup_official_land_price(
    *,
    args: OfficialLandPriceArgs,
    context: ToolContext,
):
    question = f"official land price {args.street}, {args.area}"
    settings = _settings()
    area_pattern = f"%{_fold(args.area).replace(' ', '%')}%"
    street_pattern = f"%{_fold(args.street).replace(' ', '%')}%"
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        cursor = conn.execute(
            """
            /* radar_ask:official_land_price */
            SELECT row_key, area, appendix, stt, street,
                   segment_from, segment_to, residential,
                   commerce_service, production_business, page,
                   source_title, source_url, data_as_of, unit
            FROM public.radar_ask_v_official_land_prices
            WHERE (
                    LOWER(area)=LOWER(%s)
                    OR search_text LIKE %s
                  )
              AND (
                    LOWER(street)=LOWER(%s)
                    OR search_text LIKE %s
                  )
              AND (
                    CAST(%s AS text) IS NULL
                    OR LOWER(segment_from || ' ' || segment_to)
                       LIKE LOWER('%%' || %s || '%%')
                  )
            ORDER BY CASE WHEN LOWER(area)=LOWER(%s) THEN 0 ELSE 1 END,
                     CASE WHEN LOWER(street)=LOWER(%s) THEN 0 ELSE 1 END,
                     page NULLS LAST,
                     stt
            LIMIT 10
            """,
            (
                args.area,
                area_pattern,
                args.street,
                street_pattern,
                args.segment,
                args.segment,
                args.area,
                args.street,
            ),
        )
        rows = _rows(cursor)
        source_urls = {
            str(row.get("source_url") or "")
            for row in rows
            if str(row.get("source_url") or "").startswith("https://")
        }
        governing_rows = (
            _search_rows(
                conn,
                query="bảng giá đất mục đích áp dụng",
                limit=1,
                marker="governing_document",
                source_url=next(iter(source_urls)),
            )
            if len(source_urls) == 1
            else []
        )
    if not rows:
        return (
            EvidenceBuilder(question_snapshot=question)
            .missing("official_land_price_row_not_found")
            .build()
        )
    builder = (
        EvidenceBuilder(
            question_snapshot=question,
            row_limit=min(settings.evidence_row_limit, len(rows) + len(governing_rows)),
        )
        .resolve(area=args.area, street=args.street, segment=args.segment)
        .warn("official_land_price_is_not_market_transaction_or_radar_fair_value")
        .calculate(
            price_semantics="official_land_price_not_market_or_fair_value",
            matched_rows=len(rows),
        )
    )
    for row in rows:
        row_key = str(row["row_key"])
        as_of = _as_of(row.get("data_as_of"))
        version = f"official-land-price:{as_of.date().isoformat()}:{row_key}"
        source_ref = f"official-land-price:{row_key}"
        builder.add(
            EvidenceItem(
                evidence_id=stable_evidence_id("official_price", source_ref, version),
                source_kind=SourceKind.OFFICIAL_PRICE,
                source_ref=source_ref,
                value={
                    "area": row.get("area"),
                    "street": row.get("street"),
                    "segment_from": row.get("segment_from"),
                    "segment_to": row.get("segment_to"),
                    "official_residential_price_thousand_vnd_per_m2": _number(
                        row.get("residential")
                    ),
                    "official_commerce_service_price_thousand_vnd_per_m2": _number(
                        row.get("commerce_service")
                    ),
                    "official_production_business_price_thousand_vnd_per_m2": _number(
                        row.get("production_business")
                    ),
                    "price_semantics": "official_land_price_not_market_or_fair_value",
                    "source_title": row.get("source_title"),
                    "page": int(row["page"]) if row.get("page") is not None else None,
                },
                unit=str(row.get("unit") or "thousand_vnd_per_m2"),
                calculation_method="curated_official_land_price_table_lookup",
                as_of=as_of,
                dataset_version=version,
                provenance={
                    "source_url": str(row.get("source_url") or ""),
                    "row_key": row_key,
                    "method": "curated_official_table_exact_or_folded_match",
                },
            )
        )
    for row in governing_rows:
        builder.add(_knowledge_item(row))
    return builder.build()

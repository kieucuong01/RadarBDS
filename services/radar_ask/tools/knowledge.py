"""Curated official-price and PostgreSQL full-text knowledge retrieval."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import date
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
    with _read_context(context) as conn:
        _configure_timeout(conn, settings)
        rows = _search_rows(conn, query=args.query, limit=limit)
    if not rows:
        return (
            EvidenceBuilder(question_snapshot=question)
            .missing("curated_document_evidence_not_found")
            .build()
        )
    builder = (
        EvidenceBuilder(question_snapshot=question, row_limit=limit)
        .calculate(
            retrieval="postgres_fts_simple_plus_accent_folded_lexical",
            result_count=len(rows),
            trust_classes=sorted({str(row.get("trust_class")) for row in rows}),
        )
    )
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

"""Owner-only pgvector migration and offline embedding backfill for Radar Ask.

Normal application startup must never call this module. ``apply`` is an
explicit maintenance action and refuses remote model names: model assets must
already exist at ``--model-path``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config.settings  # noqa: F401


ALLOWED_MODEL_DIMENSIONS = {
    "intfloat/multilingual-e5-small": 384,
    "BAAI/bge-m3": 1024,
}
READ_ROLE = "radar_ask_ro"
VECTOR_INDEX = "idx_knowledge_chunks_embedding_hnsw"
VECTOR_CONTRACT_VERSION = "radar-ask-vector-v1"


@dataclass(frozen=True)
class VectorReadinessReport:
    ok: bool
    extension_ready: bool
    knowledge_view_ready: bool
    vector_column_ready: bool
    index_ready: bool
    functions_ready: bool
    contract_version: str
    model_id: str
    dimension: int
    embedded_chunks: int
    total_chunks: int
    violations: tuple[str, ...]


def validate_model_id(value: str) -> str:
    model_id = str(value or "").strip()
    if model_id not in ALLOWED_MODEL_DIMENSIONS:
        raise ValueError("model ID is not an approved benchmark candidate")
    return model_id


def validate_dimension(model_id: str, value: int) -> int:
    expected = ALLOWED_MODEL_DIMENSIONS[validate_model_id(model_id)]
    try:
        dimension = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("vector dimension is invalid") from exc
    if dimension != expected:
        raise ValueError(
            f"vector dimension must be {expected} for the selected model"
        )
    return dimension


def build_semantic_function_sql() -> str:
    return """
    CREATE OR REPLACE FUNCTION public.radar_ask_semantic_search(
        query_embedding vector,
        expected_model_id text,
        max_rows integer
    )
    RETURNS TABLE (
        chunk_id uuid,
        chunk_index integer,
        chunk_text text,
        document_title text,
        version text,
        published_at date,
        effective_from date,
        effective_to date,
        imported_at timestamptz,
        source_slug text,
        source_title text,
        source_url text,
        trust_class text,
        jurisdiction text,
        rank double precision
    )
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path=pg_catalog,public
    AS $$
        SELECT c.id AS chunk_id,
               c.chunk_index,
               c.chunk_text,
               d.title AS document_title,
               d.version,
               d.published_at,
               d.effective_from,
               d.effective_to,
               d.imported_at,
               s.slug AS source_slug,
               s.title AS source_title,
               s.canonical_url AS source_url,
               s.trust_class,
               s.jurisdiction,
               (1 - (c.embedding <=> query_embedding))::double precision AS rank
        FROM public.knowledge_chunks c
        JOIN public.knowledge_documents d ON d.id=c.document_id
        JOIN public.knowledge_sources s ON s.id=d.source_id
        JOIN public.radar_ask_vector_metadata metadata ON metadata.singleton
        WHERE c.embedding IS NOT NULL
          AND c.embedding_model_id=expected_model_id
          AND metadata.model_id=expected_model_id
          AND s.active
          AND (d.effective_from IS NULL OR d.effective_from<=CURRENT_DATE)
          AND (d.effective_to IS NULL OR d.effective_to>=CURRENT_DATE)
          AND NOT EXISTS (
              SELECT 1
              FROM public.knowledge_documents newer
              WHERE newer.source_id=d.source_id
                AND (newer.effective_from IS NULL OR newer.effective_from<=CURRENT_DATE)
                AND (newer.effective_to IS NULL OR newer.effective_to>=CURRENT_DATE)
                AND (
                    COALESCE(newer.effective_from, DATE '-infinity')
                        > COALESCE(d.effective_from, DATE '-infinity')
                    OR (
                        COALESCE(newer.effective_from, DATE '-infinity')
                            = COALESCE(d.effective_from, DATE '-infinity')
                        AND newer.imported_at>d.imported_at
                    )
                    OR (
                        COALESCE(newer.effective_from, DATE '-infinity')
                            = COALESCE(d.effective_from, DATE '-infinity')
                        AND newer.imported_at=d.imported_at
                        AND newer.id::text>d.id::text
                    )
                )
          )
        ORDER BY c.embedding <=> query_embedding, c.id
        LIMIT LEAST(GREATEST(COALESCE(max_rows, 1), 1), 10)
    $$
    """


def build_readiness_function_sql() -> str:
    return f"""
    CREATE OR REPLACE FUNCTION public.radar_ask_vector_readiness()
    RETURNS TABLE (
        extension_ready boolean,
        index_ready boolean,
        model_id text,
        dimension integer,
        contract_version text,
        embedded_chunks bigint,
        total_chunks bigint
    )
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path=pg_catalog,public
    AS $$
        SELECT EXISTS (
                   SELECT 1 FROM pg_catalog.pg_extension WHERE extname='vector'
               ) AS extension_ready,
               to_regclass('public.{VECTOR_INDEX}') IS NOT NULL AS index_ready,
               metadata.model_id,
               metadata.dimension,
               metadata.contract_version,
               COUNT(*) FILTER (
                   WHERE chunks.embedding IS NOT NULL
                     AND chunks.embedding_model_id=metadata.model_id
               ) AS embedded_chunks,
               COUNT(chunks.id) AS total_chunks
        FROM public.radar_ask_vector_metadata metadata
        LEFT JOIN public.knowledge_chunks chunks ON TRUE
        WHERE metadata.singleton
        GROUP BY metadata.model_id, metadata.dimension, metadata.contract_version
    $$
    """


def _row_mapping(cursor, row) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    names = [getattr(item, "name", item[0]) for item in cursor.description or ()]
    return dict(zip(names, row, strict=True))


def check_vector_readiness(
    conn,
    *,
    model_id: str,
    dimension: int,
) -> VectorReadinessReport:
    model_id = validate_model_id(model_id)
    dimension = validate_dimension(model_id, dimension)
    violations: list[str] = []
    extension_ready = bool(
        conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
        ).fetchone()[0]
    )
    if not extension_ready:
        violations.append("pgvector extension is missing")
    role_ready = bool(
        conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=%s)",
            (READ_ROLE,),
        ).fetchone()[0]
    )
    view_ready = bool(
        conn.execute(
            "SELECT to_regclass('public.radar_ask_v_knowledge_chunks') IS NOT NULL"
        ).fetchone()[0]
    )
    knowledge_view_ready = bool(
        role_ready
        and view_ready
        and conn.execute(
            """
            SELECT has_table_privilege(
                %s, 'public.radar_ask_v_knowledge_chunks', 'SELECT'
            )
            """,
            (READ_ROLE,),
        ).fetchone()[0]
    )
    if not knowledge_view_ready:
        violations.append("knowledge phase safe view/read grant is not ready")
    knowledge_relation_ready = bool(
        conn.execute(
            "SELECT to_regclass('public.knowledge_chunks') IS NOT NULL"
        ).fetchone()[0]
    )
    if not knowledge_relation_ready:
        violations.append("knowledge_chunks relation is missing")
    column_row = (
        conn.execute(
            """
            SELECT format_type(attribute.atttypid, attribute.atttypmod)
            FROM pg_attribute attribute
            WHERE attribute.attrelid=to_regclass('public.knowledge_chunks')
              AND attribute.attname='embedding'
              AND NOT attribute.attisdropped
            """
        ).fetchone()
        if knowledge_relation_ready
        else None
    )
    vector_column_ready = bool(
        column_row and str(column_row[0]).lower() == f"vector({dimension})"
    )
    if not vector_column_ready:
        violations.append("knowledge chunk vector column/dimension is not ready")
    index_cursor = conn.execute(
        """
        SELECT access_method.amname,
               index_meta.indisvalid,
               index_meta.indisready,
               pg_get_indexdef(index_relation.oid)
        FROM pg_class index_relation
        JOIN pg_namespace namespace ON namespace.oid=index_relation.relnamespace
        JOIN pg_index index_meta ON index_meta.indexrelid=index_relation.oid
        JOIN pg_class table_relation ON table_relation.oid=index_meta.indrelid
        JOIN pg_am access_method ON access_method.oid=index_relation.relam
        WHERE namespace.nspname='public'
          AND index_relation.relname=%s
          AND table_relation.relname='knowledge_chunks'
        """,
        (VECTOR_INDEX,),
    )
    index_row = index_cursor.fetchone()
    index_definition = str(index_row[3] if index_row else "").lower()
    index_ready = bool(
        index_row
        and str(index_row[0]).lower() == "hnsw"
        and bool(index_row[1])
        and bool(index_row[2])
        and "(embedding vector_cosine_ops)" in index_definition
        and "embedding is not null" in index_definition
    )
    if not index_ready:
        violations.append("knowledge vector HNSW/cosine index contract is not ready")

    function_rows: dict[tuple[str, str], dict[str, Any]] = {}
    if role_ready and knowledge_relation_ready:
        function_cursor = conn.execute(
            """
            SELECT procedure.proname,
                   oidvectortypes(procedure.proargtypes) AS argument_types,
                   procedure.prosecdef,
                   owner.rolname AS owner_name,
                   procedure.proconfig,
                   procedure.prosrc,
                   has_function_privilege(%s, procedure.oid, 'EXECUTE') AS read_execute,
                   EXISTS (
                       SELECT 1
                       FROM aclexplode(
                           COALESCE(
                               procedure.proacl,
                               acldefault('f', procedure.proowner)
                           )
                       ) privilege
                       WHERE privilege.grantee=0
                         AND privilege.privilege_type='EXECUTE'
                   ) AS public_execute,
                   has_table_privilege(
                       owner.rolname, 'public.knowledge_chunks', 'SELECT'
                   ) AS owner_can_read_chunks
            FROM pg_proc procedure
            JOIN pg_namespace namespace ON namespace.oid=procedure.pronamespace
            JOIN pg_roles owner ON owner.oid=procedure.proowner
            WHERE namespace.nspname='public'
              AND procedure.proname=ANY(%s::text[])
            """,
            (
                READ_ROLE,
                ["radar_ask_vector_readiness", "radar_ask_semantic_search"],
            ),
        )
        for raw_row in function_cursor.fetchall():
            row = _row_mapping(function_cursor, raw_row)
            function_rows[(str(row["proname"]), str(row["argument_types"]))] = row

    expected_functions = {
        ("radar_ask_vector_readiness", ""): (
            VECTOR_INDEX,
            "metadata.contract_version",
            "count(*) filter",
        ),
        ("radar_ask_semantic_search", "vector, text, integer"): (
            "coalesce(max_rows, 1)",
            "embedding <=> query_embedding",
            "metadata.model_id=expected_model_id",
        ),
    }
    functions_ready = True
    for signature, required_fragments in expected_functions.items():
        row = function_rows.get(signature)
        config = "".join(str(value) for value in (row or {}).get("proconfig") or [])
        normalized_config = config.lower().replace(" ", "")
        source = str((row or {}).get("prosrc") or "").lower().replace(" ", "")
        if (
            not row
            or not bool(row.get("prosecdef"))
            or str(row.get("owner_name") or "") in {READ_ROLE, "radar_ask_view_owner"}
            or "search_path=pg_catalog,public" not in normalized_config
            or not bool(row.get("read_execute"))
            or bool(row.get("public_execute"))
            or not bool(row.get("owner_can_read_chunks"))
            or not all(
                fragment.lower().replace(" ", "") in source
                for fragment in required_fragments
            )
        ):
            functions_ready = False
    if not functions_ready:
        violations.append("knowledge vector function signature/security contract is not ready")

    metadata: dict[str, Any] = {}
    embedded_chunks = 0
    total_chunks = (
        int(conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0])
        if knowledge_relation_ready
        else 0
    )
    metadata_relation_ready = conn.execute(
        "SELECT to_regclass('public.radar_ask_vector_metadata') IS NOT NULL"
    ).fetchone()[0]
    metadata_contract_ready = bool(
        metadata_relation_ready
        and conn.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='radar_ask_vector_metadata'
                  AND column_name='contract_version'
            )
            """
        ).fetchone()[0]
    )
    if metadata_contract_ready:
        cursor = conn.execute(
            """
            SELECT model_id, dimension, contract_version
            FROM radar_ask_vector_metadata
            WHERE singleton
            LIMIT 1
            """
        )
        metadata = _row_mapping(cursor, cursor.fetchone())
        if vector_column_ready and knowledge_relation_ready:
            embedded_chunks = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM knowledge_chunks
                    WHERE embedding IS NOT NULL AND embedding_model_id=%s
                    """,
                    (model_id,),
                ).fetchone()[0]
            )
    if (
        str(metadata.get("model_id") or "") != model_id
        or int(metadata.get("dimension") or 0) != dimension
        or str(metadata.get("contract_version") or "") != VECTOR_CONTRACT_VERSION
    ):
        violations.append("active vector model/dimension/contract metadata does not match")
    if embedded_chunks != total_chunks:
        violations.append("knowledge vector embedding coverage is incomplete")
    if total_chunks < 1:
        violations.append("knowledge vector corpus is empty")
    return VectorReadinessReport(
        ok=not violations,
        extension_ready=extension_ready,
        knowledge_view_ready=knowledge_view_ready,
        vector_column_ready=vector_column_ready,
        index_ready=index_ready,
        functions_ready=functions_ready,
        contract_version=str(metadata.get("contract_version") or ""),
        model_id=model_id,
        dimension=dimension,
        embedded_chunks=embedded_chunks,
        total_chunks=total_chunks,
        violations=tuple(violations),
    )


def _owner_database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not parsed.hostname
        or not parsed.path.strip("/")
        or parsed.username == READ_ROLE
    ):
        raise ValueError("DATABASE_URL must be a PostgreSQL owner connection")
    return value


def _load_model(model_path: Path):
    if not model_path.is_dir() or not (
        (model_path / "modules.json").is_file()
        or (model_path / "config.json").is_file()
    ):
        raise ValueError("--model-path must contain pre-downloaded model assets")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("install requirements-radar-ask-retrieval.txt first") from exc
    return SentenceTransformer(
        str(model_path.resolve()),
        local_files_only=True,
        trust_remote_code=False,
    )


def _vector_literal(values) -> str:
    normalized = [float(value) for value in values]
    if not normalized or not all(math.isfinite(value) for value in normalized):
        raise ValueError("model returned an empty or non-finite vector")
    return "[" + ",".join(f"{value:.9g}" for value in normalized) + "]"


def apply_vector_migration(
    conn,
    *,
    model,
    model_id: str,
    dimension: int,
) -> VectorReadinessReport:
    model_id = validate_model_id(model_id)
    dimension = validate_dimension(model_id, dimension)
    probe = model.encode(
        ["Radar BDS vector dimension probe"],
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]
    if len(probe) != dimension:
        raise ValueError("local model output dimension does not match --dimension")
    if not conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=%s)",
        (READ_ROLE,),
    ).fetchone()[0]:
        raise ValueError("radar_ask_ro role must be configured before vector migration")
    knowledge_view_exists = bool(
        conn.execute(
            "SELECT to_regclass('public.radar_ask_v_knowledge_chunks') IS NOT NULL"
        ).fetchone()[0]
    )
    knowledge_view_granted = bool(
        knowledge_view_exists
        and conn.execute(
            """
            SELECT has_table_privilege(
                %s, 'public.radar_ask_v_knowledge_chunks', 'SELECT'
            )
            """,
            (READ_ROLE,),
        ).fetchone()[0]
    )
    if not knowledge_view_granted:
        raise ValueError(
            "Radar Ask knowledge phase must be configured before vector migration"
        )

    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public.radar_ask_vector_metadata (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
            model_id TEXT NOT NULL,
            dimension INTEGER NOT NULL CHECK (dimension BETWEEN 64 AND 4096),
            contract_version TEXT NOT NULL,
            embedded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        ALTER TABLE public.radar_ask_vector_metadata
        ADD COLUMN IF NOT EXISTS contract_version TEXT
        """
    )
    conn.execute(
        """
        UPDATE public.radar_ask_vector_metadata
        SET contract_version=%s
        WHERE contract_version IS NULL
        """,
        (VECTOR_CONTRACT_VERSION,),
    )
    conn.execute(
        """
        ALTER TABLE public.radar_ask_vector_metadata
        ALTER COLUMN contract_version SET NOT NULL
        """
    )
    column_row = conn.execute(
        """
        SELECT format_type(attribute.atttypid, attribute.atttypmod)
        FROM pg_attribute attribute
        WHERE attribute.attrelid='public.knowledge_chunks'::regclass
          AND attribute.attname='embedding'
          AND NOT attribute.attisdropped
        """
    ).fetchone()
    if column_row and str(column_row[0]).lower() != f"vector({dimension})":
        raise ValueError("existing embedding column has a different vector dimension")
    if not column_row:
        conn.execute(
            f"ALTER TABLE public.knowledge_chunks ADD COLUMN embedding vector({dimension})"
        )
    conn.execute(
        "ALTER TABLE public.knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_model_id TEXT"
    )

    rows = conn.execute(
        "SELECT id, chunk_text FROM public.knowledge_chunks ORDER BY id"
    ).fetchall()
    for offset in range(0, len(rows), 64):
        batch = rows[offset : offset + 64]
        texts = [str(row[1]) for row in batch]
        if model_id == "intfloat/multilingual-e5-small":
            texts = [f"passage: {text}" for text in texts]
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        for row, vector in zip(batch, vectors, strict=True):
            if len(vector) != dimension:
                raise ValueError("model returned an inconsistent vector dimension")
            conn.execute(
                """
                UPDATE public.knowledge_chunks
                SET embedding=%s::vector, embedding_model_id=%s
                WHERE id=%s
                """,
                (_vector_literal(vector), model_id, row[0]),
            )
    conn.execute(
        """
        INSERT INTO public.radar_ask_vector_metadata (
            singleton, model_id, dimension, contract_version, embedded_at
        ) VALUES (TRUE, %s, %s, %s, NOW())
        ON CONFLICT (singleton) DO UPDATE SET
            model_id=EXCLUDED.model_id,
            dimension=EXCLUDED.dimension,
            contract_version=EXCLUDED.contract_version,
            embedded_at=NOW()
        """,
        (model_id, dimension, VECTOR_CONTRACT_VERSION),
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {VECTOR_INDEX}
        ON public.knowledge_chunks
        USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
        """
    )
    conn.execute(build_readiness_function_sql())
    conn.execute(build_semantic_function_sql())
    for signature in (
        "public.radar_ask_vector_readiness()",
        "public.radar_ask_semantic_search(vector,text,integer)",
    ):
        conn.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        conn.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {READ_ROLE}")
    conn.execute("ANALYZE public.knowledge_chunks")
    return check_vector_readiness(
        conn,
        model_id=model_id,
        dimension=dimension,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "apply"))
    parser.add_argument("--model-id", required=True, choices=sorted(ALLOWED_MODEL_DIMENSIONS))
    parser.add_argument("--dimension", required=True, type=int)
    parser.add_argument("--model-path", type=Path)
    args = parser.parse_args(argv)
    model_id = validate_model_id(args.model_id)
    dimension = validate_dimension(model_id, args.dimension)
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required") from exc
    with psycopg.connect(_owner_database_url()) as conn:
        if args.action == "apply":
            if args.model_path is None:
                raise ValueError("apply requires --model-path with local model assets")
            report = apply_vector_migration(
                conn,
                model=_load_model(args.model_path),
                model_id=model_id,
                dimension=dimension,
            )
            if not report.ok:
                conn.rollback()
        else:
            report = check_vector_readiness(
                conn,
                model_id=model_id,
                dimension=dimension,
            )
            conn.rollback()
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

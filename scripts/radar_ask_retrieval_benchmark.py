"""Benchmark Radar Ask FTS and explicitly local semantic retrieval.

Semantic mode never resolves a model name over the network: ``--model-path``
must point to pre-downloaded assets and the Hugging Face clients are forced
offline before import.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import time
import tracemalloc
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config.settings  # noqa: F401
from services.radar_ask.tools.knowledge import RankedChunk, fuse_ranked_results


ALLOWED_CATEGORIES = frozenset(
    {
        "address_alias",
        "post_merger_ward",
        "legal_terminology",
        "official_land_price",
        "market_paraphrase",
        "exact_source",
    }
)
ALLOWED_TRUST_CLASSES = frozenset({"official", "radar_method", "editorial"})
ALLOWED_MODEL_IDS = frozenset({"intfloat/multilingual-e5-small", "BAAI/bge-m3"})
MAX_FIXTURE_BYTES = 2 * 1024 * 1024
MAX_QUERY_CHARS = 500
PRODUCTION_RETRIEVAL_LIMIT = 5
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.()-]*\d){8,10}(?!\d)")
URL_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)")


@dataclass(frozen=True)
class CorpusChunk:
    chunk_id: str
    trust_class: str
    text: str


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    category: str
    query: str
    accepted_chunk_ids: tuple[str, ...]
    required_trust_class: str


@dataclass(frozen=True)
class BenchmarkFixture:
    benchmark_version: str
    corpus: tuple[CorpusChunk, ...]
    cases: tuple[RetrievalCase, ...]
    raw: Mapping[str, Any]


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "").lower().replace("đ", "d")
    ascii_text = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_text)).strip()


def _safe_text(value: Any, *, field: str, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if not text or len(text) > maximum:
        raise ValueError(f"{field} is invalid")
    if PHONE_PATTERN.search(text) or URL_PATTERN.search(text):
        raise ValueError(f"{field} contains prohibited PII or URL data")
    return text


def load_benchmark_fixture(path: str | Path) -> BenchmarkFixture:
    resolved = Path(path).resolve()
    if not resolved.is_file() or resolved.stat().st_size > MAX_FIXTURE_BYTES:
        raise ValueError("benchmark fixture is missing or too large")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark fixture root must be an object")
    version = _safe_text(
        payload.get("benchmark_version"),
        field="benchmark_version",
        maximum=100,
    )
    raw_corpus = payload.get("corpus")
    raw_cases = payload.get("cases")
    if not isinstance(raw_corpus, list) or not 1 <= len(raw_corpus) <= 1_000:
        raise ValueError("benchmark corpus size is invalid")
    if not isinstance(raw_cases, list) or not 50 <= len(raw_cases) <= 2_000:
        raise ValueError("benchmark requires between 50 and 2000 cases")

    corpus: list[CorpusChunk] = []
    chunk_ids: set[str] = set()
    chunk_trust: dict[str, str] = {}
    for row in raw_corpus:
        if not isinstance(row, Mapping):
            raise ValueError("benchmark corpus row must be an object")
        chunk_id = _safe_text(row.get("chunk_id"), field="chunk_id", maximum=120)
        trust_class = str(row.get("trust_class") or "").strip()
        text = _safe_text(row.get("text"), field="corpus text", maximum=5_000)
        if chunk_id in chunk_ids or trust_class not in ALLOWED_TRUST_CLASSES:
            raise ValueError("benchmark corpus identity or trust class is invalid")
        chunk_ids.add(chunk_id)
        chunk_trust[chunk_id] = trust_class
        corpus.append(CorpusChunk(chunk_id=chunk_id, trust_class=trust_class, text=text))

    cases: list[RetrievalCase] = []
    case_ids: set[str] = set()
    for row in raw_cases:
        if not isinstance(row, Mapping):
            raise ValueError("benchmark case must be an object")
        case_id = _safe_text(row.get("id"), field="case id", maximum=120)
        category = str(row.get("category") or "").strip()
        query = _safe_text(row.get("query"), field="query", maximum=MAX_QUERY_CHARS)
        required_trust = str(row.get("required_trust_class") or "").strip()
        raw_accepted = row.get("accepted_chunk_ids")
        if (
            case_id in case_ids
            or category not in ALLOWED_CATEGORIES
            or required_trust not in ALLOWED_TRUST_CLASSES
            or not isinstance(raw_accepted, list)
            or not raw_accepted
        ):
            raise ValueError("benchmark case metadata is invalid")
        accepted = tuple(dict.fromkeys(str(value) for value in raw_accepted))
        if not set(accepted) <= chunk_ids or not any(
            chunk_trust[chunk_id] == required_trust for chunk_id in accepted
        ):
            raise ValueError("benchmark accepted chunks or trust class are invalid")
        case_ids.add(case_id)
        cases.append(
            RetrievalCase(
                case_id=case_id,
                category=category,
                query=query,
                accepted_chunk_ids=accepted,
                required_trust_class=required_trust,
            )
        )
    if {case.category for case in cases} != ALLOWED_CATEGORIES:
        raise ValueError("benchmark fixture must cover every required category")
    return BenchmarkFixture(
        benchmark_version=version,
        corpus=tuple(corpus),
        cases=tuple(cases),
        raw=payload,
    )


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 6) if values else 0.0


def evaluate_rankings(
    benchmark: BenchmarkFixture,
    rankings: Mapping[str, list[str]],
) -> dict[str, Any]:
    by_category: dict[str, dict[str, list[float]]] = {}
    all_recall: list[float] = []
    all_mrr: list[float] = []
    exact_recall: list[float] = []
    for case in benchmark.cases:
        ranked = list(dict.fromkeys(rankings.get(case.case_id, [])))
        accepted = set(case.accepted_chunk_ids)
        recall = len(accepted.intersection(ranked[:5])) / len(accepted)
        reciprocal_rank = next(
            (1.0 / rank for rank, chunk_id in enumerate(ranked[:10], start=1) if chunk_id in accepted),
            0.0,
        )
        all_recall.append(recall)
        all_mrr.append(reciprocal_rank)
        if case.category == "exact_source":
            exact_recall.append(recall)
        bucket = by_category.setdefault(case.category, {"recall": [], "mrr": []})
        bucket["recall"].append(recall)
        bucket["mrr"].append(reciprocal_rank)
    return {
        "macro_recall_at_5": _mean(all_recall),
        "mrr_at_10": _mean(all_mrr),
        "exact_source_recall_at_5": _mean(exact_recall),
        "categories": {
            category: {
                "case_count": len(values["recall"]),
                "recall_at_5": _mean(values["recall"]),
                "mrr_at_10": _mean(values["mrr"]),
            }
            for category, values in sorted(by_category.items())
        },
    }


def activation_gate(
    *,
    fts_macro_recall_at_5: float,
    semantic_macro_recall_at_5: float,
    exact_source_recall_at_5: float,
    peak_memory_mb: float,
    memory_allowance_mb: float,
    p95_query_latency_ms: float,
    worker_processes: int,
    production_path_verified: bool,
) -> dict[str, Any]:
    improvement = semantic_macro_recall_at_5 - fts_macro_recall_at_5
    total_worker_memory_mb = peak_memory_mb * max(int(worker_processes), 1)
    checks = {
        "macro_recall_improvement_at_least_0_08": improvement + 1e-12 >= 0.08,
        "exact_source_recall_at_least_0_85": exact_source_recall_at_5 >= 0.85,
        "all_worker_memory_within_allowance": total_worker_memory_mb
        <= memory_allowance_mb,
        "p95_latency_at_most_250_ms": p95_query_latency_ms <= 250.0,
        "production_hnsw_rrf_path_verified": bool(production_path_verified),
    }
    return {
        "eligible": all(checks.values()),
        "macro_recall_improvement": round(improvement, 6),
        "worker_processes": max(int(worker_processes), 1),
        "estimated_all_worker_memory_mb": round(total_worker_memory_mb, 3),
        "checks": checks,
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return round(ordered[index], 3)


def build_report(
    *,
    benchmark: BenchmarkFixture,
    mode: str,
    rankings: Mapping[str, list[str]],
    latencies_ms: list[float],
    indexing_time_ms: float,
    peak_memory_mb: float,
    model_id: str | None = None,
) -> dict[str, Any]:
    metrics = evaluate_rankings(benchmark, rankings)
    return {
        "benchmark_version": benchmark.benchmark_version,
        "mode": mode,
        "model_id": model_id,
        "case_count": len(benchmark.cases),
        "corpus_chunk_count": len(benchmark.corpus),
        **metrics,
        "p95_query_latency_ms": _p95(latencies_ms),
        "corpus_indexing_time_ms": round(indexing_time_ms, 3),
        "peak_memory_mb": round(peak_memory_mb, 3),
        "contains_raw_document_text": False,
    }


def _peak_memory_mb(traced_peak: int) -> float:
    traced_mb = traced_peak / (1024 * 1024)
    try:
        import psutil

        rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        rss_mb = 0.0
    return max(traced_mb, rss_mb)


def _run_fts(benchmark: BenchmarkFixture, database_url: str) -> dict[str, Any]:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - base runtime owns psycopg
        raise RuntimeError("psycopg is required for the FTS benchmark") from exc
    tracemalloc.start()
    started = time.perf_counter()
    rankings: dict[str, list[str]] = {}
    latencies: list[float] = []
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            CREATE TEMP TABLE radar_ask_retrieval_benchmark (
                chunk_id TEXT PRIMARY KEY,
                trust_class TEXT NOT NULL,
                chunk_text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                search_vector TSVECTOR GENERATED ALWAYS AS (
                    to_tsvector('simple', chunk_text)
                ) STORED
            ) ON COMMIT DROP
            """
        )
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO radar_ask_retrieval_benchmark (
                    chunk_id, trust_class, chunk_text, normalized_text
                ) VALUES (%s, %s, %s, %s)
                """,
                [
                    (chunk.chunk_id, chunk.trust_class, chunk.text, _fold(chunk.text))
                    for chunk in benchmark.corpus
                ],
            )
        conn.execute(
            """
            CREATE INDEX radar_ask_retrieval_benchmark_fts
            ON radar_ask_retrieval_benchmark USING GIN (search_vector)
            """
        )
        conn.execute("ANALYZE radar_ask_retrieval_benchmark")
        indexing_time_ms = (time.perf_counter() - started) * 1000
        for case in benchmark.cases:
            query_started = time.perf_counter()
            pattern = "%" + "%".join(_fold(case.query).split()[:20]) + "%"
            rows = conn.execute(
                """
                WITH query_terms AS (
                    SELECT websearch_to_tsquery('simple', %s) AS query
                )
                SELECT chunk_id
                FROM radar_ask_retrieval_benchmark, query_terms
                WHERE search_vector @@ query_terms.query
                   OR normalized_text LIKE %s
                ORDER BY CASE trust_class
                             WHEN 'official' THEN 0
                             WHEN 'radar_method' THEN 1
                             ELSE 2
                         END,
                         GREATEST(
                             ts_rank_cd(search_vector, query_terms.query),
                             CASE WHEN normalized_text LIKE %s THEN 0.05 ELSE 0 END
                         ) DESC,
                         chunk_id
                LIMIT 5
                """,
                (case.query, pattern, pattern),
            ).fetchall()
            latencies.append((time.perf_counter() - query_started) * 1000)
            rankings[case.case_id] = [str(row[0]) for row in rows]
    _current, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return build_report(
        benchmark=benchmark,
        mode="fts",
        rankings=rankings,
        latencies_ms=latencies,
        indexing_time_ms=indexing_time_ms,
        peak_memory_mb=_peak_memory_mb(traced_peak),
    )


def _load_offline_model(path: Path):
    if not path.is_dir() or not (
        (path / "modules.json").is_file() or (path / "config.json").is_file()
    ):
        raise ValueError("--model-path must contain pre-downloaded model assets")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("install requirements-radar-ask-retrieval.txt first") from exc
    return SentenceTransformer(
        str(path.resolve()),
        local_files_only=True,
        trust_remote_code=False,
    )


def _run_semantic(
    benchmark: BenchmarkFixture,
    *,
    model_path: Path,
    model_id: str,
    database_url: str,
) -> dict[str, Any]:
    if model_id not in ALLOWED_MODEL_IDS:
        raise ValueError("semantic benchmark model ID is not an approved candidate")
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - base runtime owns psycopg
        raise RuntimeError("psycopg is required for the semantic benchmark") from exc
    tracemalloc.start()
    model = _load_offline_model(model_path)
    corpus_text = [chunk.text for chunk in benchmark.corpus]
    if model_id == "intfloat/multilingual-e5-small":
        corpus_text = [f"passage: {text}" for text in corpus_text]
    started = time.perf_counter()
    corpus_vectors = model.encode(
        corpus_text,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    dimension = len(corpus_vectors[0]) if len(corpus_vectors) else 0
    if dimension < 1 or any(len(vector) != dimension for vector in corpus_vectors):
        raise ValueError("semantic model returned inconsistent vector dimensions")

    def vector_literal(values) -> str:
        normalized = [float(value) for value in values]
        if not normalized or not all(math.isfinite(value) for value in normalized):
            raise ValueError("semantic model returned a non-finite vector")
        return "[" + ",".join(f"{value:.9g}" for value in normalized) + "]"

    rankings: dict[str, list[str]] = {}
    latencies: list[float] = []
    with psycopg.connect(database_url) as conn:
        extension_ready = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
        ).fetchone()[0]
        if not extension_ready:
            raise ValueError(
                "semantic activation benchmark requires an owner-installed pgvector extension"
            )
        conn.execute(
            f"""
            CREATE TEMP TABLE radar_ask_semantic_benchmark (
                chunk_id TEXT PRIMARY KEY,
                trust_class TEXT NOT NULL,
                chunk_text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                search_vector TSVECTOR GENERATED ALWAYS AS (
                    to_tsvector('simple', chunk_text)
                ) STORED,
                embedding vector({dimension}) NOT NULL
            ) ON COMMIT DROP
            """
        )
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO radar_ask_semantic_benchmark (
                    chunk_id, trust_class, chunk_text, normalized_text, embedding
                ) VALUES (%s, %s, %s, %s, %s::vector)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.trust_class,
                        chunk.text,
                        _fold(chunk.text),
                        vector_literal(vector),
                    )
                    for chunk, vector in zip(
                        benchmark.corpus,
                        corpus_vectors,
                        strict=True,
                    )
                ],
            )
        conn.execute(
            """
            CREATE INDEX radar_ask_semantic_benchmark_fts
            ON radar_ask_semantic_benchmark USING GIN (search_vector)
            """
        )
        conn.execute(
            """
            CREATE INDEX radar_ask_semantic_benchmark_hnsw
            ON radar_ask_semantic_benchmark
            USING hnsw (embedding vector_cosine_ops)
            """
        )
        conn.execute("ANALYZE radar_ask_semantic_benchmark")
        conn.execute("SET LOCAL enable_seqscan=off")
        indexing_time_ms = (time.perf_counter() - started) * 1000
        for case in benchmark.cases:
            query = (
                f"query: {case.query}"
                if model_id == "intfloat/multilingual-e5-small"
                else case.query
            )
            query_started = time.perf_counter()
            query_vector = model.encode(
                [query],
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0]
            if len(query_vector) != dimension:
                raise ValueError("semantic query vector dimension changed")
            query_literal = vector_literal(query_vector)
            pattern = "%" + "%".join(_fold(case.query).split()[:20]) + "%"
            fts_rows = conn.execute(
                """
                WITH query_terms AS (
                    SELECT websearch_to_tsquery('simple', %s) AS query
                )
                SELECT chunk_id
                FROM radar_ask_semantic_benchmark, query_terms
                WHERE search_vector @@ query_terms.query
                   OR normalized_text LIKE %s
                ORDER BY CASE trust_class
                             WHEN 'official' THEN 0
                             WHEN 'radar_method' THEN 1
                             ELSE 2
                         END,
                         GREATEST(
                             ts_rank_cd(search_vector, query_terms.query),
                             CASE WHEN normalized_text LIKE %s THEN 0.05 ELSE 0 END
                         ) DESC,
                         chunk_id
                LIMIT 5
                """,
                (case.query, pattern, pattern),
            ).fetchall()
            semantic_rows = conn.execute(
                """
                SELECT chunk_id
                FROM radar_ask_semantic_benchmark
                ORDER BY embedding <=> %s::vector, chunk_id
                LIMIT 5
                """,
                (query_literal,),
            ).fetchall()
            fused = fuse_ranked_results(
                fts=[
                    RankedChunk(chunk_id=str(row[0]), rank=rank)
                    for rank, row in enumerate(fts_rows, start=1)
                ],
                semantic=[
                    RankedChunk(chunk_id=str(row[0]), rank=rank)
                    for rank, row in enumerate(semantic_rows, start=1)
                ],
                limit=PRODUCTION_RETRIEVAL_LIMIT,
            )
            latencies.append((time.perf_counter() - query_started) * 1000)
            rankings[case.case_id] = [item.chunk_id for item in fused]
    _current, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report = build_report(
        benchmark=benchmark,
        mode="semantic_hnsw_rrf",
        model_id=model_id,
        rankings=rankings,
        latencies_ms=latencies,
        indexing_time_ms=indexing_time_ms,
        peak_memory_mb=_peak_memory_mb(traced_peak),
    )
    report["production_path_verified"] = True
    report["vector_index"] = "hnsw_cosine"
    report["fusion"] = "rrf_k60"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fts", "semantic"), required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--model-id", choices=sorted(ALLOWED_MODEL_IDS))
    parser.add_argument("--fts-baseline", type=Path)
    parser.add_argument("--memory-allowance-mb", type=float, default=1_024.0)
    parser.add_argument("--worker-processes", type=int, default=3)
    args = parser.parse_args(argv)
    benchmark = load_benchmark_fixture(args.cases)
    database_url = os.getenv("RADAR_TEST_DATABASE_URL", "").strip() or os.getenv(
        "DATABASE_URL", ""
    ).strip()
    if not database_url:
        raise ValueError("DATABASE_URL or RADAR_TEST_DATABASE_URL is required")
    if args.mode == "fts":
        report = _run_fts(benchmark, database_url)
        report["activation_gate"] = {
            "eligible": False,
            "reason": "FTS is the mandatory baseline, not a vector activation candidate",
        }
    else:
        if args.model_path is None or args.model_id is None:
            raise ValueError("semantic mode requires --model-path and --model-id")
        report = _run_semantic(
            benchmark,
            model_path=args.model_path,
            model_id=args.model_id,
            database_url=database_url,
        )
        if args.fts_baseline is None or not args.fts_baseline.is_file():
            report["activation_gate"] = {
                "eligible": False,
                "reason": "a matching FTS baseline report is required",
            }
        else:
            baseline = json.loads(args.fts_baseline.read_text(encoding="utf-8"))
            if baseline.get("benchmark_version") != benchmark.benchmark_version:
                raise ValueError("FTS baseline benchmark version does not match")
            report["activation_gate"] = activation_gate(
                fts_macro_recall_at_5=float(baseline["macro_recall_at_5"]),
                semantic_macro_recall_at_5=float(report["macro_recall_at_5"]),
                exact_source_recall_at_5=float(report["exact_source_recall_at_5"]),
                peak_memory_mb=float(report["peak_memory_mb"]),
                memory_allowance_mb=float(args.memory_allowance_mb),
                p95_query_latency_ms=float(report["p95_query_latency_ms"]),
                worker_processes=max(int(args.worker_processes), 1),
                production_path_verified=bool(report.get("production_path_verified")),
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

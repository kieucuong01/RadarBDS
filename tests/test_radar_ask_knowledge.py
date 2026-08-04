from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from db import connection
from db.connection import get_conn
from db.schema import init_schema
from scripts.radar_ask_knowledge import (
    import_document_payload,
    load_document_file,
    register_source,
    validate_document_payload,
    validate_source_definition,
)
from scripts.configure_radar_ask_db_role import KNOWLEDGE_VIEW_SQL
from services.radar_ask.contracts import AskContext, SourceKind, ToolCall
from services.radar_ask.evidence import build_provider_bundle
from services.radar_ask.registry import (
    OfficialLandPriceArgs,
    SearchOfficialDocumentsArgs,
    ToolContext,
    execute_tool,
)
from services.radar_ask.tools.knowledge import (
    RankedChunk,
    SemanticRetriever,
    VectorRetrievalNotReady,
    fuse_ranked_results,
    lookup_official_land_price,
    search_official_documents,
)


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "radar_ask"
    / "official_land_price_sample.json"
)
NOW = datetime(2026, 8, 4, 11, 0, tzinfo=timezone.utc)


@pytest.fixture
def knowledge_payload():
    return load_document_file(FIXTURE)


@pytest.fixture
def knowledge_database(knowledge_payload):
    slug = knowledge_payload["source"]["slug"]
    connection.close_all()
    init_schema()
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM knowledge_sources WHERE slug=?",
            (slug,),
        )
        register_source(conn, knowledge_payload["source"])
    yield knowledge_payload
    with get_conn() as conn:
        conn.execute("DELETE FROM knowledge_sources WHERE slug=?", (slug,))
    connection.close_all()


def test_source_allowlist_requires_trusted_https_origin(knowledge_payload):
    valid = validate_source_definition(knowledge_payload["source"])
    assert valid.slug == "tphcm-congbao-land-price-test"
    assert valid.trust_class == "official"

    insecure = {**knowledge_payload["source"], "canonical_url": "http://congbao.hochiminhcity.gov.vn/x"}
    with pytest.raises(ValueError, match="HTTPS"):
        validate_source_definition(insecure)

    arbitrary = {**knowledge_payload["source"], "canonical_url": "https://attacker.example/x"}
    with pytest.raises(ValueError, match="allowlist"):
        validate_source_definition(arbitrary)


def test_document_validation_preserves_dates_and_deterministic_chunks(knowledge_payload):
    first = validate_document_payload(knowledge_payload)
    second = validate_document_payload(deepcopy(knowledge_payload))

    assert first.published_at == date(2025, 12, 31)
    assert first.effective_from == date(2026, 1, 1)
    assert first.content_sha256 == second.content_sha256
    assert first.chunk_ids == second.chunk_ids
    assert len(first.chunks) == 2


def test_document_import_is_idempotent_and_schema_has_gin_index(knowledge_database):
    with get_conn() as conn:
        first = import_document_payload(conn, knowledge_database)
    with get_conn() as conn:
        second = import_document_payload(conn, knowledge_database)
        indexes = conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname='idx_knowledge_chunks_search_vector'"
        ).fetchall()

    assert isinstance(first.document_id, UUID)
    assert first.document_id == second.document_id
    assert first.chunk_ids == second.chunk_ids
    assert first.inserted_chunks == 2
    assert second.inserted_chunks == 0
    assert indexes and "USING gin" in indexes[0]["indexdef"]


def test_imported_vietnamese_text_is_searchable_by_fts_and_accent_fold(
    knowledge_database,
):
    with get_conn() as conn:
        imported = import_document_payload(conn, knowledge_database)
        fts_rows = conn.execute(
            """
            SELECT id
            FROM knowledge_chunks
            WHERE document_id=?
              AND search_vector @@ websearch_to_tsquery('simple', ?)
            """,
            (imported.document_id, "nghĩa vụ tài chính"),
        ).fetchall()
        folded_rows = conn.execute(
            """
            SELECT id
            FROM knowledge_chunks
            WHERE document_id=?
              AND normalized_text LIKE ?
            """,
            (imported.document_id, "%bang%gia%dat%"),
        ).fetchall()

    assert fts_rows
    assert folded_rows


def test_new_document_version_supersedes_previous_current_version(knowledge_database):
    with get_conn() as conn:
        first = import_document_payload(conn, knowledge_database)
    updated = deepcopy(knowledge_database)
    updated["version"] = "2026-test-v2"
    updated["content"] += "\n\nPhiên bản cập nhật làm rõ phạm vi áp dụng."
    with get_conn() as conn:
        second = import_document_payload(conn, updated)
        old_row = conn.execute(
            "SELECT is_current FROM knowledge_documents WHERE id=?",
            (first.document_id,),
        ).fetchone()
        new_row = conn.execute(
            "SELECT supersedes_document_id, title, effective_from FROM knowledge_documents WHERE id=?",
            (second.document_id,),
        ).fetchone()

    assert second.document_id != first.document_id
    assert old_row["is_current"] is False
    assert new_row["supersedes_document_id"] == first.document_id
    assert new_row["title"] == updated["title"]
    assert new_row["effective_from"] == date(2026, 1, 1)


def test_future_version_does_not_hide_currently_effective_document(knowledge_database):
    with get_conn() as conn:
        current = import_document_payload(conn, knowledge_database)
    future = deepcopy(knowledge_database)
    future["version"] = "2027-test-v1"
    future["effective_from"] = "2027-01-01"
    future["effective_to"] = "2027-12-31"
    future["content"] += "\n\nPhiên bản chỉ có hiệu lực trong tương lai."
    with get_conn() as conn:
        planned = import_document_payload(conn, future)
        temporary_view_sql = KNOWLEDGE_VIEW_SQL.replace(
            "public.radar_ask_v_knowledge_chunks",
            "pg_temp.radar_ask_v_knowledge_chunks",
            1,
        )
        conn.execute(temporary_view_sql)
        try:
            visible = conn.execute(
                """
            SELECT DISTINCT document_id
            FROM pg_temp.radar_ask_v_knowledge_chunks
            WHERE source_slug=?
                """,
                (knowledge_database["source_slug"],),
            ).fetchall()
        finally:
            conn.execute("DROP VIEW pg_temp.radar_ask_v_knowledge_chunks")

    assert [row["document_id"] for row in visible] == [current.document_id]
    assert planned.document_id != current.document_id


def test_same_content_rejects_changed_immutable_metadata(knowledge_database):
    with get_conn() as conn:
        import_document_payload(conn, knowledge_database)
    changed = deepcopy(knowledge_database)
    changed["title"] = "Tiêu đề đã bị sửa nhưng nội dung giữ nguyên"
    with get_conn() as conn, pytest.raises(ValueError, match="immutable metadata"):
        import_document_payload(conn, changed)


def test_same_version_rejects_different_content(knowledge_database):
    with get_conn() as conn:
        import_document_payload(conn, knowledge_database)
    changed = deepcopy(knowledge_database)
    changed["content"] += "\n\nNội dung khác nhưng cố giữ nguyên version."
    with get_conn() as conn, pytest.raises(ValueError, match="version"):
        import_document_payload(conn, changed)


def test_repeated_boilerplate_chunks_are_valid(knowledge_database):
    repeated = deepcopy(knowledge_database)
    paragraph = "Điều khoản boilerplate được lặp hợp lệ trong phụ lục."
    repeated["version"] = "2026-repeat-v1"
    repeated["content"] = f"{paragraph}\n\n{paragraph}"
    with get_conn() as conn:
        imported = import_document_payload(conn, repeated)

    assert imported.inserted_chunks == 2
    assert imported.chunk_ids[0] != imported.chunk_ids[1]


class FakeResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeKnowledgeConnection:
    def __init__(self):
        self.queries: list[tuple[str, tuple]] = []
        self.official_rows = [
            {
                "row_key": "official-row-1",
                "area": "PHƯỜNG SÀI GÒN",
                "appendix": "Phụ lục II",
                "stt": "1",
                "street": "ĐỒNG KHỞI",
                "segment_from": "TRỌN ĐƯỜNG",
                "segment_to": "",
                "residential": 687_200,
                "commerce_service": 481_000,
                "production_business": 412_300,
                "page": 20,
                "source_title": "Nghị quyết bảng giá đất TP.HCM",
                "source_url": "https://congbao.hochiminhcity.gov.vn/test/radar-ask",
                "data_as_of": date(2026, 1, 1),
                "unit": "1.000 đồng/m²",
            }
        ]
        self.knowledge_rows = [
            {
                "chunk_id": "71a46703-557d-5a6e-a421-920598c930a3",
                "chunk_index": 0,
                "chunk_text": "Bảng giá đất là căn cứ cho nghĩa vụ tài chính nhưng không phải giá giao dịch thị trường.",
                "document_title": "Quy định sử dụng bảng giá đất",
                "version": "2026-v1",
                "published_at": date(2025, 12, 31),
                "effective_from": date(2026, 1, 1),
                "effective_to": date(2026, 12, 31),
                "source_slug": "tphcm-congbao-land-price",
                "source_title": "Công báo TP.HCM",
                "source_url": "https://congbao.hochiminhcity.gov.vn/test/radar-ask",
                "trust_class": "official",
                "jurisdiction": "TP.HCM",
                "rank": 0.9,
                "imported_at": NOW,
            }
        ]

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split()).lower()
        self.queries.append((sql, tuple(params)))
        if "set_config('statement_timeout'" in normalized:
            return FakeResult([{"set_config": str(params[0])}])
        if "radar_ask:official_land_price" in normalized:
            return FakeResult(self.official_rows)
        if "radar_ask:knowledge_search" in normalized:
            return FakeResult(self.knowledge_rows)
        if "radar_ask:governing_document" in normalized:
            requested_urls = {
                str(value)
                for param in params
                for value in (
                    param if isinstance(param, (list, tuple)) else (param,)
                )
                if str(value).startswith("https://")
            }
            return FakeResult(
                [
                    row
                    for row in self.knowledge_rows
                    if row["source_url"] in requested_urls
                ][:1]
            )
        raise AssertionError(f"unexpected knowledge query: {normalized}")


@contextmanager
def fake_factory(connection):
    yield connection


def tool_context(connection, tier="free"):
    return ToolContext(
        ask=AskContext(user_id=31, tier=tier),
        read_conn_factory=lambda: fake_factory(connection),
    )


def test_search_returns_exact_chunk_source_and_trust_citations():
    connection = FakeKnowledgeConnection()
    bundle = search_official_documents(
        args=SearchOfficialDocumentsArgs(
            query="bảng giá đất dùng để làm gì",
            limit=5,
        ),
        context=tool_context(connection),
    )

    assert bundle.items
    assert all(item.source_ref.startswith("knowledge:") for item in bundle.items)
    assert all(item.source_kind is SourceKind.OFFICIAL_DOCUMENT for item in bundle.items)
    assert all(item.provenance["source_url"].startswith("https://") for item in bundle.items)
    assert bundle.items[0].value["trust_class"] == "official"
    search_sql = next(sql for sql, _ in connection.queries if "radar_ask:knowledge_search" in sql)
    normalized = " ".join(search_sql.lower().split())
    assert "websearch_to_tsquery('simple'" in normalized
    assert "effective_from" in normalized and "effective_to" in normalized


def test_official_land_price_is_labeled_separately_from_market_and_fair_value():
    bundle = lookup_official_land_price(
        args=OfficialLandPriceArgs(
            area="Phường Sài Gòn",
            street="Đồng Khởi",
        ),
        context=tool_context(FakeKnowledgeConnection()),
    )

    official = next(item for item in bundle.items if item.source_kind is SourceKind.OFFICIAL_PRICE)
    governing = next(
        item
        for item in bundle.items
        if item.source_kind is SourceKind.OFFICIAL_DOCUMENT
    )
    assert official.value["official_residential_price_thousand_vnd_per_m2"] == 687_200.0
    assert official.value["price_semantics"] == "official_land_price_not_market_or_fair_value"
    assert governing.provenance["source_url"] == official.provenance["source_url"]
    assert "asking_price" not in official.value
    assert "fair_price" not in official.value


def test_official_price_never_attaches_an_unrelated_governing_document():
    connection = FakeKnowledgeConnection()
    connection.knowledge_rows[0]["source_url"] = (
        "https://congbao.hochiminhcity.gov.vn/test/unrelated-document"
    )
    bundle = lookup_official_land_price(
        args=OfficialLandPriceArgs(area="Phường Sài Gòn", street="Đồng Khởi"),
        context=tool_context(connection),
    )

    assert [item.source_kind for item in bundle.items] == [SourceKind.OFFICIAL_PRICE]
    governing_query = next(
        params
        for sql, params in connection.queries
        if "radar_ask:governing_document" in sql
    )
    assert connection.official_rows[0]["source_url"] in governing_query


def test_provider_copy_strips_canonical_url_but_keeps_exact_chunk_citation():
    bundle = search_official_documents(
        args=SearchOfficialDocumentsArgs(query="bảng giá đất", limit=5),
        context=tool_context(FakeKnowledgeConnection()),
    )

    safe = build_provider_bundle(bundle, tier="free")
    encoded = safe.model_dump_json()
    assert "congbao.hochiminhcity.gov.vn" not in encoded
    assert safe.items[0].source_ref.startswith("knowledge:")


def test_registry_dispatches_both_curated_knowledge_handlers():
    connection = FakeKnowledgeConnection()
    calls = [
        ToolCall(
            call_id="k1",
            name="lookup_official_land_price",
            arguments={"area": "Phường Sài Gòn", "street": "Đồng Khởi"},
        ),
        ToolCall(
            call_id="k2",
            name="search_official_documents",
            arguments={"query": "bảng giá đất dùng để làm gì"},
        ),
    ]

    assert all(execute_tool(call, tool_context(connection)).items for call in calls)


def test_vector_flag_cannot_enable_without_extension_and_local_model(
    monkeypatch,
    tmp_path,
):
    model_path = tmp_path / "local-model"
    model_path.mkdir()
    monkeypatch.setenv("RADAR_ASK_KNOWLEDGE_VECTOR_ENABLED", "1")
    monkeypatch.setenv("RADAR_ASK_KNOWLEDGE_VECTOR_MODEL_PATH", str(model_path))
    monkeypatch.setenv(
        "RADAR_ASK_KNOWLEDGE_VECTOR_MODEL_ID",
        "intfloat/multilingual-e5-small",
    )
    monkeypatch.setenv("RADAR_ASK_KNOWLEDGE_VECTOR_DIMENSION", "384")

    with pytest.raises(VectorRetrievalNotReady, match="readiness"):
        SemanticRetriever.from_environment(FakeKnowledgeConnection())


def test_unready_vector_path_falls_back_to_fts_without_losing_citations(
    monkeypatch,
    tmp_path,
):
    model_path = tmp_path / "local-model"
    model_path.mkdir()
    monkeypatch.setenv("RADAR_ASK_KNOWLEDGE_VECTOR_ENABLED", "1")
    monkeypatch.setenv("RADAR_ASK_KNOWLEDGE_VECTOR_MODEL_PATH", str(model_path))
    monkeypatch.setenv(
        "RADAR_ASK_KNOWLEDGE_VECTOR_MODEL_ID",
        "intfloat/multilingual-e5-small",
    )
    monkeypatch.setenv("RADAR_ASK_KNOWLEDGE_VECTOR_DIMENSION", "384")

    bundle = search_official_documents(
        args=SearchOfficialDocumentsArgs(query="bảng giá đất", limit=5),
        context=tool_context(FakeKnowledgeConnection()),
    )

    assert bundle.items
    assert bundle.items[0].source_ref.startswith("knowledge:")
    assert "semantic_retrieval_unavailable_using_fts" in bundle.warnings
    assert bundle.calculations["retrieval"].startswith("postgres_fts")


def test_rrf_deduplicates_and_prioritizes_agreement():
    first = RankedChunk(chunk_id="c1", rank=1, payload={"source_ref": "knowledge:c1"})
    shared_fts = RankedChunk(chunk_id="c2", rank=2, payload={"source_ref": "knowledge:c2"})
    shared_semantic = RankedChunk(
        chunk_id="c2",
        rank=1,
        payload={"source_ref": "knowledge:c2"},
    )

    fused = fuse_ranked_results(
        fts=[first, shared_fts],
        semantic=[shared_semantic],
        limit=5,
    )

    assert [item.chunk_id for item in fused] == ["c2", "c1"]
    assert fused[0].payload["source_ref"] == "knowledge:c2"


def test_e5_semantic_query_uses_required_query_prefix():
    class RecordingEncoder:
        def __init__(self):
            self.inputs = []

        def encode(self, inputs, **_kwargs):
            self.inputs.append(list(inputs))
            return [[0.1, 0.2, 0.3]]

    class EmptySemanticConnection:
        def execute(self, sql, _params=()):
            assert "radar_ask_semantic_search" in sql
            return FakeResult([])

    encoder = RecordingEncoder()
    retriever = SemanticRetriever(
        conn=EmptySemanticConnection(),
        encoder=encoder,
        model_id="intfloat/multilingual-e5-small",
        dimension=3,
    )

    assert retriever.search("giá đất Phú Mỹ", limit=5) == []
    assert encoder.inputs == [["query: giá đất Phú Mỹ"]]

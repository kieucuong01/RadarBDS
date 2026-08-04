from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from services.radar_ask.contracts import (
    AskContext,
    EvidenceBundle,
    EvidenceItem,
    PageContext,
    RetrievalQuality,
    SourceKind,
    ToolCall,
)
from services.radar_ask.evidence import (
    EvidenceBuilder,
    build_provider_bundle,
    stable_evidence_id,
)
from services.radar_ask.registry import (
    DEFAULT_TOOL_REGISTRY,
    ResolveListingArgs,
    ResolveLocationArgs,
    ResolveRoadArgs,
    ToolContext,
    execute_tool,
)
from services.radar_ask.tools.entities import (
    resolve_listing,
    resolve_location,
    resolve_road,
)


NOW = datetime(2026, 8, 4, 7, 0, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeReadConnection:
    def __init__(self):
        self.queries: list[tuple[str, tuple]] = []
        self.listings = {
            101: {
                "listing_id": 101,
                "title": "Lô đất Phú Tân",
                "source": "facebook",
                "ward": "Phú Tân",
                "property_type": "dat_nen",
                "road_name": "Đường 30/4",
                "is_active": True,
                "probably_sold": False,
                "public_visible": True,
                "crawled_at": NOW,
            },
            102: {
                "listing_id": 102,
                "title": "Tin bị ẩn",
                "source": "facebook",
                "ward": "Tân An",
                "property_type": "dat_nen",
                "road_name": "DX 071",
                "is_active": True,
                "probably_sold": False,
                "public_visible": False,
                "crawled_at": NOW,
            },
        }
        self.locations = [
            {"ward": "Tân An", "as_of": NOW, "sample_size": 9},
            {"ward": "Phú Tân", "as_of": NOW, "sample_size": 12},
            {"ward": "Hiệp Thành", "as_of": NOW, "sample_size": 8},
            {"ward": "Phú Mỹ", "as_of": NOW, "sample_size": 10},
            {"ward": "Hòa Phú", "as_of": NOW, "sample_size": 7},
            {"ward": "Phú Chánh", "as_of": NOW, "sample_size": 6},
        ]
        self.roads = [
            {"road_name": "Đường 30/4", "ward": "Phú Cường", "as_of": NOW, "sample_size": 5},
            {"road_name": "Đường 30/4", "ward": "Chánh Nghĩa", "as_of": NOW, "sample_size": 4},
            {"road_name": "DX 071", "ward": "Định Hòa", "as_of": NOW, "sample_size": 11},
        ]

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split()).lower()
        self.queries.append((sql, tuple(params)))
        if "where listing_id" in normalized:
            row = self.listings.get(int(params[0]))
            return FakeResult([row] if row else [])
        if "group by ward, road_name" in normalized:
            return FakeResult(self.roads)
        if "group by ward" in normalized:
            return FakeResult(self.locations)
        raise AssertionError(f"unexpected entity query: {normalized}")


@contextmanager
def fake_read_factory(connection):
    yield connection


def tool_context(
    connection: FakeReadConnection,
    *,
    tier: str = "free",
    listing_id: int | None = None,
) -> ToolContext:
    return ToolContext(
        ask=AskContext(
            user_id=7,
            tier=tier,
            page=PageContext(listing_id=listing_id),
        ),
        read_conn_factory=lambda: fake_read_factory(connection),
    )


def test_resolve_listing_supports_numeric_and_current_page_context():
    connection = FakeReadConnection()
    context = tool_context(connection, listing_id=101)

    direct = resolve_listing(args=ResolveListingArgs(listing_id=101), context=context)
    current = resolve_listing(args=ResolveListingArgs(), context=context)

    assert direct.resolved_entities["listing_ref"] == "radar-listing:101"
    assert current.resolved_entities == direct.resolved_entities
    assert direct.items[0].source_ref == "radar-listing:101"
    assert all("101" not in sql for sql, _params in connection.queries)
    assert connection.queries[0][1] == (101,)


def test_missing_or_hidden_listing_does_not_disclose_existence_to_free_but_admin_can_resolve():
    connection = FakeReadConnection()

    missing = resolve_listing(
        args=ResolveListingArgs(listing_id=999),
        context=tool_context(connection),
    )
    hidden = resolve_listing(
        args=ResolveListingArgs(listing_id=102),
        context=tool_context(connection),
    )
    admin = resolve_listing(
        args=ResolveListingArgs(listing_id=102),
        context=tool_context(connection, tier="admin"),
    )

    assert missing.items == [] and hidden.items == []
    assert missing.retrieval_quality is RetrievalQuality.INSUFFICIENT
    assert hidden.missing_requirements == missing.missing_requirements
    assert admin.resolved_entities["listing_ref"] == "radar-listing:102"


@pytest.mark.parametrize(
    ("ward", "expected"),
    [
        ("TDC Phu Chanh", "Phú Tân"),
        ("KDC Hiep Thanh", "Hiệp Thành"),
        ("Phu Tan", "Phú Tân"),
    ],
)
def test_explicit_old_market_aliases_resolve_to_canonical_valuation_wards(ward, expected):
    bundle = resolve_location(
        args=ResolveLocationArgs(city="Thủ Dầu Một", ward=ward),
        context=tool_context(FakeReadConnection()),
    )

    assert bundle.needs_clarification is False
    assert bundle.resolved_entities["ward"] == expected


def test_broad_post_merger_ward_returns_old_market_clarification_candidates():
    bundle = resolve_location(
        args=ResolveLocationArgs(ward="phường Bình Dương"),
        context=tool_context(FakeReadConnection()),
    )

    assert bundle.needs_clarification is True
    assert {"Phú Mỹ", "Hòa Phú", "Phú Tân", "Phú Chánh"} <= set(
        bundle.clarification_candidates
    )
    assert bundle.items == []


def test_ambiguous_road_requires_clarification_and_exact_ward_disambiguates():
    connection = FakeReadConnection()
    ambiguous = resolve_road(
        args=ResolveRoadArgs(road="Đường 30/4"),
        context=tool_context(connection),
    )
    exact = resolve_road(
        args=ResolveRoadArgs(road="DX071", ward="Định Hòa"),
        context=tool_context(connection),
    )

    assert ambiguous.needs_clarification is True
    assert len(ambiguous.clarification_candidates) == 2
    assert ambiguous.items == []
    assert exact.resolved_entities == {"road": "DX 071", "ward": "Định Hòa"}
    assert exact.items[0].source_kind is SourceKind.MARKET_STAT


def test_stable_evidence_ids_deduplicate_and_conflicts_are_recorded():
    evidence_id = stable_evidence_id("market_stat", "ward:phu-tan", "listings:12")
    assert evidence_id == stable_evidence_id(
        "market_stat",
        "ward:phu-tan",
        "listings:12",
    )
    first = EvidenceItem(
        evidence_id=evidence_id,
        source_kind=SourceKind.MARKET_STAT,
        source_ref="ward:phu-tan",
        value={"sample_size": 12},
        as_of=NOW,
        dataset_version="listings:12",
    )
    conflicting = first.model_copy(update={"value": {"sample_size": 99}})
    builder = EvidenceBuilder(question_snapshot="Phú Tân có dữ liệu gì?", row_limit=5)

    builder.add(first)
    builder.add(first)
    builder.add(conflicting)
    bundle = builder.build()

    assert len(bundle.items) == 1
    assert len(bundle.conflicts) == 1
    assert bundle.retrieval_quality is RetrievalQuality.CONFLICTED


def test_evidence_builder_caps_rows_and_provider_bundle_strips_private_fields():
    builder = EvidenceBuilder(question_snapshot="Kiểm tra dữ liệu", row_limit=2)
    for index in range(4):
        builder.add(
            EvidenceItem(
                evidence_id=stable_evidence_id("listing", f"listing:{index}", "v1"),
                source_kind=SourceKind.LISTING,
                source_ref=f"radar-listing:{index}",
                value={
                    "title": f"Gọi 0909 123 45{index} tại https://facebook.com/{index}",
                    "phone": f"090912345{index}",
                    "database_url": "postgresql://secret",
                    "raw_sql": "SELECT * FROM users",
                    "safe_value": index,
                },
                as_of=NOW,
                dataset_version="v1",
                provenance={"listing_id": str(index), "method": "safe_view"},
            )
        )

    bounded = builder.build()
    safe = build_provider_bundle(bounded, tier="admin")
    encoded = safe.model_dump_json().lower()

    assert len(bounded.items) == 2
    assert "evidence_row_limit_reached" in bounded.warnings
    assert "0909" not in encoded
    assert "facebook.com" not in encoded
    assert "phone" not in encoded
    assert "database_url" not in encoded
    assert "raw_sql" not in encoded
    assert "listing_id" not in encoded
    assert "safe_value" in encoded


def test_default_registry_dispatches_real_entity_handler_with_typed_arguments():
    connection = FakeReadConnection()
    bundle = execute_tool(
        ToolCall(call_id="entity-1", name="resolve_listing", arguments={"listing_id": 101}),
        tool_context(connection),
        registry=DEFAULT_TOOL_REGISTRY,
    )

    assert bundle.resolved_entities["listing_ref"] == "radar-listing:101"

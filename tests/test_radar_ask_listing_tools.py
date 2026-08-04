from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from services.radar_ask.contracts import AskContext, SourceKind, ToolCall
from services.radar_ask.evidence import build_provider_bundle
from services.radar_ask.registry import (
    DEFAULT_TOOL_REGISTRY,
    HistoryArgs,
    ListingFactsArgs,
    ToolContext,
    execute_tool,
)
from services.radar_ask.tools.listings import (
    get_listing_facts,
    get_lot_history,
    get_price_history,
)


NOW = datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)


class FakeResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeListingConnection:
    def __init__(self):
        self.queries: list[tuple[str, tuple]] = []
        self.listings = {
            201: {
                "listing_id": 201,
                "source": "facebook",
                "title": "Bán lô đẹp - gọi 0909 123 456",
                "ward": "Phú Tân",
                "price_ty": 2.4,
                "price_per_m2": 20.0,
                "area_m2": 120.0,
                "property_type": "dat_nen",
                "frontage_m": 6.0,
                "depth_m": 20.0,
                "road_name": "Đường N10",
                "road_width_m": 6.0,
                "road_type": "duong_nhua",
                "road_tier": 2,
                "tho_cu_m2": 100.0,
                "tho_cu_ratio": 0.8333,
                "has_so": True,
                "price_dropped": True,
                "price_drop_pct": 7.7,
                "price_first_ty": 2.6,
                "possibly_duplicate": False,
                "duplicate_of_id": None,
                "measurement_provenance": '{"area_m2":"declared_text","frontage_m":"source_text"}',
                "extraction_quality_flags": "",
                "suspicious_bait": False,
                "public_visible": True,
                "first_seen_at": NOW - timedelta(days=30),
                "last_seen_at": NOW,
                "posted_at": NOW - timedelta(days=32),
                "crawled_at": NOW,
                "is_active": True,
                "probably_sold": False,
            },
            204: {
                "listing_id": 204,
                "source": "guland",
                "title": "Tin publisher bị ẩn 0912 345 678",
                "ward": "Phú Tân",
                "price_ty": 2.1,
                "price_per_m2": 21.0,
                "area_m2": 100.0,
                "property_type": "dat_nen",
                "frontage_m": 5.0,
                "depth_m": 20.0,
                "road_name": "Đường N10",
                "road_width_m": 6.0,
                "road_type": "duong_nhua",
                "road_tier": 2,
                "tho_cu_m2": 100.0,
                "tho_cu_ratio": 1.0,
                "has_so": True,
                "price_dropped": False,
                "price_drop_pct": None,
                "price_first_ty": 2.1,
                "possibly_duplicate": True,
                "duplicate_of_id": 201,
                "measurement_provenance": "{}",
                "extraction_quality_flags": "publisher_high_activity",
                "suspicious_bait": False,
                "public_visible": False,
                "first_seen_at": NOW - timedelta(days=10),
                "last_seen_at": NOW,
                "posted_at": NOW - timedelta(days=10),
                "crawled_at": NOW,
                "is_active": True,
                "probably_sold": False,
            },
        }
        self.price_history = [
            {
                "price_history_id": 3,
                "listing_id": 201,
                "price_ty": 2.4,
                "price_per_m2": 20.0,
                "recorded_at": NOW,
            },
            {
                "price_history_id": 1,
                "listing_id": 201,
                "price_ty": 2.6,
                "price_per_m2": 21.67,
                "recorded_at": NOW - timedelta(days=30),
            },
            {
                "price_history_id": 2,
                "listing_id": 201,
                "price_ty": 2.5,
                "price_per_m2": 20.83,
                "recorded_at": NOW - timedelta(days=15),
            },
        ]
        self.lot_history = [
            {
                "listing_id": 201,
                "canonical_lot_id": 201,
                "source": "facebook",
                "title": "Tin gốc 0909 111 222",
                "ward": "Phú Tân",
                "road_name": "Đường N10",
                "property_type": "dat_nen",
                "area_m2": 120.0,
                "frontage_m": 6.0,
                "depth_m": 20.0,
                "price_ty": 2.4,
                "price_per_m2": 20.0,
                "price_first_ty": 2.6,
                "first_seen_at": NOW - timedelta(days=30),
                "last_seen_at": NOW,
                "posted_at": NOW - timedelta(days=32),
                "crawled_at": NOW,
                "is_active": True,
                "public_visible": True,
            },
            {
                "listing_id": 202,
                "canonical_lot_id": 201,
                "source": "facebook",
                "title": "Repost cùng lô 0909 333 444",
                "ward": "Phú Tân",
                "road_name": "Đường N10",
                "property_type": "dat_nen",
                "area_m2": 120.0,
                "frontage_m": 6.0,
                "depth_m": 20.0,
                "price_ty": 2.5,
                "price_per_m2": 20.83,
                "price_first_ty": 2.5,
                "first_seen_at": NOW - timedelta(days=20),
                "last_seen_at": NOW - timedelta(days=5),
                "posted_at": NOW - timedelta(days=20),
                "crawled_at": NOW - timedelta(days=5),
                "is_active": True,
                "public_visible": True,
            },
            {
                "listing_id": 204,
                "canonical_lot_id": 201,
                "source": "guland",
                "title": "Publisher ẩn 0912 345 678",
                "ward": "Phú Tân",
                "road_name": "Đường N10",
                "property_type": "dat_nen",
                "area_m2": 120.0,
                "frontage_m": 6.0,
                "depth_m": 20.0,
                "price_ty": 2.3,
                "price_per_m2": 19.17,
                "price_first_ty": 2.3,
                "first_seen_at": NOW - timedelta(days=8),
                "last_seen_at": NOW,
                "posted_at": NOW - timedelta(days=8),
                "crawled_at": NOW,
                "is_active": True,
                "public_visible": False,
            },
        ]

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split()).lower()
        self.queries.append((sql, tuple(params)))
        if "from public.radar_ask_v_price_history" in normalized:
            listing_id, limit = int(params[0]), int(params[1])
            rows = [row for row in self.price_history if row["listing_id"] == listing_id]
            return FakeResult(rows[-limit:])
        if "from public.radar_ask_v_lot_history" in normalized:
            canonical_id, is_admin, limit = int(params[0]), bool(params[1]), int(params[2])
            rows = [
                row
                for row in self.lot_history
                if row["canonical_lot_id"] == canonical_id
                and (is_admin or row["public_visible"])
            ]
            return FakeResult(rows[:limit])
        if "from public.radar_ask_v_listings" in normalized:
            row = self.listings.get(int(params[0]))
            return FakeResult([row] if row else [])
        raise AssertionError(f"unexpected listing query: {normalized}")


@contextmanager
def fake_factory(connection):
    yield connection


def context(connection, tier="free") -> ToolContext:
    return ToolContext(
        ask=AskContext(user_id=11, tier=tier),
        read_conn_factory=lambda: fake_factory(connection),
    )


@pytest.mark.parametrize("tier", ["free", "vip"])
def test_listing_facts_are_typed_and_redact_embedded_phone_and_source_url(tier):
    bundle = get_listing_facts(
        args=ListingFactsArgs(listing_id=201),
        context=context(FakeListingConnection(), tier),
    )
    encoded = bundle.model_dump_json().lower()
    facts = bundle.items[0]

    assert facts.source_kind is SourceKind.LISTING
    assert facts.value["asking_price_ty"] == 2.4
    assert facts.value["asking_price_per_m2_million"] == 20.0
    assert facts.value["measurement_provenance"]["area_m2"] == "declared_text"
    assert facts.value["frontage_m"] == 6.0
    assert "asking_price_not_transaction_price" in bundle.warnings
    assert "0909" not in encoded
    assert "facebook.com" not in encoded
    assert "source_url" not in encoded


def test_hidden_publisher_listing_is_indistinguishable_from_missing_for_non_admin():
    connection = FakeListingConnection()
    free = get_listing_facts(
        args=ListingFactsArgs(listing_id=204),
        context=context(connection, "free"),
    )
    admin = get_listing_facts(
        args=ListingFactsArgs(listing_id=204),
        context=context(connection, "admin"),
    )

    assert free.items == []
    assert free.missing_requirements == ["listing_not_found_or_not_visible"]
    assert admin.items[0].value["listing_ref"] == "radar-listing:204"


def test_price_history_is_time_ordered_bounded_and_labeled_as_asking_price():
    bundle = get_price_history(
        args=HistoryArgs(listing_id=201, limit=2),
        context=context(FakeListingConnection()),
    )

    assert len(bundle.items) == 2
    observed = [item.as_of for item in bundle.items]
    assert observed == sorted(observed)
    assert all("asking_price_ty" in item.value for item in bundle.items)
    assert all("transaction_price" not in item.value for item in bundle.items)


def test_lot_history_follows_stored_canonical_identity_and_filters_hidden_publishers():
    connection = FakeListingConnection()
    free = get_lot_history(
        args=HistoryArgs(listing_id=201, limit=20),
        context=context(connection, "free"),
    )
    admin = get_lot_history(
        args=HistoryArgs(listing_id=201, limit=20),
        context=context(connection, "admin"),
    )

    assert [item.value["listing_ref"] for item in free.items] == [
        "radar-listing:201",
        "radar-listing:202",
    ]
    assert len(admin.items) == 3
    assert "0912" not in build_provider_bundle(admin, tier="admin").model_dump_json()


def test_history_for_missing_or_hidden_root_does_not_query_related_rows():
    connection = FakeListingConnection()
    bundle = get_lot_history(
        args=HistoryArgs(listing_id=204),
        context=context(connection, "vip"),
    )

    assert bundle.items == []
    assert len(connection.queries) == 1


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_kind"),
    [
        ("get_listing_facts", {"listing_id": 201}, SourceKind.LISTING),
        ("get_price_history", {"listing_id": 201, "limit": 2}, SourceKind.PRICE_HISTORY),
        ("get_lot_history", {"listing_id": 201, "limit": 2}, SourceKind.LOT_HISTORY),
    ],
)
def test_default_registry_dispatches_real_listing_handlers(tool_name, arguments, expected_kind):
    bundle = execute_tool(
        ToolCall(call_id=f"call-{tool_name}", name=tool_name, arguments=arguments),
        context(FakeListingConnection()),
        registry=DEFAULT_TOOL_REGISTRY,
    )

    assert bundle.items
    assert bundle.items[0].source_kind is expected_kind

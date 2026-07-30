import json
import uuid

import pytest

from db.connection import get_conn
from db.raw_listings import (
    canonical_raw_json,
    get_raw_listing_revisions,
    insert_raw_result,
    update_raw_listing_payload,
)
from db.schema import init_schema


@pytest.fixture(scope="module", autouse=True)
def _ensure_revision_schema():
    init_schema()


def _url(label: str) -> str:
    return f"https://example.test/raw-history/{label}-{uuid.uuid4().hex}"


def _delete(url: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM raw_listings WHERE url=?", (url,))


def test_insert_creates_initial_revision_and_identical_refresh_is_idempotent():
    url = _url("initial")
    try:
        inserted = insert_raw_result(
            "facebook",
            "post-initial",
            url,
            {"url": url, "text": "A"},
        )

        revisions = get_raw_listing_revisions(inserted.raw_id)
        assert [(row["revision_no"], row["change_kind"]) for row in revisions] == [
            (1, "initial")
        ]
        assert revisions[0]["raw_json"]["text"] == "A"

        changed = update_raw_listing_payload(
            inserted.raw_id,
            {"text": "A", "url": url},
            change_kind="source_refresh",
        )

        assert changed is False
        assert len(get_raw_listing_revisions(inserted.raw_id)) == 1
    finally:
        _delete(url)


def test_history_preserves_a_b_a_sequence_and_changed_fields():
    url = _url("sequence")
    try:
        inserted = insert_raw_result(
            "guland",
            "post-sequence",
            url,
            {"url": url, "text": "A", "price": 1},
        )

        assert update_raw_listing_payload(
            inserted.raw_id,
            {"url": url, "text": "B", "price": 1},
            change_kind="source_refresh",
            crawl_run_id=21,
        )
        assert update_raw_listing_payload(
            inserted.raw_id,
            {"url": url, "text": "A", "price": 1},
            change_kind="source_refresh",
            crawl_run_id=22,
        )

        revisions = get_raw_listing_revisions(inserted.raw_id)
        assert [row["revision_no"] for row in revisions] == [1, 2, 3]
        assert [row["raw_json"]["text"] for row in revisions] == ["A", "B", "A"]
        assert revisions[1]["changed_fields"] == ["text"]
        assert revisions[1]["crawl_run_id"] == 21
        assert revisions[2]["crawl_run_id"] == 22
    finally:
        _delete(url)


def test_legacy_row_seeds_old_snapshot_before_first_change():
    url = _url("legacy")
    try:
        with get_conn() as conn:
            raw_id = conn.execute(
                """
                INSERT INTO raw_listings (source, source_id, url, raw_json)
                VALUES ('facebook', 'legacy-post', ?, ?)
                """,
                (url, json.dumps({"url": url, "text": "old"})),
            ).lastrowid

        assert update_raw_listing_payload(
            raw_id,
            {"url": url, "text": "new"},
            change_kind="facebook_image_refresh",
        )

        revisions = get_raw_listing_revisions(raw_id)
        assert [row["raw_json"]["text"] for row in revisions] == ["old", "new"]
        assert [row["change_kind"] for row in revisions] == [
            "legacy_seed",
            "facebook_image_refresh",
        ]
    finally:
        _delete(url)


def test_canonical_raw_json_ignores_mapping_order_but_not_values():
    payload_a, hash_a = canonical_raw_json({"b": 2, "a": 1})
    payload_b, hash_b = canonical_raw_json({"a": 1, "b": 2})
    _, hash_changed = canonical_raw_json({"a": 1, "b": 3})

    assert payload_a == payload_b == '{"a":1,"b":2}'
    assert hash_a == hash_b
    assert hash_changed != hash_a

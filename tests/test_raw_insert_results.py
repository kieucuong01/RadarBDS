from contextlib import contextmanager
import uuid

import pytest

from db.connection import get_conn
import db.raw_listings as raw_listings
from db.raw_listings import RawInsertResult, insert_raw_result


def test_insert_raw_result_distinguishes_insert_and_duplicate():
    unique_url = f"https://guland.vn/post/raw-result-{uuid.uuid4().hex}-901"
    try:
        first = insert_raw_result(
            "guland",
            "901",
            unique_url,
            {"url": unique_url},
        )
        second = insert_raw_result(
            "guland",
            "901",
            unique_url,
            {"url": unique_url},
        )

        assert first.status == "inserted"
        assert first.raw_id
        assert second == RawInsertResult(status="duplicate", raw_id=None)
    finally:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM raw_listings WHERE source='guland' AND url=?",
                (unique_url,),
            )


def test_insert_raw_result_propagates_database_failure(monkeypatch):
    @contextmanager
    def broken_context():
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(raw_listings, "get_conn", broken_context)

    with pytest.raises(RuntimeError, match="database unavailable"):
        insert_raw_result(
            "guland",
            "902",
            "https://guland.vn/post/x-902",
            {"url": "x"},
        )

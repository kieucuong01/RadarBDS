from db.connection import PgRow, adapt_sql


def test_adapt_sql_translates_insert_or_ignore_and_placeholders():
    sql, params = adapt_sql(
        "INSERT OR IGNORE INTO raw_listings (source, url, raw_json) VALUES (?, ?, ?)",
        ("facebook", "https://x.test/1", "{}"),
    )

    assert "INSERT INTO raw_listings" in sql
    assert "ON CONFLICT (source, url) DO NOTHING" in sql
    assert "VALUES (%s, %s, %s)" in sql
    assert params == ("facebook", "https://x.test/1", "{}")


def test_adapt_sql_translates_common_datetime_expressions():
    sql, params = adapt_sql(
        """
        SELECT strftime('%Y-%m', COALESCE(posted_at, crawled_at)) AS month_key
        FROM listings
        WHERE datetime(COALESCE(crawled_at, '1970-01-01')) >= datetime('now', ?)
          AND datetime(started_at) >= datetime(?)
        """,
        ("-30 days", "2026-05-01"),
    )

    assert "to_char(COALESCE(posted_at, crawled_at)::timestamp, 'YYYY-MM')" in sql
    assert "(COALESCE(crawled_at, '1970-01-01'))::timestamp >= (CURRENT_TIMESTAMP + (%s::interval))" in sql
    assert "(started_at)::timestamp >= (%s::timestamp)" in sql
    assert params == ("-30 days", "2026-05-01")


def test_adapt_sql_translates_named_parameters():
    sql, params = adapt_sql(
        "UPDATE listings SET updated_at=datetime('now') WHERE id=:id",
        {"id": 42},
    )

    assert "updated_at=CURRENT_TIMESTAMP::text" in sql
    assert "id=%(id)s" in sql
    assert params == {"id": 42}


def test_adapt_sql_escapes_literal_percent_when_parameters_are_present():
    sql, params = adapt_sql(
        "SELECT 1 FROM listing_images WHERE img_url LIKE '%fbcdn.net%' AND listing_id=?",
        (123,),
    )

    assert "LIKE '%%fbcdn.net%%'" in sql
    assert "listing_id=%s" in sql
    assert params == (123,)


def test_pg_row_supports_sqlite_row_access_patterns():
    row = PgRow((123, "Tan An"), ("id", "ward"))

    assert row[0] == 123
    assert row["id"] == 123
    assert row["ward"] == "Tan An"
    assert dict(row) == {"id": 123, "ward": "Tan An"}
    assert row.get("missing", "fallback") == "fallback"

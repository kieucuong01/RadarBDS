import uuid

from db.connection import get_conn
from db.crawl_runs import load_recent_crawl_runs, summarize_recent_crawl_runs
from db.schema import init_schema


def test_weekly_health_casts_text_timestamps():
    init_schema()
    area = f"health-test-{uuid.uuid4().hex}"
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO crawl_runs
                (source, area, status, n_fetched, n_new, error_msg, started_at)
            VALUES
                ('guland', ?, 'done', 10, 2, '', CURRENT_TIMESTAMP::text),
                ('guland', ?, 'partial', 8, 1, 'one target failed', CURRENT_TIMESTAMP::text)
            """,
            (area, area),
        )

    try:
        with get_conn() as conn:
            recent = load_recent_crawl_runs(conn, limit=10)
            rows = summarize_recent_crawl_runs(conn, days=7)

        assert any(row["area"] == area for row in recent)
        by_source = {row["source"]: row for row in rows}
        assert by_source["guland"]["partial_runs"] >= 1
        assert by_source["guland"]["runs_with_errors"] >= 1
    finally:
        with get_conn() as conn:
            conn.execute("DELETE FROM crawl_runs WHERE area=?", (area,))

import json
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FacebookImageRefreshTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_fb_refresh.db"
        self.url = f"https://facebook.test/posts/{uuid.uuid4().hex}"
        connection.close_all()
        self.db_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        init_schema()

    def tearDown(self):
        from db import connection
        from db.connection import get_conn

        try:
            with get_conn() as conn:
                conn.execute(
                    "DELETE FROM raw_listings WHERE source='facebook' AND url=?",
                    (self.url,),
                )
        finally:
            connection.close_all()
            self.db_patch.stop()
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_refresh_existing_facebook_images_updates_raw_json(self):
        from db.connection import get_conn
        from cli.crawlers import _refresh_existing_facebook_images

        url = self.url
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO raw_listings (source, source_id, url, raw_json)
                VALUES ('facebook', 'fb1', ?, ?)
                """,
                (url, json.dumps({"url": url, "imgs": ["https://old.test/a.jpg"]})),
            )

        changed = _refresh_existing_facebook_images(
            url,
            {"imgs": ["https://scontent.test/fresh.jpg"], "_apify_raw": {"id": "fb1"}},
        )

        self.assertTrue(changed)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT raw_json FROM raw_listings WHERE source='facebook' AND url=?",
                (url,),
            ).fetchone()
        payload = json.loads(row["raw_json"])
        self.assertEqual(payload["imgs"], ["https://scontent.test/fresh.jpg"])
        self.assertEqual(payload["_apify_raw"], {"id": "fb1"})

    def test_same_url_content_edit_is_revisioned_even_when_images_are_unchanged(self):
        from db.connection import get_conn
        from db.raw_listings import get_raw_listing_revisions
        from cli.crawlers import _refresh_existing_facebook_images

        url = self.url
        old = {
            "url": url,
            "description": "Giá 2 tỷ",
            "imgs": ["https://scontent.test/same.jpg"],
            "manual_note": "preserve me",
        }
        with get_conn() as conn:
            raw_id = conn.execute(
                """
                INSERT INTO raw_listings (source, source_id, url, raw_json)
                VALUES ('facebook', 'fb-edit', ?, ?)
                """,
                (url, json.dumps(old)),
            ).lastrowid

        changed = _refresh_existing_facebook_images(
            url,
            {
                "url": url,
                "description": "Giá 1.9 tỷ",
                "imgs": ["https://scontent.test/same.jpg"],
            },
        )

        self.assertEqual(changed, raw_id)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT raw_json FROM raw_listings WHERE id=?",
                (raw_id,),
            ).fetchone()
        payload = json.loads(row["raw_json"])
        self.assertEqual(payload["description"], "Giá 1.9 tỷ")
        self.assertEqual(payload["manual_note"], "preserve me")
        revisions = get_raw_listing_revisions(raw_id)
        self.assertEqual(
            [item["raw_json"]["description"] for item in revisions],
            ["Giá 2 tỷ", "Giá 1.9 tỷ"],
        )
        self.assertIn("description", revisions[-1]["changed_fields"])


if __name__ == "__main__":
    unittest.main()

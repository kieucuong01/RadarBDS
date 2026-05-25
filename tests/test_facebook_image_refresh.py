import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FacebookImageRefreshTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_fb_refresh.db"
        connection.close_all()
        self.db_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        init_schema()

    def tearDown(self):
        from db import connection

        connection.close_all()
        self.db_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_refresh_existing_facebook_images_updates_raw_json(self):
        from db.connection import get_conn
        from cli.crawlers import _refresh_existing_facebook_images

        url = "https://facebook.test/posts/1"
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


if __name__ == "__main__":
    unittest.main()

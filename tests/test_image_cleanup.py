import json
import shutil
import sys
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class BrokerImageCleanupTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_image_cleanup.db"
        self.image_dir = self.tmpdir / "images"
        self.thumb_dir = self.image_dir / "thumbs"
        self.image_dir.mkdir()
        self.thumb_dir.mkdir()
        self.token = uuid.uuid4().hex
        self.source = f"test_guland_{self.token}"

        connection.close_all()
        self.db_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        init_schema()
        self._delete_test_rows()

    def tearDown(self):
        from db import connection

        try:
            self._delete_test_rows()
        finally:
            connection.close_all()
            self.db_patch.stop()
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _delete_test_rows(self):
        from db.connection import get_conn

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id FROM listings WHERE source=? OR url LIKE 'https://test-cleanup-%'",
                (self.source,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", ids)
                conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", ids)
            conn.execute("DELETE FROM raw_listings WHERE source=?", (self.source,))

    def _insert_listing(self, source=None, imgs=None):
        from db.connection import get_conn

        source = source or self.source
        imgs = imgs or []
        raw_json = {
            "url": f"https://test-cleanup-{self.token}.test/{source}/post/{uuid.uuid4().hex}",
            "imgs": imgs,
            "img_urls": list(imgs),
        }
        with get_conn() as conn:
            raw_id = conn.execute(
                """
                INSERT INTO raw_listings (source, source_id, url, raw_json)
                VALUES (?, 'src1', ?, ?)
                """,
                (source, raw_json["url"], json.dumps(raw_json)),
            ).lastrowid
            listing_id = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, area, ward, property_type,
                    tx_type, price_ty, price_per_m2, area_m2, crawled_at
                )
                VALUES (?, ?, 'src1', ?, 'Tin co anh', 'Tan An', 'Tan An', 'dat_nen',
                        'ban', 1.0, 10.0, 100.0, '2026-05-01T00:00:00')
                """,
                (raw_id, source, raw_json["url"]),
            ).lastrowid
        return listing_id, raw_id

    def _insert_image(self, listing_id, img_url, order=0, img_type="cover", local_name=None):
        from db.connection import get_conn

        local_path = None
        if local_name:
            local_path = f"data/images/{local_name}"
            (self.image_dir / local_name).write_bytes(b"fake image")
            (self.thumb_dir / f"{Path(local_name).stem}.webp").write_bytes(b"fake thumb")
        with get_conn() as conn:
            return conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order, img_type, local_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (listing_id, img_url, order, img_type, local_path),
            ).lastrowid

    def test_metadata_avatar_url_is_deleted_but_listing_image_is_kept(self):
        from db.connection import get_conn
        from cleansing.image_cleanup import clean_broker_images

        keep_url = "https://cdn.guland.vn/post/land-main.jpg"
        bad_url = "https://cdn.guland.vn/profile/avatar-broker.jpg"
        listing_id, _raw_id = self._insert_listing(imgs=[bad_url, keep_url])
        self._insert_image(listing_id, bad_url, order=0, img_type="cover")
        self._insert_image(listing_id, keep_url, order=1, img_type="cover")

        with mock.patch("cleansing.image_cleanup.DATA_DIR", self.tmpdir):
            stats = clean_broker_images(source=self.source, apply=True, strong=True)

        self.assertEqual(stats["deleted"], 1)
        self.assertEqual(stats["reasons"]["metadata"], 1)
        with get_conn() as conn:
            remaining = conn.execute(
                "SELECT img_url FROM listing_images WHERE listing_id=? ORDER BY img_order",
                (listing_id,),
            ).fetchall()
        self.assertEqual([r["img_url"] for r in remaining], [keep_url])

    def test_apply_deletes_row_local_file_thumbnail_and_raw_url(self):
        from db.connection import get_conn
        from cleansing.image_cleanup import clean_broker_images

        bad_url = "https://cdn.guland.vn/member/profile-photo.jpg"
        keep_url = "https://cdn.guland.vn/post/frontage.jpg"
        listing_id, raw_id = self._insert_listing(imgs=[bad_url, keep_url])
        self._insert_image(listing_id, bad_url, order=0, local_name="bad_0.jpg")
        self._insert_image(listing_id, keep_url, order=1, local_name="keep_1.jpg")

        with mock.patch("cleansing.image_cleanup.DATA_DIR", self.tmpdir):
            stats = clean_broker_images(source=self.source, apply=True, strong=True)

        self.assertEqual(stats["deleted"], 1)
        self.assertFalse((self.image_dir / "bad_0.jpg").exists())
        self.assertFalse((self.thumb_dir / "bad_0.webp").exists())
        self.assertTrue((self.image_dir / "keep_1.jpg").exists())
        with get_conn() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM listing_images WHERE listing_id=?", (listing_id,)).fetchone()[0],
                1,
            )
            payload = json.loads(
                conn.execute("SELECT raw_json FROM raw_listings WHERE id=?", (raw_id,)).fetchone()["raw_json"]
            )
        self.assertEqual(payload["imgs"], [keep_url])
        self.assertEqual(payload["img_urls"], [keep_url])

    def test_cv_face_detection_deletes_large_face_but_keeps_so_hong(self):
        from db.connection import get_conn
        import cleansing.image_cleanup as cleanup

        face_url = "https://cdn.guland.vn/post/person-in-frame.jpg"
        legal_url = "https://cdn.guland.vn/post/sohong-person.jpg"
        listing_id, _raw_id = self._insert_listing(imgs=[face_url, legal_url])
        self._insert_image(listing_id, face_url, order=0, img_type="cover", local_name="face_0.jpg")
        self._insert_image(listing_id, legal_url, order=1, img_type="so_hong", local_name="legal_1.jpg")

        with mock.patch.object(cleanup, "_detect_local_broker_face", return_value="face_large"), \
             mock.patch.object(cleanup, "DATA_DIR", self.tmpdir):
            stats = cleanup.clean_broker_images(source=self.source, apply=True, strong=True)

        self.assertEqual(stats["deleted"], 1)
        self.assertEqual(stats["reasons"]["face_large"], 1)
        with get_conn() as conn:
            remaining = conn.execute(
                "SELECT img_url FROM listing_images WHERE listing_id=?",
                (listing_id,),
            ).fetchall()
        self.assertEqual([r["img_url"] for r in remaining], [legal_url])


class BrokerImageCleanupCliTest(unittest.TestCase):
    def test_cmd_download_images_runs_cleanup_after_download(self):
        import cli.system as system

        args = SimpleNamespace(limit=25)
        with mock.patch.object(system, "init_schema"), \
             mock.patch("cleansing.download_images.download_images", return_value=3) as download, \
             mock.patch("cleansing.legal_image_classifier.classify_legal_images", return_value={"updated": 1}) as classify, \
             mock.patch("cleansing.image_cleanup.clean_broker_images", return_value={"deleted": 2}) as clean:
            system.cmd_download_images(args)

        download.assert_called_once_with(limit=25)
        classify.assert_called_once_with(apply=True, limit=25)
        clean.assert_called_once_with(apply=True, limit=25, strong=True)

    def test_cmd_clean_broker_images_forwards_cli_options(self):
        import cli.system as system

        args = SimpleNamespace(source="guland", apply=True, limit=100, strong=False)
        with mock.patch.object(system, "init_schema"), \
             mock.patch("cleansing.image_cleanup.clean_broker_images", return_value={
                 "scanned": 100,
                 "candidates": 7,
                 "deleted": 7,
                 "files_deleted": 3,
                 "thumbs_deleted": 3,
                 "raw_updated": 5,
                 "reasons": {"metadata": 4, "face_large": 3},
                 "apply": True,
             }) as clean:
            system.cmd_clean_broker_images(args)

        clean.assert_called_once_with(source="guland", apply=True, limit=100, strong=False)


if __name__ == "__main__":
    unittest.main()

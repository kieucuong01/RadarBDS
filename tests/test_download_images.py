import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class DownloadImagesRetryTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_images.db"
        self.token = uuid.uuid4().hex
        self.listing_url = f"https://facebook.test/post/{self.token}"
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
                "SELECT id FROM listings WHERE url=? OR url='https://facebook.test/post/1'",
                (self.listing_url,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", ids)
                conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", ids)

    def test_facebook_not_found_image_is_retryable(self):
        from db.connection import get_conn
        import cleansing.download_images as downloader

        image_dir = self.tmpdir / "images"
        image_dir.mkdir()
        with get_conn() as conn:
            listing_id = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, area, ward, property_type,
                    tx_type, price_ty, price_per_m2, area_m2, crawled_at
                )
                VALUES (
                    'facebook', ?, ?,
                    'Tin co anh', 'Tan An', 'Tan An', 'dat_nen',
                    'ban', 1.0, 10.0, 100.0, '2026-05-01T00:00:00'
                )
                """,
                (f"fb-{self.token}", self.listing_url),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order, local_path, crawled_at)
                VALUES (?, 'https://scontent.test/image.jpg', 0, 'NOT_FOUND', datetime('now'))
                """,
                (listing_id,),
            )

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"fake image bytes"

        with mock.patch.object(downloader, "DATA_DIR", image_dir), \
             mock.patch.object(downloader, "ensure_thumbnail", return_value=None), \
             mock.patch.object(downloader.urllib.request, "urlopen", return_value=FakeResponse()):
            count = downloader.download_images(limit=10, listing_id=listing_id)

        self.assertEqual(count, 1)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT local_path FROM listing_images WHERE listing_id=?",
                (listing_id,),
            ).fetchone()
        self.assertEqual(row["local_path"], f"data/images/{listing_id}_0.jpg")
        self.assertTrue((image_dir / f"{listing_id}_0.jpg").exists())

    def test_s3_mode_uploads_original_and_thumbnail_before_marking_local_path(self):
        from db.connection import get_conn
        import cleansing.download_images as downloader

        image_dir = self.tmpdir / "images"
        image_dir.mkdir()
        thumb_path = image_dir / "thumbs" / "0_0.webp"
        thumb_path.parent.mkdir()
        thumb_path.write_bytes(b"fake thumb")

        with get_conn() as conn:
            listing_id = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, area, ward, property_type,
                    tx_type, price_ty, price_per_m2, area_m2, crawled_at
                )
                VALUES (
                    'facebook', ?, ?,
                    'Tin co anh S3', 'Tan An', 'Tan An', 'dat_nen',
                    'ban', 1.0, 10.0, 100.0, '2026-05-01T00:00:00'
                )
                """,
                (f"fb-s3-{self.token}", f"{self.listing_url}/s3"),
            ).lastrowid
            thumb_path = image_dir / "thumbs" / f"{listing_id}_0.webp"
            thumb_path.write_bytes(b"fake thumb")
            conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order, local_path, crawled_at)
                VALUES (?, 'https://scontent.test/image-s3.jpg', 0, NULL, datetime('now'))
                """,
                (listing_id,),
            )

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"fake image bytes"

        uploads = []
        with mock.patch.dict("os.environ", {"RADAR_IMAGE_STORAGE": "s3"}, clear=False), \
             mock.patch.object(downloader, "DATA_DIR", image_dir), \
             mock.patch.object(downloader, "ensure_thumbnail", return_value=thumb_path), \
             mock.patch.object(downloader, "upload_file", side_effect=lambda path, key: uploads.append((Path(path).name, key))), \
             mock.patch.object(downloader.urllib.request, "urlopen", return_value=FakeResponse()):
            count = downloader.download_images(limit=10, listing_id=listing_id)

        self.assertEqual(count, 1)
        self.assertEqual(
            uploads,
            [
                (f"{listing_id}_0.jpg", f"data/images/{listing_id}_0.jpg"),
                (f"{listing_id}_0.webp", f"data/images/thumbs/{listing_id}_0.webp"),
            ],
        )
        with get_conn() as conn:
            row = conn.execute(
                "SELECT local_path FROM listing_images WHERE listing_id=?",
                (listing_id,),
            ).fetchone()
        self.assertEqual(row["local_path"], f"data/images/{listing_id}_0.jpg")


if __name__ == "__main__":
    unittest.main()

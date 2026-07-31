import io
import shutil
import tempfile
import unittest
import urllib.error
import uuid
from pathlib import Path
from unittest import mock

from PIL import Image


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (2, 2), (240, 30, 30)).save(output, "PNG")
    return output.getvalue()


PNG_BYTES = _png_bytes()


class FakeResponse:
    status = 200

    def __init__(self, body=PNG_BYTES, content_type="image/png", content_length=None):
        self.body = body
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(
                len(body) if content_length is None else content_length
            ),
        }

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, amount=-1):
        return self.body if amount is None or amount < 0 else self.body[:amount]


class DownloadImagesRetryTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.token = uuid.uuid4().hex
        self.listing_urls = []
        connection.close_all()
        init_schema()

    def tearDown(self):
        from db import connection
        from db.connection import get_conn

        try:
            with get_conn() as conn:
                for url in self.listing_urls:
                    conn.execute("DELETE FROM listings WHERE url=?", (url,))
        finally:
            connection.close_all()
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_image(
        self,
        *,
        source="facebook",
        img_url="https://scontent.test/image.jpg",
        img_order=0,
        local_path=None,
    ):
        from db.connection import get_conn

        url = f"https://example.test/{source}/{uuid.uuid4().hex}"
        self.listing_urls.append(url)
        with get_conn() as conn:
            listing_id = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, area, ward, property_type,
                    tx_type, price_ty, price_per_m2, area_m2, crawled_at
                )
                VALUES (?, ?, ?, 'Tin co anh', 'Tan An', 'Tan An', 'dat_nen',
                        'ban', 1.0, 10.0, 100.0, datetime('now'))
                """,
                (source, f"{source}-{uuid.uuid4().hex}", url),
            ).lastrowid
            image_id = conn.execute(
                """
                INSERT INTO listing_images
                    (listing_id, img_url, img_order, local_path, crawled_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (listing_id, img_url, img_order, local_path),
            ).lastrowid
        return listing_id, image_id

    def _local_path(self, image_id):
        from db.connection import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT local_path FROM listing_images WHERE id=?",
                (image_id,),
            ).fetchone()
        return row["local_path"]

    def test_object_path_is_unique_for_two_rows_in_the_same_slot(self):
        from cleansing.download_images import image_object_path

        first_path, first_key = image_object_path(
            image_id=101,
            listing_id=50,
            img_url="https://scontent.test/a.jpg?token=1",
            format_name="PNG",
            root=self.tmpdir,
        )
        second_path, second_key = image_object_path(
            image_id=102,
            listing_id=50,
            img_url="https://scontent.test/b.jpg?token=2",
            format_name="PNG",
            root=self.tmpdir,
        )

        self.assertNotEqual(first_path, second_path)
        self.assertNotEqual(first_key, second_key)
        self.assertIn("_101_", first_key)
        self.assertIn("_102_", second_key)
        self.assertTrue(first_key.endswith(".png"))

    def test_facebook_not_found_image_is_retryable(self):
        import cleansing.download_images as downloader

        listing_id, image_id = self._create_image(local_path="NOT_FOUND")
        image_dir = self.tmpdir / "images"
        image_dir.mkdir()

        with mock.patch.object(downloader, "DATA_DIR", image_dir), \
             mock.patch.object(downloader, "ensure_thumbnail", return_value=None), \
             mock.patch.object(downloader.urllib.request, "urlopen", return_value=FakeResponse()):
            count = downloader.download_images(limit=10, listing_id=listing_id)

        self.assertEqual(count, 1)
        local_path = self._local_path(image_id)
        self.assertIn(f"{listing_id}_{image_id}_", local_path)
        self.assertTrue((image_dir / Path(local_path).name).exists())

    def test_transient_http_error_retries_then_succeeds(self):
        import cleansing.download_images as downloader

        listing_id, image_id = self._create_image()
        image_dir = self.tmpdir / "images"
        image_dir.mkdir()
        transient = urllib.error.HTTPError(
            "https://scontent.test/image.jpg",
            503,
            "busy",
            {},
            None,
        )

        with mock.patch.object(downloader, "DATA_DIR", image_dir), \
             mock.patch.object(downloader, "ensure_thumbnail", return_value=None), \
             mock.patch.object(downloader.time, "sleep"), \
             mock.patch.object(
                 downloader.urllib.request,
                 "urlopen",
                 side_effect=[transient, FakeResponse()],
             ) as fetch:
            count = downloader.download_images(limit=10, listing_id=listing_id)

        self.assertEqual(count, 1)
        self.assertEqual(fetch.call_count, 2)
        self.assertIsNotNone(self._local_path(image_id))

    def test_html_body_is_rejected_without_partial_file(self):
        import cleansing.download_images as downloader

        listing_id, image_id = self._create_image()
        image_dir = self.tmpdir / "images"
        image_dir.mkdir()

        with mock.patch.object(downloader, "DATA_DIR", image_dir), \
             mock.patch.object(
                 downloader.urllib.request,
                 "urlopen",
                 return_value=FakeResponse(b"<html>blocked</html>", "text/html"),
             ):
            count = downloader.download_images(limit=10, listing_id=listing_id)

        self.assertEqual(count, 0)
        self.assertIsNone(self._local_path(image_id))
        self.assertEqual(list(image_dir.glob("*.part")), [])
        self.assertEqual(list(image_dir.glob("*.*")), [])

    def test_oversized_content_length_is_rejected_before_publish(self):
        import cleansing.download_images as downloader

        listing_id, image_id = self._create_image()
        image_dir = self.tmpdir / "images"
        image_dir.mkdir()
        response = FakeResponse(
            PNG_BYTES,
            "image/png",
            content_length=downloader.MAX_IMAGE_BYTES + 1,
        )

        with mock.patch.object(downloader, "DATA_DIR", image_dir), \
             mock.patch.object(downloader.urllib.request, "urlopen", return_value=response):
            count = downloader.download_images(limit=10, listing_id=listing_id)

        self.assertEqual(count, 0)
        self.assertIsNone(self._local_path(image_id))
        self.assertEqual(list(image_dir.iterdir()), [])

    def test_terminal_not_found_marks_row(self):
        import cleansing.download_images as downloader

        listing_id, image_id = self._create_image(source="guland")
        missing = urllib.error.HTTPError(
            "https://scontent.test/image.jpg",
            404,
            "missing",
            {},
            None,
        )
        with mock.patch.object(
            downloader.urllib.request,
            "urlopen",
            side_effect=missing,
        ):
            count = downloader.download_images(limit=10, listing_id=listing_id)

        self.assertEqual(count, 0)
        self.assertEqual(self._local_path(image_id), "NOT_FOUND")

    def test_s3_requires_original_and_thumbnail_upload_before_ready(self):
        import cleansing.download_images as downloader

        listing_id, image_id = self._create_image()
        image_dir = self.tmpdir / "images"
        thumb_dir = image_dir / "thumbs"
        thumb_dir.mkdir(parents=True)

        def make_thumb(path):
            thumb = thumb_dir / f"{Path(path).stem}.webp"
            thumb.write_bytes(b"webp")
            return thumb

        uploads = []

        def upload(path, key):
            uploads.append((Path(path).name, key))

        with mock.patch.dict("os.environ", {"RADAR_IMAGE_STORAGE": "s3"}, clear=False), \
             mock.patch.object(downloader, "DATA_DIR", image_dir), \
             mock.patch.object(downloader, "ensure_thumbnail", side_effect=make_thumb), \
             mock.patch.object(downloader, "upload_file", side_effect=upload), \
             mock.patch.object(downloader.urllib.request, "urlopen", return_value=FakeResponse()):
            count = downloader.download_images(limit=10, listing_id=listing_id)

        self.assertEqual(count, 1)
        self.assertEqual(len(uploads), 2)
        self.assertIn(f"{listing_id}_{image_id}_", uploads[0][1])
        self.assertTrue(uploads[1][1].startswith("data/images/thumbs/"))
        self.assertIsNotNone(self._local_path(image_id))

    def test_s3_thumbnail_upload_failure_does_not_mark_ready(self):
        import cleansing.download_images as downloader

        listing_id, image_id = self._create_image()
        image_dir = self.tmpdir / "images"
        thumb_dir = image_dir / "thumbs"
        thumb_dir.mkdir(parents=True)

        def make_thumb(path):
            thumb = thumb_dir / f"{Path(path).stem}.webp"
            thumb.write_bytes(b"webp")
            return thumb

        def fail_thumbnail(_path, key):
            if "/thumbs/" in key:
                raise RuntimeError("thumbnail upload failed")

        with mock.patch.dict("os.environ", {"RADAR_IMAGE_STORAGE": "s3"}, clear=False), \
             mock.patch.object(downloader, "DATA_DIR", image_dir), \
             mock.patch.object(downloader, "ensure_thumbnail", side_effect=make_thumb), \
             mock.patch.object(downloader, "upload_file", side_effect=fail_thumbnail), \
             mock.patch.object(downloader.urllib.request, "urlopen", return_value=FakeResponse()):
            count = downloader.download_images(limit=10, listing_id=listing_id)

        self.assertEqual(count, 0)
        self.assertIsNone(self._local_path(image_id))
        self.assertEqual(list(image_dir.glob("*.part")), [])


if __name__ == "__main__":
    unittest.main()

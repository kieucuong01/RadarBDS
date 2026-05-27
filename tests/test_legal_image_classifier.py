import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class LegalImageClassifierTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_legal_images.db"
        self.image_dir = self.tmpdir / "images"
        self.image_dir.mkdir()
        self.source = f"test_legal_{uuid.uuid4().hex}"
        connection.close_all()
        self.db_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        init_schema()

    def tearDown(self):
        from db import connection
        from db.connection import get_conn

        try:
            with get_conn() as conn:
                conn.execute("DELETE FROM listings WHERE source=?", (self.source,))
                conn.execute("DELETE FROM raw_listings WHERE source=?", (self.source,))
        except Exception:
            pass

        connection.close_all()
        self.db_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _insert_listing(self, source=None):
        from db.connection import get_conn

        source = source or self.source
        suffix = uuid.uuid4().hex
        url = f"https://{source}.test/post/{suffix}"
        with get_conn() as conn:
            raw_id = conn.execute(
                """
                INSERT INTO raw_listings (source, source_id, url, raw_json)
                VALUES (?, 'src1', ?, '{}')
                """,
                (source, url),
            ).lastrowid
            return conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, area, ward, property_type,
                    tx_type, price_ty, price_per_m2, area_m2, crawled_at
                )
                VALUES (?, ?, 'src1', ?, 'Tin co anh', 'Tan An', 'Tan An', 'dat_nen',
                        'ban', 1.0, 10.0, 100.0, '2026-05-01T00:00:00')
                """,
                (raw_id, source, url),
            ).lastrowid

    def _insert_image(self, listing_id, url, name=None, img_type="unknown"):
        from db.connection import get_conn

        local_path = f"data/images/{name}" if name else None
        with get_conn() as conn:
            return conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order, img_type, local_path)
                VALUES (?, ?, 0, ?, ?)
                """,
                (listing_id, url, img_type, local_path),
            ).lastrowid

    def _make_document_image(self, name):
        path = self.image_dir / name
        img = Image.new("RGB", (900, 1200), "white")
        draw = ImageDraw.Draw(img)
        for y in range(80, 1080, 45):
            draw.rectangle((80, y, 820, y + 10), fill="black")
        draw.rectangle((60, 60, 840, 1140), outline="black", width=8)
        img.save(path)
        return path

    def _make_property_image(self, name):
        path = self.image_dir / name
        img = Image.new("RGB", (900, 600), (60, 140, 80))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 360, 900, 600), fill=(95, 70, 45))
        draw.rectangle((250, 120, 650, 360), fill=(180, 180, 180))
        img.save(path)
        return path

    def _make_bright_street_image(self, name):
        path = self.image_dir / name
        img = Image.new("RGB", (900, 900), (180, 220, 245))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 360, 900, 900), fill=(210, 205, 190))
        draw.rectangle((670, 180, 895, 820), fill=(235, 235, 230))
        draw.line((0, 120, 900, 70), fill=(20, 20, 20), width=4)
        draw.line((0, 190, 900, 160), fill=(45, 45, 45), width=3)
        draw.rectangle((120, 520, 320, 700), fill=(130, 105, 80))
        img.save(path)
        return path

    def _make_white_room_image(self, name):
        path = self.image_dir / name
        img = Image.new("RGB", (900, 675), (232, 235, 228))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 500, 900, 675), fill=(150, 130, 105))
        for x in range(520, 870, 90):
            draw.line((x, 20, x, 500), fill=(120, 120, 115), width=3)
        draw.rectangle((50, 520, 300, 650), fill=(210, 20, 40))
        img.save(path)
        return path

    def test_url_keywords_classify_as_so_hong(self):
        from db.connection import get_conn
        import cleansing.legal_image_classifier as legal_image_classifier

        listing_id = self._insert_listing()
        self._insert_image(listing_id, "https://cdn.test/giay-chung-nhan-qsd.jpg")

        stats = legal_image_classifier.classify_legal_images(source=self.source, apply=True)

        self.assertEqual(stats["updated"], 1)
        self.assertEqual(stats["reasons"]["metadata"], 1)
        with get_conn() as conn:
            img_type = conn.execute(
                "SELECT img_type FROM listing_images WHERE listing_id=?",
                (listing_id,),
            ).fetchone()["img_type"]
        self.assertEqual(img_type, "so_hong")

    def test_document_like_local_image_is_classified(self):
        from db.connection import get_conn
        import cleansing.legal_image_classifier as legal_image_classifier

        listing_id = self._insert_listing()
        self._make_document_image("doc_0.jpg")
        self._insert_image(listing_id, "https://cdn.test/post/doc.jpg", name="doc_0.jpg")

        with mock.patch.object(legal_image_classifier, "DATA_DIR", self.tmpdir):
            stats = legal_image_classifier.classify_legal_images(source=self.source, apply=True)

        self.assertEqual(stats["updated"], 1)
        self.assertEqual(stats["reasons"]["document_cv"], 1)
        with get_conn() as conn:
            img_type = conn.execute(
                "SELECT img_type FROM listing_images WHERE listing_id=?",
                (listing_id,),
            ).fetchone()["img_type"]
        self.assertEqual(img_type, "so_hong")

    def test_property_or_avatar_image_is_not_classified(self):
        from db.connection import get_conn
        import cleansing.legal_image_classifier as legal_image_classifier

        listing_id = self._insert_listing()
        self._make_property_image("land_0.jpg")
        self._insert_image(listing_id, "https://cdn.test/post/land.jpg", name="land_0.jpg")
        self._insert_image(listing_id, "https://cdn.test/profile/avatar.jpg")

        with mock.patch.object(legal_image_classifier, "DATA_DIR", self.tmpdir):
            stats = legal_image_classifier.classify_legal_images(source=self.source, apply=True)

        self.assertEqual(stats["updated"], 0)
        with get_conn() as conn:
            types = [
                r["img_type"]
                for r in conn.execute(
                    "SELECT img_type FROM listing_images WHERE listing_id=? ORDER BY id",
                    (listing_id,),
                ).fetchall()
            ]
        self.assertEqual(types, ["unknown", "unknown"])

    def test_bright_street_or_white_room_image_is_not_classified(self):
        from db.connection import get_conn
        import cleansing.legal_image_classifier as legal_image_classifier

        listing_id = self._insert_listing()
        self._make_bright_street_image("street_0.jpg")
        self._make_white_room_image("room_0.jpg")
        self._insert_image(listing_id, "https://cdn.test/post/street.jpg", name="street_0.jpg")
        self._insert_image(listing_id, "https://cdn.test/post/room.jpg", name="room_0.jpg")

        with mock.patch.object(legal_image_classifier, "DATA_DIR", self.tmpdir):
            stats = legal_image_classifier.classify_legal_images(source=self.source, apply=True)

        self.assertEqual(stats["updated"], 0)
        with get_conn() as conn:
            types = [
                r["img_type"]
                for r in conn.execute(
                    "SELECT img_type FROM listing_images WHERE listing_id=? ORDER BY id",
                    (listing_id,),
                ).fetchall()
            ]
        self.assertEqual(types, ["unknown", "unknown"])

    def test_clean_legal_image_tags_demotes_stale_false_positive(self):
        from db.connection import get_conn
        import cleansing.legal_image_classifier as legal_image_classifier

        listing_id = self._insert_listing()
        self._make_bright_street_image("street_false_positive.jpg")
        self._make_document_image("doc_true_positive.jpg")
        self._insert_image(
            listing_id,
            "https://cdn.test/post/street.jpg",
            name="street_false_positive.jpg",
            img_type="so_hong",
        )
        self._insert_image(
            listing_id,
            "https://cdn.test/post/doc.jpg",
            name="doc_true_positive.jpg",
            img_type="so_hong",
        )

        with mock.patch.object(legal_image_classifier, "DATA_DIR", self.tmpdir):
            stats = legal_image_classifier.clean_legal_image_tags(source=self.source, apply=True)

        self.assertEqual(stats["demoted"], 1)
        self.assertEqual(stats["kept"], 1)
        with get_conn() as conn:
            types = [
                r["img_type"]
                for r in conn.execute(
                    "SELECT img_type FROM listing_images WHERE listing_id=? ORDER BY id",
                    (listing_id,),
                ).fetchall()
            ]
        self.assertEqual(types, ["cover", "so_hong"])


if __name__ == "__main__":
    unittest.main()

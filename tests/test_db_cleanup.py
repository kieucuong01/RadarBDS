import shutil
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class DbCleanupTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_cleanup.db"
        self.images_dir = self.tmpdir / "images"
        self.images_dir.mkdir()
        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://cleanup-listing-{self.token}.test"
        self.raw_url_prefix = f"https://cleanup-raw-{self.token}.test"
        self.user_prefix = f"cleanup-user-{self.token}"
        self.listing_ids = []
        self.raw_ids = []

        connection.close_all()
        self.db_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        init_schema()

        from cli import cleanup as cleanup_mod

        self.img_patch = mock.patch.object(cleanup_mod, "IMAGES_DIR", self.images_dir)
        self.img_patch.start()
        self.db_path_patch = mock.patch.object(cleanup_mod, "DB_PATH", self.db_path, create=True)
        self.db_path_patch.start()
        self._delete_test_rows()

    def tearDown(self):
        from db import connection

        self._delete_test_rows()
        self.img_patch.stop()
        self.db_path_patch.stop()
        connection.close_all()
        self.db_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _listing_url(self, url: str) -> str:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return f"{self.url_prefix}/{url}"

    def _delete_test_rows(self):
        from db.connection import get_conn

        try:
            with get_conn() as conn:
                conn.execute("DELETE FROM user_sessions WHERE token LIKE ?", (f"{self.user_prefix}%",))
                conn.execute("DELETE FROM users WHERE identifier LIKE ?", (f"{self.user_prefix}%",))
                rows = conn.execute(
                    "SELECT id FROM listings WHERE url LIKE ?",
                    (f"{self.url_prefix}%",),
                ).fetchall()
                ids = {r["id"] for r in rows}
                ids.update(self.listing_ids)
                if ids:
                    placeholders = ",".join("?" * len(ids))
                    params = list(ids)
                    conn.execute(f"DELETE FROM notification_log WHERE listing_id IN ({placeholders})", params)
                    conn.execute(f"DELETE FROM price_history WHERE listing_id IN ({placeholders})", params)
                    conn.execute(f"DELETE FROM valuation_results WHERE listing_id IN ({placeholders})", params)
                    conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", params)
                    conn.execute(f"DELETE FROM legal_verifications WHERE listing_id IN ({placeholders})", params)
                    conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", params)
                conn.execute("DELETE FROM raw_listings WHERE url LIKE ?", (f"{self.raw_url_prefix}%",))
        except Exception:
            pass

    def _run_cleanup(self, **kwargs):
        from cli.cleanup import run_cleanup

        return run_cleanup(
            listing_url_prefix=self.url_prefix,
            raw_url_prefix=self.raw_url_prefix,
            user_identifier_prefix=self.user_prefix,
            **kwargs,
        )

    def _insert_listing(
        self,
        *,
        url,
        probably_sold=0,
        last_seen_at=None,
        crawled_at=None,
        raw_id=None,
        price_ty=1.0,
        area_m2=100.0,
    ):
        from db.connection import get_conn

        full_url = self._listing_url(url)
        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, probably_sold,
                    crawled_at, last_seen_at, price_ty, area_m2
                ) VALUES (?, 'facebook', ?, ?, 'T', ?, ?, ?, ?, ?)
                """,
                (
                    raw_id,
                    f"{Path(url).name}-{self.token}",
                    full_url,
                    probably_sold,
                    crawled_at or "2026-05-01T00:00:00",
                    last_seen_at,
                    price_ty,
                    area_m2,
                ),
            )
            listing_id = cur.lastrowid
            self.listing_ids.append(listing_id)
            return listing_id

    def _insert_raw(self, source_id, crawled_at):
        from db.connection import get_conn

        scoped_source_id = f"{source_id}-{self.token}"
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json, crawled_at) "
                "VALUES ('facebook', ?, ?, '{}', ?)",
                (scoped_source_id, f"{self.raw_url_prefix}/{source_id}", crawled_at),
            )
            raw_id = cur.lastrowid
            self.raw_ids.append(raw_id)
            return raw_id

    def _insert_notification(self, listing_id, sent_at):
        from db.connection import get_conn

        with get_conn() as conn:
            user = conn.execute(
                "INSERT INTO users (identifier, identifier_type, password_hash, tier) "
                "VALUES (?, 'phone', 'hash', 'vip')",
                (f"{self.user_prefix}-{listing_id}-{sent_at}",),
            ).lastrowid
            conn.execute(
                "INSERT INTO notification_log "
                "(user_id, listing_id, channel, notified_price_ty, sent_at) "
                "VALUES (?, ?, 'telegram', 1.0, ?)",
                (user, listing_id, sent_at),
            )

    def _insert_listing_image(self, listing_id, local_path):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute(
                "INSERT INTO listing_images (listing_id, img_url, local_path) "
                "VALUES (?, ?, ?)",
                (listing_id, f"https://cdn.test/{self.token}/{local_path}", local_path),
            )

    def _touch_image_file(self, name, content=b"abc"):
        p = self.images_dir / name
        p.write_bytes(content)
        return p

    def _counts(self):
        from db.connection import get_conn

        with get_conn() as conn:
            return {
                "listings": conn.execute(
                    "SELECT COUNT(*) FROM listings WHERE url LIKE ?",
                    (f"{self.url_prefix}%",),
                ).fetchone()[0],
                "raw": conn.execute(
                    "SELECT COUNT(*) FROM raw_listings WHERE url LIKE ?",
                    (f"{self.raw_url_prefix}%",),
                ).fetchone()[0],
                "notif": conn.execute(
                    """
                    SELECT COUNT(*)
                      FROM notification_log n
                      JOIN users u ON u.id = n.user_id
                     WHERE u.identifier LIKE ?
                    """,
                    (f"{self.user_prefix}%",),
                ).fetchone()[0],
                "images": conn.execute(
                    """
                    SELECT COUNT(*)
                      FROM listing_images li
                      JOIN listings l ON l.id = li.listing_id
                     WHERE l.url LIKE ?
                    """,
                    (f"{self.url_prefix}%",),
                ).fetchone()[0],
            }

    def test_dry_run_does_not_delete(self):
        self._insert_listing(url="u1", probably_sold=1, last_seen_at="2025-01-01T00:00:00")
        self._insert_raw("orphan-1", "2025-01-01T00:00:00")
        lid = self._insert_listing(url="u2", probably_sold=1, last_seen_at="2026-05-01T00:00:00")
        self._insert_notification(lid, "2024-01-01T00:00:00")

        before = self._counts()
        stats = self._run_cleanup(apply=False)
        after = self._counts()

        self.assertGreater(stats["sold_listings"], 0)
        self.assertGreater(stats["orphan_raw"], 0)
        self.assertGreater(stats["old_notifications"], 0)
        self.assertEqual(before, after)

    def test_sold_listings_older_than_90d_deleted(self):
        now = datetime.now(timezone.utc)
        old = self._insert_listing(
            url="u-old",
            probably_sold=1,
            last_seen_at=(now - timedelta(days=91)).isoformat(),
        )
        recent = self._insert_listing(
            url="u-recent",
            probably_sold=1,
            last_seen_at=(now - timedelta(days=89)).isoformat(),
        )
        active = self._insert_listing(url="u-active", probably_sold=0, last_seen_at="2024-01-01T00:00:00")

        self._run_cleanup(apply=True, vacuum=False)

        from db.connection import get_conn

        with get_conn() as conn:
            ids = {
                r[0]
                for r in conn.execute(
                    "SELECT id FROM listings WHERE url LIKE ?",
                    (f"{self.url_prefix}%",),
                ).fetchall()
            }
        self.assertNotIn(old, ids)
        self.assertIn(recent, ids)
        self.assertIn(active, ids)

    def test_cascade_removes_dependent_rows(self):
        from db.connection import get_conn

        lid = self._insert_listing(url="u-cascade", probably_sold=1, last_seen_at="2024-01-01T00:00:00")
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO valuation_results (listing_id, mos_pct, is_signal) VALUES (?, 30.0, 1)",
                (lid,),
            )
            conn.execute("INSERT INTO price_history (listing_id, price_ty) VALUES (?, 2.0)", (lid,))

        self._run_cleanup(apply=True, vacuum=False)

        with get_conn() as conn:
            n_val = conn.execute(
                "SELECT COUNT(*) FROM valuation_results WHERE listing_id=?",
                (lid,),
            ).fetchone()[0]
            n_ph = conn.execute(
                "SELECT COUNT(*) FROM price_history WHERE listing_id=?",
                (lid,),
            ).fetchone()[0]
        self.assertEqual(n_val, 0)
        self.assertEqual(n_ph, 0)

    def test_orphan_raw_listings_deleted(self):
        from db.connection import get_conn

        orphan_raw = self._insert_raw("orphan-A", "2025-01-01T00:00:00")
        linked_raw = self._insert_raw("linked-A", "2025-01-01T00:00:00")
        self._insert_listing(url="u-linked", raw_id=linked_raw)

        self._run_cleanup(apply=True, vacuum=False)

        with get_conn() as conn:
            ids = {
                r[0]
                for r in conn.execute(
                    "SELECT id FROM raw_listings WHERE url LIKE ?",
                    (f"{self.raw_url_prefix}%",),
                ).fetchall()
            }
        self.assertNotIn(orphan_raw, ids)
        self.assertIn(linked_raw, ids)

    def test_raw_not_orphan_if_listing_exists(self):
        from db.connection import get_conn

        raw_id = self._insert_raw("kept", "2024-01-01T00:00:00")
        self._insert_listing(url="u-keep", raw_id=raw_id)

        stats = self._run_cleanup(apply=True, vacuum=False)
        self.assertEqual(stats["orphan_raw"], 0)
        with get_conn() as conn:
            n = conn.execute("SELECT COUNT(*) FROM raw_listings WHERE id=?", (raw_id,)).fetchone()[0]
        self.assertEqual(n, 1)

    def test_old_notifications_deleted(self):
        from db.connection import get_conn

        lid = self._insert_listing(url="u-notif")
        self._insert_notification(lid, "2024-01-01T00:00:00")
        self._insert_notification(lid, "2026-05-01T00:00:00")

        self._run_cleanup(apply=True, vacuum=False)

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT sent_at FROM notification_log WHERE listing_id = ? ORDER BY sent_at",
                (lid,),
            ).fetchall()
        sent_ats = [r[0] for r in rows]
        self.assertEqual(len(sent_ats), 1)
        self.assertEqual(sent_ats[0], "2026-05-01T00:00:00")

    def test_unpriceable_listings_and_raw_are_deleted(self):
        from db.connection import get_conn

        raw_missing_price = self._insert_raw("missing-price", "2026-05-01T00:00:00")
        raw_missing_area = self._insert_raw("missing-area", "2026-05-01T00:00:00")
        raw_good = self._insert_raw("good", "2026-05-01T00:00:00")
        missing_price = self._insert_listing(
            url="u-missing-price",
            raw_id=raw_missing_price,
            price_ty=None,
            area_m2=100.0,
        )
        missing_area = self._insert_listing(
            url="u-missing-area",
            raw_id=raw_missing_area,
            price_ty=1.0,
            area_m2=None,
        )
        good = self._insert_listing(
            url="u-good",
            raw_id=raw_good,
            price_ty=1.0,
            area_m2=100.0,
        )

        stats = self._run_cleanup(apply=True, vacuum=False)

        self.assertGreaterEqual(stats["unpriceable_listings"], 2)
        self.assertGreaterEqual(stats["unpriceable_raw"], 2)
        with get_conn() as conn:
            listing_ids = {
                r[0]
                for r in conn.execute(
                    "SELECT id FROM listings WHERE url LIKE ?",
                    (f"{self.url_prefix}%",),
                ).fetchall()
            }
            raw_ids = {
                r[0]
                for r in conn.execute(
                    "SELECT id FROM raw_listings WHERE url LIKE ?",
                    (f"{self.raw_url_prefix}%",),
                ).fetchall()
            }
        self.assertNotIn(missing_price, listing_ids)
        self.assertNotIn(missing_area, listing_ids)
        self.assertIn(good, listing_ids)
        self.assertNotIn(raw_missing_price, raw_ids)
        self.assertNotIn(raw_missing_area, raw_ids)
        self.assertIn(raw_good, raw_ids)

    def test_orphan_image_files_unlinked(self):
        lid = self._insert_listing(url="u-img")
        kept = self._touch_image_file("kept_0.jpg")
        orphan_a = self._touch_image_file("orphan_a.jpg", b"x" * 100)
        orphan_b = self._touch_image_file("orphan_b.jpg", b"y" * 200)
        self._insert_listing_image(lid, f"data/images/{kept.name}")

        stats = self._run_cleanup(apply=True, vacuum=False)

        self.assertEqual(stats["orphan_image_files"], 2)
        self.assertEqual(stats["bytes_freed"], 300)
        self.assertTrue(kept.exists())
        self.assertFalse(orphan_a.exists())
        self.assertFalse(orphan_b.exists())

    def test_custom_thresholds(self):
        from db.connection import get_conn

        lid = self._insert_listing(url="u-60d", probably_sold=1, last_seen_at="2026-03-15T00:00:00")

        self._run_cleanup(apply=True, sold_days=30, vacuum=False)

        with get_conn() as conn:
            n = conn.execute("SELECT COUNT(*) FROM listings WHERE id=?", (lid,)).fetchone()[0]
        self.assertEqual(n, 0)

    def test_idempotent_second_run_noop(self):
        self._insert_listing(url="u1", probably_sold=1, last_seen_at="2024-01-01T00:00:00")
        self._insert_raw("orphan-X", "2024-01-01T00:00:00")
        lid = self._insert_listing(url="u2")
        self._insert_notification(lid, "2024-01-01T00:00:00")
        self._touch_image_file("orphan_z.jpg")

        self._run_cleanup(apply=True, vacuum=False)
        stats = self._run_cleanup(apply=True, vacuum=False)

        self.assertEqual(stats["sold_listings"], 0)
        self.assertEqual(stats["orphan_raw"], 0)
        self.assertEqual(stats["unpriceable_listings"], 0)
        self.assertEqual(stats["old_notifications"], 0)
        self.assertEqual(stats["orphan_image_files"], 0)


if __name__ == "__main__":
    unittest.main()

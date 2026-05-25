import json
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Optional
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class VipNotifyTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_vip_notify.db"
        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://vip-notify-{self.token}.test"
        self.ward = f"VipWard{self.token[:8]}"
        self.since = "2099-01-15T00:00:00"
        self.first_seen = "2099-01-15T08:00:00"
        self.vip_expires = "2100-01-01T00:00:00"
        self.user_ids = []
        self.listing_ids = []
        connection.close_all()
        self.patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.patch.start()
        init_schema()
        self._delete_test_rows()

    def tearDown(self):
        from db import connection

        self._delete_test_rows()
        connection.close_all()
        self.patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _chat(self, chat_id: str) -> str:
        return f"{chat_id}-{self.token}"

    def _delete_test_rows(self):
        from db.connection import get_conn

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id FROM listings WHERE url LIKE ?",
                (f"{self.url_prefix}%",),
            ).fetchall()
            listing_ids = {r["id"] for r in rows}
            listing_ids.update(self.listing_ids)
            user_rows = conn.execute(
                "SELECT id FROM users WHERE identifier LIKE ?",
                (f"%{self.token}%",),
            ).fetchall()
            user_ids = {r["id"] for r in user_rows}
            user_ids.update(self.user_ids)
            if listing_ids:
                placeholders = ",".join("?" * len(listing_ids))
                params = list(listing_ids)
                conn.execute(f"DELETE FROM notification_log WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM valuation_results WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM legal_verifications WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", params)
            if user_ids:
                placeholders = ",".join("?" * len(user_ids))
                params = list(user_ids)
                conn.execute(f"DELETE FROM user_watchlists WHERE user_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM user_sessions WHERE user_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM notification_log WHERE user_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM users WHERE id IN ({placeholders})", params)

    def _insert_user(self, tier: str, chat_id: str, vip_expires_at: Optional[str] = None) -> int:
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (
                    identifier, identifier_type, password_hash, tier,
                    vip_expires_at, telegram_chat_id, notify_email, notify_telegram
                ) VALUES (?, 'phone', 'hash', ?, ?, ?, 0, 1)
                """,
                (f"{tier}-{chat_id}-{self.token}", tier, vip_expires_at, self._chat(chat_id)),
            )
            user_id = cur.lastrowid
            self.user_ids.append(user_id)
            return user_id

    def _insert_watchlist(self, user_id: int) -> None:
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO user_watchlists (
                    user_id, name, wards, prop_types, mos_min,
                    notify_email, notify_telegram, active
                ) VALUES (?, 'TDM deals', ?, ?, 0, 0, 1, 1)
                """,
                (user_id, json.dumps([self.ward]), json.dumps(["dat_nen"])),
            )

    def _insert_signal(self) -> int:
        from db.connection import get_conn

        idx = len(self.listing_ids) + 1
        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, ward, property_type,
                    price_ty, area_m2, first_seen_at, crawled_at,
                    probably_sold, is_blacklisted, review_hidden
                ) VALUES (
                    'facebook', ?, ?,
                    'VIP signal', ?, 'dat_nen',
                    2.1, 100, ?, ?,
                    0, 0, 0
                )
                """,
                (
                    f"notify-{self.token}-{idx}",
                    f"{self.url_prefix}/notify-{idx}",
                    self.ward,
                    self.first_seen,
                    self.first_seen,
                ),
            )
            listing_id = cur.lastrowid
            self.listing_ids.append(listing_id)
            conn.execute(
                """
                INSERT INTO valuation_results (listing_id, mos_pct, is_signal)
                VALUES (?, 28.0, 1)
                """,
                (listing_id,),
            )
            return listing_id

    def _seed_notification(self, user_id, listing_id, channel, notified_price_ty, sent_at=None):
        from db.connection import get_conn

        with get_conn() as conn:
            if sent_at:
                conn.execute(
                    "INSERT INTO notification_log (user_id, listing_id, channel, notified_price_ty, sent_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, listing_id, channel, notified_price_ty, sent_at),
                )
            else:
                conn.execute(
                    "INSERT INTO notification_log (user_id, listing_id, channel, notified_price_ty) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, listing_id, channel, notified_price_ty),
                )

    def _set_listing_price(self, listing_id, price_ty):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute("UPDATE listings SET price_ty=? WHERE id=?", (price_ty, listing_id))

    def _notif_rows(self):
        from db.connection import get_conn

        placeholders = ",".join("?" * len(self.listing_ids))
        with get_conn() as conn:
            return conn.execute(
                "SELECT user_id, listing_id, channel, notified_price_ty "
                f"FROM notification_log WHERE listing_id IN ({placeholders}) ORDER BY id",
                list(self.listing_ids),
            ).fetchall()

    def test_push_sends_only_to_active_vip_watchlists(self):
        from cli.notify import push_new_listings_to_vip
        from db.connection import get_conn

        free_id = self._insert_user("free", "free-chat")
        vip_id = self._insert_user("vip", "vip-chat", self.vip_expires)
        self._insert_watchlist(free_id)
        self._insert_watchlist(vip_id)
        listing_id = self._insert_signal()

        with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True) as send:
            stats = push_new_listings_to_vip(since=self.since)

        self.assertEqual(stats["matched_users"], 1)
        self.assertEqual(stats["telegram_sent"], 1)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0], self._chat("vip-chat"))

        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT user_id, listing_id, channel, notified_price_ty
                FROM notification_log
                WHERE listing_id = ?
                ORDER BY id
                """,
                (listing_id,),
            ).fetchall()
        self.assertEqual([tuple(r) for r in rows], [(vip_id, listing_id, "telegram", 2.1)])

    def _vip_setup(self):
        vip_id = self._insert_user("vip", "vip-chat", self.vip_expires)
        self._insert_watchlist(vip_id)
        listing_id = self._insert_signal()
        return vip_id, listing_id

    def test_first_push_records_price(self):
        from cli.notify import push_new_listings_to_vip

        self._vip_setup()

        with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True):
            stats = push_new_listings_to_vip(since=self.since)

        self.assertEqual(stats["telegram_sent"], 1)
        rows = self._notif_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["notified_price_ty"], 2.1)

    def test_same_price_recheck_skips(self):
        from cli.notify import push_new_listings_to_vip

        vip_id, listing_id = self._vip_setup()
        self._seed_notification(vip_id, listing_id, "telegram", 2.1)

        with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True) as send:
            stats = push_new_listings_to_vip(since=self.since)

        self.assertEqual(stats["telegram_sent"], 0)
        self.assertEqual(send.call_count, 0)
        self.assertEqual(len(self._notif_rows()), 1)

    def test_small_drop_below_threshold_skips(self):
        from cli.notify import push_new_listings_to_vip

        vip_id, listing_id = self._vip_setup()
        self._seed_notification(vip_id, listing_id, "telegram", 2.0)
        self._set_listing_price(listing_id, 1.95)

        with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True) as send:
            stats = push_new_listings_to_vip(since=self.since)

        self.assertEqual(stats["telegram_sent"], 0)
        self.assertEqual(send.call_count, 0)
        self.assertEqual(len(self._notif_rows()), 1)

    def test_drop_at_or_above_threshold_realerts(self):
        from cli.notify import push_new_listings_to_vip

        vip_id, listing_id = self._vip_setup()
        self._seed_notification(vip_id, listing_id, "telegram", 2.0)
        self._set_listing_price(listing_id, 1.80)

        with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True) as send:
            stats = push_new_listings_to_vip(since=self.since)

        self.assertEqual(stats["telegram_sent"], 1)
        self.assertEqual(send.call_count, 1)
        listings_arg = send.call_args.args[1]
        self.assertEqual(len(listings_arg), 1)
        self.assertEqual(listings_arg[0]["_prev_notified_price_ty"], 2.0)
        rows = self._notif_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["notified_price_ty"], 1.80)

    def test_legacy_null_price_row_skips(self):
        from cli.notify import push_new_listings_to_vip

        vip_id, listing_id = self._vip_setup()
        self._seed_notification(vip_id, listing_id, "telegram", None)

        with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True) as send:
            stats = push_new_listings_to_vip(since=self.since)

        self.assertEqual(stats["telegram_sent"], 0)
        self.assertEqual(send.call_count, 0)

    def test_realert_message_contains_drop_context(self):
        from cli.notify import push_new_listings_to_vip

        vip_id, listing_id = self._vip_setup()
        self._seed_notification(vip_id, listing_id, "telegram", 2.0)
        self._set_listing_price(listing_id, 1.80)

        with mock.patch("alerts.telegram.send_message_to", return_value=True) as send:
            push_new_listings_to_vip(since=self.since)

        self.assertEqual(send.call_count, 1)
        text = send.call_args.args[1]
        self.assertIn("-10.0%", text)
        self.assertIn("TIN", text)

    def test_threshold_boundary_inclusive(self):
        from cli.notify import push_new_listings_to_vip

        vip_id, listing_id = self._vip_setup()
        self._seed_notification(vip_id, listing_id, "telegram", 2.0)
        self._set_listing_price(listing_id, 1.90)

        with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True) as send:
            stats = push_new_listings_to_vip(since=self.since)

        self.assertEqual(stats["telegram_sent"], 1)
        self.assertEqual(send.call_count, 1)

    def test_custom_threshold_via_settings(self):
        from cli import notify as notify_mod

        vip_id, listing_id = self._vip_setup()
        self._seed_notification(vip_id, listing_id, "telegram", 2.0)

        with mock.patch.object(notify_mod, "SIGNAL_REALERT_THRESHOLD_PCT", 15.0):
            self._set_listing_price(listing_id, 1.85)
            with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True) as send1:
                stats1 = notify_mod.push_new_listings_to_vip(since=self.since)
            self.assertEqual(stats1["telegram_sent"], 0)
            self.assertEqual(send1.call_count, 0)

            self._set_listing_price(listing_id, 1.65)
            with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True) as send2:
                stats2 = notify_mod.push_new_listings_to_vip(since=self.since)
            self.assertEqual(stats2["telegram_sent"], 1)
            self.assertEqual(send2.call_count, 1)


if __name__ == "__main__":
    unittest.main()

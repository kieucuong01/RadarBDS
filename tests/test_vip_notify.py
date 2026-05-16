import json
import shutil
import sys
import tempfile
import unittest
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
        connection.close_all()
        self.patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.patch.start()
        init_schema()

    def tearDown(self):
        from db import connection

        connection.close_all()
        self.patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

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
                (f"{tier}-{chat_id}", tier, vip_expires_at, chat_id),
            )
            return cur.lastrowid

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
                (user_id, json.dumps(["Tân An"]), json.dumps(["dat_nen"])),
            )

    def _insert_signal(self) -> int:
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, ward, property_type,
                    price_ty, area_m2, first_seen_at, crawled_at,
                    probably_sold, is_blacklisted, review_hidden
                ) VALUES (
                    'facebook', 'notify-1', 'https://example.test/notify-1',
                    'VIP signal', 'Tân An', 'dat_nen',
                    2.1, 100, '2026-05-15T08:00:00', '2026-05-15T08:00:00',
                    0, 0, 0
                )
                """
            )
            listing_id = cur.lastrowid
            conn.execute(
                """
                INSERT INTO valuation_results (listing_id, mos_pct, is_signal)
                VALUES (?, 28.0, 1)
                """,
                (listing_id,),
            )
            return listing_id

    def test_push_sends_only_to_active_vip_watchlists(self):
        from cli.notify import push_new_listings_to_vip
        from db.connection import get_conn

        free_id = self._insert_user("free", "free-chat")
        vip_id = self._insert_user("vip", "vip-chat", "2099-01-01T00:00:00")
        self._insert_watchlist(free_id)
        self._insert_watchlist(vip_id)
        listing_id = self._insert_signal()

        with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True) as send:
            stats = push_new_listings_to_vip(since="2026-05-15T00:00:00")

        self.assertEqual(stats["matched_users"], 1)
        self.assertEqual(stats["telegram_sent"], 1)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0], "vip-chat")

        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT user_id, listing_id, channel
                FROM notification_log
                ORDER BY id
                """
            ).fetchall()
        self.assertEqual([tuple(r) for r in rows], [(vip_id, listing_id, "telegram")])


if __name__ == "__main__":
    unittest.main()

import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _listing_rec(**overrides):
    rec = {
        "raw_id": None,
        "source": "guland",
        "source_id": "1123539",
        "url": "https://guland.vn/post/dat-chinh-chu-1134m2-truc-duong-dx84-tdm-binh-duong-1123539",
        "title": "Dat chinh chu 113,4m2, truc duong DX84, TDM, Binh Duong",
        "description": "Dat chinh chu 113,4m2, truc duong DX84",
        "area": "Phu Loi",
        "ward": "Phu Loi",
        "raw_area_text": "113,4m2",
        "price_ty": 1.74,
        "price_per_m2": 15.4,
        "area_m2": 113.0,
        "property_type": "dat_nen",
        "tx_type": "ban",
        "frontage_m": None,
        "depth_m": None,
        "road_width_m": None,
        "road_type": "duong_nhua",
        "road_tier": 2,
        "has_so": True,
        "is_hot": False,
        "contact_phone": None,
        "seller_name": None,
        "post_date": "2026-05-06",
    }
    rec.update(overrides)
    return rec


class PriceHistoryTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_test.db"
        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://price-history-{self.token}.test"
        self.source_id = f"price-history-{self.token}"
        self.admin_identifier = f"price-history-admin-{self.token}@example.test"
        self.admin_token = f"price-history-admin-token-{self.token}"
        self.listing_ids = []
        connection.close_all()
        self.db_path_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_path_patch.start()
        init_schema()
        self._delete_test_rows()

    def tearDown(self):
        from db import connection

        self._delete_test_rows()
        connection.close_all()
        self.db_path_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _delete_test_rows(self):
        from db.connection import get_conn

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id FROM listings WHERE url LIKE ?",
                (f"{self.url_prefix}%",),
            ).fetchall()
            ids = {r["id"] for r in rows}
            ids.update(self.listing_ids)
            if not ids:
                return
            placeholders = ",".join("?" * len(ids))
            params = list(ids)
            conn.execute(f"DELETE FROM price_history WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM valuation_results WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM legal_verifications WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", params)
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (self.admin_token,))
            conn.execute("DELETE FROM users WHERE identifier = ?", (self.admin_identifier,))

    def _rec(self, **overrides):
        data = {
            "source_id": self.source_id,
            "url": f"{self.url_prefix}/listing",
        }
        data.update(overrides)
        return _listing_rec(**data)

    def _track(self, listing_id):
        self.listing_ids.append(listing_id)
        return listing_id

    def _login_as_admin(self, client):
        from auth.core import SESSION_COOKIE_NAME
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier)
                VALUES (?, 'email', 'hash', 'admin')
                """,
                (self.admin_identifier,),
            )
            conn.execute(
                """
                INSERT INTO user_sessions (token, user_id, expires_at)
                VALUES (?, ?, '2099-01-01T00:00:00')
                """,
                (self.admin_token, cur.lastrowid),
            )
        try:
            client.set_cookie(SESSION_COOKIE_NAME, self.admin_token)
        except TypeError:
            client.set_cookie("localhost", SESSION_COOKIE_NAME, self.admin_token)

    def _history_rows(self, listing_id):
        from db.connection import get_conn

        with get_conn() as conn:
            return conn.execute("""
                SELECT price_ty, price_per_m2, crawl_run_id
                FROM price_history
                WHERE listing_id = ?
                ORDER BY recorded_at ASC, id ASC
            """, (listing_id,)).fetchall()

    def test_upsert_listing_same_price_does_not_duplicate_history(self):
        from db.listings import upsert_listing

        listing_id, is_new = upsert_listing(self._rec(), crawl_run_id=1)
        self._track(listing_id)
        self.assertTrue(is_new)

        same_listing_id, is_new = upsert_listing(self._rec(), crawl_run_id=2)
        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)

        rows = self._history_rows(listing_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price_ty"], 1.74)
        self.assertEqual(rows[0]["crawl_run_id"], 1)

    def test_upsert_listing_changed_price_adds_one_history_snapshot(self):
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(self._rec(), crawl_run_id=1)
        self._track(listing_id)
        upsert_listing(self._rec(price_ty=1.70, price_per_m2=15.04), crawl_run_id=2)
        upsert_listing(self._rec(price_ty=1.70, price_per_m2=15.04), crawl_run_id=3)

        rows = self._history_rows(listing_id)
        self.assertEqual([r["price_ty"] for r in rows], [1.74, 1.70])
        self.assertEqual([r["crawl_run_id"] for r in rows], [1, 2])

    def test_upsert_listing_missing_price_or_area_preserves_last_known_values(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(self._rec(), crawl_run_id=1)
        self._track(listing_id)

        same_listing_id, is_new = upsert_listing(
            self._rec(price_ty=None, price_per_m2=None, area_m2=None),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT price_ty, price_per_m2, area_m2 FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["price_ty"], 1.74)
        self.assertEqual(row["price_per_m2"], 15.4)
        self.assertEqual(row["area_m2"], 113.0)

    def test_upsert_listing_full_reprocess_clears_stale_missing_measurements(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(
            self._rec(price_ty=3.8, price_per_m2=11.912, area_m2=319.0, tho_cu_m2=5.0),
            crawl_run_id=1,
        )
        self._track(listing_id)

        same_listing_id, is_new = upsert_listing(
            self._rec(
                price_ty=3.8,
                price_per_m2=None,
                area_m2=None,
                frontage_m=None,
                depth_m=None,
                tho_cu_m2=None,
                tho_cu_ratio=None,
                _clear_stale_measurements=True,
            ),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT price_ty, price_per_m2, area_m2, frontage_m, depth_m, tho_cu_m2 FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["price_ty"], 3.8)
        self.assertIsNone(row["price_per_m2"])
        self.assertIsNone(row["area_m2"])
        self.assertIsNone(row["frontage_m"])
        self.assertIsNone(row["depth_m"])
        self.assertIsNone(row["tho_cu_m2"])

    def test_upsert_listing_clear_stale_measurements_can_clear_stale_price(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(
            self._rec(price_ty=3.0, price_per_m2=20.0, area_m2=150.0),
            crawl_run_id=1,
        )
        self._track(listing_id)

        same_listing_id, is_new = upsert_listing(
            self._rec(
                price_ty=None,
                price_per_m2=None,
                area_m2=150.0,
                _clear_stale_measurements=True,
            ),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT price_ty, price_per_m2, price_first_ty,
                       price_dropped, price_drop_pct, suspicious_bait, area_m2
                FROM listings
                WHERE id=?
                """,
                (listing_id,),
            ).fetchone()

        self.assertIsNone(row["price_ty"])
        self.assertIsNone(row["price_per_m2"])
        self.assertIsNone(row["price_first_ty"])
        self.assertEqual(row["price_dropped"], 0)
        self.assertIsNone(row["price_drop_pct"])
        self.assertEqual(row["suspicious_bait"], 0)
        self.assertEqual(row["area_m2"], 150.0)

    def test_upsert_listing_existing_row_enriches_dimensions_from_new_parse(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(self._rec(), crawl_run_id=1)
        self._track(listing_id)

        same_listing_id, is_new = upsert_listing(
            self._rec(frontage_m=4.0, depth_m=28.0),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT frontage_m, depth_m FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["frontage_m"], 4.0)
        self.assertEqual(row["depth_m"], 28.0)

    def test_upsert_listing_derives_area_and_ppm2_from_dimensions(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, is_new = upsert_listing(
            self._rec(area_m2=None, price_per_m2=None, frontage_m=7.5, depth_m=29.0),
            crawl_run_id=1,
        )
        self._track(listing_id)

        self.assertTrue(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT area_m2, price_per_m2, frontage_m, depth_m FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["area_m2"], 217.5)
        self.assertAlmostEqual(row["price_per_m2"], 8.0, places=3)
        self.assertEqual(row["frontage_m"], 7.5)
        self.assertEqual(row["depth_m"], 29.0)

    def test_upsert_listing_derives_depth_from_area_and_frontage(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, is_new = upsert_listing(
            self._rec(area_m2=215.0, price_per_m2=None, frontage_m=9.0, depth_m=None),
            crawl_run_id=1,
        )
        self._track(listing_id)

        self.assertTrue(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT area_m2, price_per_m2, frontage_m, depth_m FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["area_m2"], 215.0)
        self.assertAlmostEqual(row["price_per_m2"], 8.093, places=3)
        self.assertEqual(row["frontage_m"], 9.0)
        self.assertEqual(row["depth_m"], 23.9)

    def test_upsert_listing_recalculates_ppm2_when_dimensions_correct_area(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(
            self._rec(price_ty=1.8, area_m2=90.0, price_per_m2=20.0),
            crawl_run_id=1,
        )
        self._track(listing_id)

        same_listing_id, is_new = upsert_listing(
            self._rec(price_ty=1.8, area_m2=None, price_per_m2=None, frontage_m=9.5, depth_m=29.0),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT area_m2, price_per_m2, frontage_m, depth_m FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["area_m2"], 275.5)
        self.assertAlmostEqual(row["price_per_m2"], 6.534, places=3)
        self.assertEqual(row["frontage_m"], 9.5)
        self.assertEqual(row["depth_m"], 29.0)

    def test_upsert_listing_allows_explicit_small_road_parse_to_override_llm_tier(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(
            self._rec(road_type="hem_ba_gac", road_tier=3),
            crawl_run_id=1,
        )
        self._track(listing_id)
        with get_conn() as conn:
            conn.execute(
                "UPDATE listings SET llm_verified=1, road_tier=3 WHERE id=?",
                (listing_id,),
            )

        same_listing_id, is_new = upsert_listing(
            self._rec(road_type="hem_ba_gac", road_tier=4),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT road_type, road_tier FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["road_type"], "hem_ba_gac")
        self.assertEqual(row["road_tier"], 4)

    def test_upsert_listing_allows_explicit_car_alley_parse_to_downgrade_llm_main_road(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(
            self._rec(road_type="duong_nhua", road_tier=2),
            crawl_run_id=1,
        )
        self._track(listing_id)
        with get_conn() as conn:
            conn.execute(
                "UPDATE listings SET llm_verified=1, road_type='duong_nhua', road_tier=2 WHERE id=?",
                (listing_id,),
            )

        same_listing_id, is_new = upsert_listing(
            self._rec(road_type="hem_xe_hoi", road_tier=3),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT road_type, road_tier FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["road_type"], "hem_xe_hoi")
        self.assertEqual(row["road_tier"], 3)

    def test_upsert_listing_uses_parser_road_tier_over_stale_llm_main_road(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(
            self._rec(road_type="mat_tien_kinh_doanh", road_tier=1),
            crawl_run_id=1,
        )
        self._track(listing_id)
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                SET llm_verified=1, road_type='mat_tien_kinh_doanh', road_tier=1
                WHERE id=?
                """,
                (listing_id,),
            )

        same_listing_id, is_new = upsert_listing(
            self._rec(road_type="mat_tien_kinh_doanh", road_tier=2),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT road_type, road_tier FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["road_type"], "mat_tien_kinh_doanh")
        self.assertEqual(row["road_tier"], 2)

    def test_upsert_listing_clears_llm_road_tier_when_parser_has_no_road_evidence(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(
            self._rec(road_type="be_tong", road_tier=3),
            crawl_run_id=1,
        )
        self._track(listing_id)
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                SET llm_verified=1, road_type='be_tong', road_tier=3,
                    llm_notes='{"road_tier": 3, "road_type": "be_tong"}'
                WHERE id=?
                """,
                (listing_id,),
            )

        same_listing_id, is_new = upsert_listing(
            self._rec(road_type="unknown", road_tier=0),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT road_type, road_tier FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["road_type"], "unknown")
        self.assertEqual(row["road_tier"], 0)

    def test_upsert_listing_clears_stale_road_tier_when_llm_has_no_road_evidence(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(
            self._rec(road_type="unknown", road_tier=3),
            crawl_run_id=1,
        )
        self._track(listing_id)
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                SET llm_verified=1, road_type='unknown', road_tier=3,
                    llm_notes='{"road_tier": null, "road_type": null}'
                WHERE id=?
                """,
                (listing_id,),
            )

        same_listing_id, is_new = upsert_listing(
            self._rec(road_type="unknown", road_tier=0),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT road_type, road_tier FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["road_type"], "unknown")
        self.assertEqual(row["road_tier"], 0)

    def test_upsert_listing_applies_explicit_llm_extraction_override(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(
            self._rec(
                price_ty=1.0,
                area_m2=100.0,
                price_per_m2=10.0,
                ward="Phu Hoa",
                property_type="nha_dat",
                road_name="QL13",
                road_type="duong_nhua",
                road_tier=2,
                tho_cu_m2=100.0,
                tho_cu_ratio=1.0,
            ),
            crawl_run_id=1,
        )
        self._track(listing_id)
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                SET llm_verified=1,
                    llm_notes='{"extraction_override":{"price_ty":null,"area_m2":120,"ward":"Hoa Loi","property_type":"dat_nen","road_name":"Bui Quoc Khanh","road_type":"hem_xe_hoi","road_tier":3,"tho_cu_m2":60}}'
                WHERE id=?
                """,
                (listing_id,),
            )

        same_listing_id, is_new = upsert_listing(
            self._rec(
                price_ty=1.0,
                area_m2=100.0,
                price_per_m2=10.0,
                ward="Phu Hoa",
                property_type="nha_dat",
                road_name="QL13",
                road_type="duong_nhua",
                road_tier=2,
                tho_cu_m2=100.0,
                tho_cu_ratio=1.0,
            ),
            crawl_run_id=2,
        )

        self.assertEqual(same_listing_id, listing_id)
        self.assertFalse(is_new)
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT price_ty, price_per_m2, area_m2, ward, property_type,
                       road_name, road_type, road_tier, tho_cu_m2, tho_cu_ratio
                FROM listings
                WHERE id=?
                """,
                (listing_id,),
            ).fetchone()

        self.assertIsNone(row["price_ty"])
        self.assertIsNone(row["price_per_m2"])
        self.assertEqual(row["area_m2"], 120.0)
        self.assertEqual(row["ward"], "Hoa Loi")
        self.assertEqual(row["property_type"], "dat_nen")
        self.assertEqual(row["road_name"], "Bui Quoc Khanh")
        self.assertEqual(row["road_type"], "hem_xe_hoi")
        self.assertEqual(row["road_tier"], 3)
        self.assertEqual(row["tho_cu_m2"], 60.0)
        self.assertEqual(row["tho_cu_ratio"], 0.5)

    def test_upsert_listing_recomputes_ppm2_from_llm_price_and_area_override(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(
            self._rec(price_ty=2.0, area_m2=100.0, price_per_m2=20.0),
            crawl_run_id=1,
        )
        self._track(listing_id)
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                SET llm_verified=1,
                    llm_notes='{"extraction_override":{"price_ty":3.6,"area_m2":120}}'
                WHERE id=?
                """,
                (listing_id,),
            )

        upsert_listing(self._rec(price_ty=2.0, area_m2=100.0, price_per_m2=20.0), crawl_run_id=2)

        with get_conn() as conn:
            row = conn.execute(
                "SELECT price_ty, area_m2, price_per_m2 FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(row["price_ty"], 3.6)
        self.assertEqual(row["area_m2"], 120.0)
        self.assertEqual(row["price_per_m2"], 30.0)

    def test_save_llm_extraction_override_marks_listing_for_next_reprocess(self):
        import json
        from db.connection import get_conn
        from db.listings import save_llm_extraction_override, upsert_listing

        listing_id, _ = upsert_listing(
            self._rec(price_ty=2.0, area_m2=100.0, price_per_m2=20.0, ward="Phu Hoa"),
            crawl_run_id=1,
        )
        self._track(listing_id)
        with get_conn() as conn:
            conn.execute(
                "UPDATE listings SET llm_notes=? WHERE id=?",
                ('{"memo":"keep this"}', listing_id),
            )

        save_llm_extraction_override(
            listing_id,
            {"price_ty": 3.6, "area_m2": 120, "ward": "Hoa Loi", "ignored": "x"},
            actor="codex",
            model="manual-llm",
            note="manual parsed facts",
        )

        with get_conn() as conn:
            row = conn.execute(
                "SELECT llm_verified, llm_notes FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()
        notes = json.loads(row["llm_notes"])

        self.assertEqual(row["llm_verified"], 1)
        self.assertEqual(notes["memo"], "keep this")
        self.assertEqual(notes["extraction_override"]["actor"], "codex")
        self.assertEqual(notes["extraction_override"]["model"], "manual-llm")
        self.assertEqual(notes["extraction_override"]["fields"], {
            "price_ty": 3.6,
            "area_m2": 120,
            "ward": "Hoa Loi",
        })

        upsert_listing(self._rec(price_ty=2.0, area_m2=100.0, price_per_m2=20.0, ward="Phu Hoa"), crawl_run_id=2)
        with get_conn() as conn:
            applied = conn.execute(
                "SELECT price_ty, area_m2, price_per_m2, ward FROM listings WHERE id=?",
                (listing_id,),
            ).fetchone()

        self.assertEqual(applied["price_ty"], 3.6)
        self.assertEqual(applied["area_m2"], 120.0)
        self.assertEqual(applied["price_per_m2"], 30.0)
        self.assertEqual(applied["ward"], "Hoa Loi")

    def test_upsert_listing_over_40pct_drop_marks_suspicious_bait(self):
        from db.connection import get_conn
        from db.listings import upsert_listing

        listing_id, _ = upsert_listing(self._rec(price_ty=2.0, price_per_m2=20.0), crawl_run_id=1)
        self._track(listing_id)
        upsert_listing(self._rec(price_ty=1.0, price_per_m2=10.0), crawl_run_id=2)

        with get_conn() as conn:
            row = conn.execute("""
                SELECT price_dropped, price_drop_pct, suspicious_bait
                FROM listings
                WHERE id = ?
            """, (listing_id,)).fetchone()

        self.assertEqual(row["price_dropped"], 0)
        self.assertIsNone(row["price_drop_pct"])
        self.assertEqual(row["suspicious_bait"], 1)

    def test_dedup_reconciles_price_first_from_history_before_drop_flag(self):
        from cleansing.dedup import _reconcile_price_first_from_history
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO listings (
                    source, source_id, url, title, ward, area_m2, property_type,
                    price_ty, price_per_m2, price_first_ty, price_dropped,
                    price_drop_pct, suspicious_bait, probably_sold
                ) VALUES (
                    'facebook', ?, ?, 'Same URL dropped but first price was reset',
                    'Tan Dinh', 150, 'dat_nen', 1.0, 6.67, 1.0, 0,
                    NULL, 0, 0
                )
            """, (f"{self.source_id}-history-reconcile", f"{self.url_prefix}/history-reconcile"))
            listing_id = self._track(cur.lastrowid)
            conn.executemany("""
                INSERT INTO price_history (listing_id, price_ty, price_per_m2, recorded_at)
                VALUES (?, ?, ?, ?)
            """, [
                (listing_id, 1.6, 10.67, "2026-05-26 16:38:30"),
                (listing_id, 1.0, 6.67, "2026-05-28 09:39:54"),
            ])

            _reconcile_price_first_from_history(conn)

            row = conn.execute("""
                SELECT price_first_ty, price_dropped, price_drop_pct, suspicious_bait
                FROM listings
                WHERE id=?
            """, (listing_id,)).fetchone()

        self.assertEqual(row["price_first_ty"], 1.6)
        self.assertEqual(row["price_dropped"], 1)
        self.assertAlmostEqual(row["price_drop_pct"], 37.5)
        self.assertEqual(row["suspicious_bait"], 0)

    def test_history_api_compacts_repeated_snapshots_and_current_price(self):
        from app import app
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO listings (
                    source, source_id, url, title, ward, area_m2, property_type,
                    price_ty, price_per_m2, updated_at, probably_sold
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                "guland", f"{self.source_id}-api", f"{self.url_prefix}/dx84",
                "Dat chinh chu 113,4m2, truc duong DX84", "Phu Loi", 113.0,
                "dat_nen", 1.74, 15.4, "2026-05-07T12:25:35",
            ))
            listing_id = self._track(cur.lastrowid)
            conn.executemany("""
                INSERT INTO price_history (listing_id, price_ty, price_per_m2, recorded_at)
                VALUES (?, ?, ?, ?)
            """, [
                (listing_id, 1.74, 15.4, "2026-05-06 22:58:26"),
                (listing_id, 1.74, 15.4, "2026-05-07 01:25:13"),
                (listing_id, 1.74, 15.4, "2026-05-07 05:25:35"),
            ])

        response = app.test_client().get(f"/api/history/{listing_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["history"], [{"date": "2026-05-06", "price_ty": 1.74}])

        admin_client = app.test_client()
        self._login_as_admin(admin_client)
        admin_response = admin_client.get(f"/api/history/{listing_id}")
        self.assertEqual(admin_response.status_code, 200)
        admin_history = admin_response.get_json()["history"]
        self.assertEqual(admin_history[0]["url"], f"{self.url_prefix}/dx84")

    def test_history_api_keeps_only_final_same_day_parser_snapshot(self):
        from app import app
        from db.connection import get_conn

        with get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO listings (
                    source, source_id, url, title, ward, area_m2, property_type,
                    price_ty, price_per_m2, posted_at, updated_at, probably_sold
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                "facebook", f"{self.source_id}-same-day-fix",
                f"{self.url_prefix}/same-day-fix",
                "Bán nhà Hiệp An 5x25 giá 2ty350",
                "Hiệp An", 125.0, "nha_dat", 2.35, 18.8,
                "2026-04-02", "2026-04-24T20:19:09",
            ))
            listing_id = self._track(cur.lastrowid)
            conn.executemany("""
                INSERT INTO price_history (
                    listing_id, price_ty, price_per_m2, recorded_at, crawl_run_id
                ) VALUES (?, ?, ?, ?, ?)
            """, [
                (listing_id, 2.0, 16.0, "2026-04-24 20:17:40", 5),
                (listing_id, 2.35, 18.8, "2026-04-24 20:19:09", 6),
            ])

        response = app.test_client().get(f"/api/history/{listing_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["history"],
            [{"date": "2026-04-02", "price_ty": 2.35}],
        )


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class LotHistoryApiTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://lot-history-{self.token}.test"
        self.listing_ids = []
        connection.close_all()

        init_schema()
        self._delete_test_rows()
        self.client = app_module.app.test_client()
        self._seed()

    def tearDown(self):
        from db import connection

        self._delete_test_rows()
        connection.close_all()

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

    def _insert_listing(self, conn, **kw):
        defaults = {
            "source": "facebook",
            "source_id": f"src-{self.token}",
            "url": f"{self.url_prefix}/src",
            "title": "Listing",
            "ward": f"LotWard{self.token[:8]}",
            "area_m2": 100,
            "property_type": "dat_nen",
            "price_ty": 2.0,
            "price_per_m2": 20,
            "price_first_ty": 2.0,
            "price_dropped": 0,
            "price_drop_pct": None,
            "probably_sold": 0,
            "possibly_duplicate": 0,
            "duplicate_of_id": None,
            "description": "Listing",
            "frontage_m": None,
            "depth_m": None,
            "contact_phone": None,
            "posted_at": "2026-05-01",
        }
        defaults.update(kw)
        cur = conn.execute("""
            INSERT INTO listings (
                source, source_id, url, title, ward, area_m2, property_type,
                price_ty, price_per_m2, price_first_ty, price_dropped,
                price_drop_pct, probably_sold, possibly_duplicate, duplicate_of_id,
                description, frontage_m, depth_m, contact_phone, posted_at
            ) VALUES (
                :source, :source_id, :url, :title, :ward, :area_m2, :property_type,
                :price_ty, :price_per_m2, :price_first_ty, :price_dropped,
                :price_drop_pct, :probably_sold, :possibly_duplicate, :duplicate_of_id,
                :description, :frontage_m, :depth_m, :contact_phone, :posted_at
            )
        """, defaults)
        listing_id = cur.lastrowid
        self.listing_ids.append(listing_id)
        return listing_id

    def _seed(self):
        from db.connection import get_conn

        with get_conn() as conn:
            self.canonical_id = self._insert_listing(
                conn,
                source_id=f"fb-old-{self.token}",
                url=f"{self.url_prefix}/fb-old",
                title="Facebook canonical",
                posted_at="2026-05-01",
            )
            self.facebook_same_price_id = self._insert_listing(
                conn,
                source_id=f"fb-same-{self.token}",
                url=f"{self.url_prefix}/fb-same",
                title="Facebook same price repost",
                price_ty=2.0,
                possibly_duplicate=1,
                duplicate_of_id=self.canonical_id,
                posted_at="2026-05-03",
            )
            self.guland_same_price_id = self._insert_listing(
                conn,
                source="guland",
                source_id=f"gl-same-{self.token}",
                url=f"{self.url_prefix}/gl-same",
                title="Guland same price repost",
                price_ty=2.0,
                possibly_duplicate=1,
                duplicate_of_id=self.canonical_id,
                posted_at="2026-05-04",
            )
            self.guland_drop_id = self._insert_listing(
                conn,
                source="guland",
                source_id=f"gl-drop-{self.token}",
                url=f"{self.url_prefix}/gl-drop",
                title="Guland lower repost",
                price_ty=1.9,
                price_first_ty=2.0,
                price_dropped=1,
                price_drop_pct=5.0,
                possibly_duplicate=1,
                duplicate_of_id=self.canonical_id,
                posted_at="2026-05-05",
            )

    def test_lot_history_includes_facebook_same_price_and_non_facebook_drop_only(self):
        response = self.client.get(f"/api/history/{self.canonical_id}")
        self.assertEqual(response.status_code, 200)
        lot_history = response.get_json()["lot_history"]
        ids = [row["id"] for row in lot_history]

        self.assertIn(self.canonical_id, ids)
        self.assertIn(self.facebook_same_price_id, ids)
        self.assertIn(self.guland_drop_id, ids)
        self.assertNotIn(self.guland_same_price_id, ids)

    def test_price_history_uses_post_date_for_merged_duplicate_snapshot(self):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute("""
                INSERT INTO price_history (listing_id, price_ty, price_per_m2, recorded_at)
                VALUES (?, ?, ?, ?)
            """, (self.canonical_id, 2.0, 20.0, "2026-06-01 08:00:00"))
            conn.execute("""
                INSERT INTO price_history (listing_id, price_ty, price_per_m2, recorded_at)
                VALUES (?, ?, ?, ?)
            """, (self.facebook_same_price_id, 1.95, 19.5, "2026-06-03 08:00:00"))

        response = self.client.get(f"/api/history/{self.canonical_id}")
        self.assertEqual(response.status_code, 200)

        history = response.get_json()["history"]
        self.assertIn(
            {"date": "2026-05-01", "price_ty": 2.0},
            [{"date": row["date"], "price_ty": row["price_ty"]} for row in history],
        )
        self.assertIn(
            {"date": "2026-05-03", "price_ty": 1.95},
            [{"date": row["date"], "price_ty": row["price_ty"]} for row in history],
        )

    def test_lot_history_filters_conflicting_road_code_child(self):
        from db.connection import get_conn

        with get_conn() as conn:
            dx013_id = self._insert_listing(
                conn,
                source_id=f"fb-dx013-{self.token}",
                url=f"{self.url_prefix}/fb-dx013",
                title="DX013 Phu My",
                ward="Phu My",
                area_m2=150,
                frontage_m=5,
                depth_m=30,
                price_ty=3.9,
                price_per_m2=26,
                description=(
                    "Can ban lo dat mat tien Dx 013 duong nhua 8m thong, "
                    "cach cho Phu My 300m. Dien tich 5x30 tho cu 60m."
                ),
                posted_at="2026-06-02",
            )
            dx20_id = self._insert_listing(
                conn,
                source_id=f"fb-dx20-{self.token}",
                url=f"{self.url_prefix}/fb-dx20",
                title="DX20 Phu My",
                ward="Phu My",
                area_m2=150,
                frontage_m=5,
                depth_m=30,
                price_ty=3.3,
                price_per_m2=22,
                description=(
                    "Giap chu Dx20 Phu My duong nhua thong suot oto ne nhau, "
                    "sat ben cho Phu My. Dien tich 5x30, tho cu 60m, gia 3ty3."
                ),
                possibly_duplicate=1,
                duplicate_of_id=dx013_id,
                posted_at="2026-01-01",
            )

        response = self.client.get(f"/api/history/{dx013_id}")
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.get_json()["lot_history"]]

        self.assertIn(dx013_id, ids)
        self.assertNotIn(dx20_id, ids)

    def test_lot_history_filters_same_road_different_area_when_price_is_different(self):
        from db.connection import get_conn

        with get_conn() as conn:
            large_lot_id = self._insert_listing(
                conn,
                source_id=f"fb-dx90-large-{self.token}",
                url=f"{self.url_prefix}/fb-dx90-large",
                title="DX90 large lot",
                ward="Hiệp An",
                area_m2=461.5,
                frontage_m=10,
                depth_m=46,
                price_ty=5.5,
                price_per_m2=11.92,
                description=(
                    "Đất mặt tiền DX090 Hiệp An gần chợ Bưng Cầu. "
                    "Diện tích 10 x 46 = 461,5m2, thổ cư 120m2."
                ),
                posted_at="2026-06-03",
            )
            small_lot_id = self._insert_listing(
                conn,
                source_id=f"fb-dx90-small-{self.token}",
                url=f"{self.url_prefix}/fb-dx90-small",
                title="DX90 small lot",
                ward="Hiệp An",
                area_m2=125.0,
                frontage_m=5,
                depth_m=25,
                price_ty=2.4,
                price_per_m2=19.2,
                description=(
                    "Đất mặt tiền DX90 Hiệp An, 1 xẹt Phan Đăng Lưu. "
                    "Diện tích 5 x 25m, thổ cư 60m2."
                ),
                possibly_duplicate=1,
                duplicate_of_id=large_lot_id,
                posted_at="2026-04-09",
            )

        response = self.client.get(f"/api/history/{large_lot_id}")
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.get_json()["lot_history"]]

        self.assertIn(large_lot_id, ids)
        self.assertNotIn(small_lot_id, ids)

    def test_lot_history_includes_linked_higher_price_drop_when_land_subtype_changes(self):
        from db.connection import get_conn

        with get_conn() as conn:
            current_id = self._insert_listing(
                conn,
                source_id=f"fb-1212-current-{self.token}",
                url=f"{self.url_prefix}/fb-1212-current",
                title="Tan An garden lot current",
                ward="Tan An",
                area_m2=1212.0,
                property_type="dat_nen",
                price_ty=2.9,
                price_per_m2=2.39,
                price_first_ty=3.5,
                price_dropped=1,
                price_drop_pct=17.14,
                description=(
                    "Ban dat phuong Tan An lam vuon gia tot duong ba gac. "
                    "Dt 1.212 m2, tc 140, gia 2ty9."
                ),
                posted_at="2025-07-22",
            )
            old_id = self._insert_listing(
                conn,
                source_id=f"fb-1212-old-{self.token}",
                url=f"{self.url_prefix}/fb-1212-old",
                title="Tan An 1212 old asking price",
                ward="Tan An",
                area_m2=1212.5,
                property_type="dat_nen",
                price_ty=3.5,
                price_per_m2=2.89,
                price_first_ty=3.5,
                possibly_duplicate=1,
                duplicate_of_id=current_id,
                description=(
                    "Sau cho Ben The nhanh Dx126 cach Huynh Thi Hieu 200m. "
                    "Dt 1212,5m2, tho cu 140m2, gia 3ty500."
                ),
                posted_at="2024-09-07",
            )

        response = self.client.get(f"/api/history/{current_id}")
        self.assertEqual(response.status_code, 200)
        lot_history = response.get_json()["lot_history"]
        ids = [row["id"] for row in lot_history]

        self.assertIn(old_id, ids)
        self.assertIn(current_id, ids)

    def test_lot_history_includes_linked_higher_price_drop_when_house_subtype_changes(self):
        from db.connection import get_conn

        with get_conn() as conn:
            current_id = self._insert_listing(
                conn,
                source_id=f"fb-house-current-{self.token}",
                url=f"{self.url_prefix}/fb-house-current",
                title="Dinh Hoa house current",
                ward="Dinh Hoa",
                area_m2=114.0,
                frontage_m=9.0,
                depth_m=12.6,
                property_type="nha_dat",
                price_ty=1.5,
                price_per_m2=13.23,
                price_first_ty=1.58,
                price_dropped=1,
                price_drop_pct=5.06,
                description=(
                    "Ban nha cap 4 Dinh Hoa 9m x 12,6m tho cu 60m2, "
                    "2 phong ngu, bep va phong tro cho thue. Gia ha con 1ty500."
                ),
                posted_at="2026-04-10",
            )
            old_id = self._insert_listing(
                conn,
                source_id=f"fb-house-old-{self.token}",
                url=f"{self.url_prefix}/fb-house-old",
                title="Dinh Hoa house old asking price",
                ward="Dinh Hoa",
                area_m2=113.4,
                frontage_m=9.0,
                depth_m=12.6,
                property_type="nha_tro",
                price_ty=1.58,
                price_per_m2=13.93,
                price_first_ty=1.58,
                possibly_duplicate=1,
                duplicate_of_id=current_id,
                description=(
                    "Can tien ban gap nha cap 4 Dinh Hoa 9m x 12,6m, "
                    "2 phong ngu va 2 phong tro cho thue. Gia 1ty580."
                ),
                posted_at="2026-03-18",
            )

        response = self.client.get(f"/api/history/{current_id}")
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.get_json()["lot_history"]]

        self.assertIn(old_id, ids)
        self.assertIn(current_id, ids)


if __name__ == "__main__":
    unittest.main()

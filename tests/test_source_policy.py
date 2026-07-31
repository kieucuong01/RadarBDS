import sys
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class SourcePolicyTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://source-policy-{self.token}.test"
        self.ward = f"SourceWard{self.token[:8]}"
        self.admin_identifier = f"source-admin-{self.token}@example.test"
        self.admin_token = f"source-admin-token-{self.token}"
        self.listing_ids = []

        connection.close_all()
        init_schema()
        self._delete_test_rows()
        self.client = app_module.app.test_client()
        self.facebook_id = self._seed_signal(
            source="facebook",
            title="Facebook source policy signal",
            source_id="fb",
        )
        self.guland_id = self._seed_signal(
            source="guland",
            title="Guland source policy signal",
            source_id="guland",
        )

    def tearDown(self):
        from db import connection

        self._delete_test_rows()
        connection.close_all()

    def _delete_test_rows(self):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (self.admin_token,))
            conn.execute("DELETE FROM users WHERE identifier = ?", (self.admin_identifier,))

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
            try:
                conn.execute(f"DELETE FROM valuation_shadow_results WHERE listing_id IN ({placeholders})", params)
            except Exception:
                pass
            conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM legal_verifications WHERE listing_id IN ({placeholders})", params)
            conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", params)

    def _seed_signal(
        self,
        *,
        source,
        title,
        source_id,
        description=None,
        ward=None,
        area_m2=100,
        price_ty=2.0,
        price_first_ty=None,
        price_dropped=0,
        price_drop_pct=None,
        image_count=0,
        frontage_m=None,
        depth_m=None,
        posted_at=None,
    ):
        from db.connection import get_conn
        price_per_m2 = round(price_ty * 1000 / area_m2, 2) if price_ty and area_m2 else None
        fair_ppm2 = round(price_per_m2 / (1 - 0.333), 2) if price_per_m2 else None
        posted_at = posted_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description, ward,
                    area_m2, frontage_m, depth_m, property_type, price_ty, price_per_m2,
                    price_first_ty, is_hot, price_dropped, price_drop_pct, suspicious_bait,
                    probably_sold, possibly_duplicate, posted_at, crawled_at
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, 'dat_nen', ?, ?,
                    ?, 0, ?, ?, 0, 0, 0, ?, ?
                )
                """,
                (
                    source,
                    f"{source_id}-{self.token}",
                    f"{self.url_prefix}/{source_id}",
                    title,
                    description or "Source policy listing",
                    ward if ward is not None else self.ward,
                    area_m2,
                    frontage_m,
                    depth_m,
                    price_ty,
                    price_per_m2,
                    price_first_ty if price_first_ty is not None else price_ty,
                    price_dropped,
                    price_drop_pct,
                    posted_at,
                    posted_at,
                ),
            )
            listing_id = cur.lastrowid
            self.listing_ids.append(listing_id)
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score
                ) VALUES (?, ?, ?, 33.3, 1, 70)
                """,
                (listing_id, fair_ppm2, price_per_m2),
            )
            run_id = conn.execute(
                """
                INSERT INTO valuation_model_runs (model_name, model_version, status)
                VALUES ('median_road_tier', 'median_road_tier_v1', 'complete')
                """
            ).lastrowid
            conn.execute(
                """
                INSERT INTO valuation_shadow_results (
                    model_run_id, listing_id, fair_ppm2, actual_ppm2, mos_pct,
                    is_signal, signal_score, source_quality_flags
                ) VALUES (?, ?, ?, ?, 33.3, 1, 70, '')
                """,
                (run_id, listing_id, fair_ppm2, price_per_m2),
            )
            for idx in range(image_count):
                conn.execute(
                    """
                    INSERT INTO listing_images (listing_id, img_url, img_order, local_path)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        listing_id,
                        f"https://images.test/{source_id}-{idx}.jpg",
                        idx,
                        f"data/images/{source_id}-{idx}.jpg",
                    ),
                )
            return listing_id

    def _login_as_admin(self):
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
            self.client.set_cookie(SESSION_COOKIE_NAME, self.admin_token)
        except TypeError:
            self.client.set_cookie("localhost", SESSION_COOKIE_NAME, self.admin_token)

    def test_guest_source_query_is_forced_to_facebook(self):
        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&source=guland&limit=10"
        )
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([s["source"] for s in payload["signals"]], ["facebook"])
        self.assertEqual(payload["signals"][0]["title"], "Facebook source policy signal")

    def test_guest_dashboard_defaults_to_facebook_only(self):
        response = self.client.get(f"/api/dashboard?city=Khac&ward={self.ward}")
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["active_sources"], ["facebook"])
        self.assertEqual(payload["all_sources"], ["facebook"])
        self.assertEqual(payload["stats"]["total"], 1)
        self.assertEqual(payload["stats"]["signals"], 1)

    def test_admin_can_select_guland_source(self):
        self._login_as_admin()

        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&source=guland&limit=10"
        )
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([s["source"] for s in payload["signals"]], ["guland"])
        self.assertEqual(payload["signals"][0]["title"], "Guland source policy signal")

    def test_guland_dashboard_signal_count_matches_actionable_feed(self):
        from db.connection import get_conn

        blocked_id = self._seed_signal(
            source="guland",
            title="Guland hard-blocked signal",
            source_id="guland-hard-blocked",
        )
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE valuation_results
                SET source_quality_recheck=1,
                    source_quality_flags='ambiguous_price_text'
                WHERE listing_id=?
                """,
                (blocked_id,),
            )

        self._login_as_admin()
        query = f"city=Khac&ward={self.ward}&source=guland&date_range=all&mos_min=10"
        feed = self.client.get(f"/api/signals?{query}&limit=20")
        dashboard = self.client.get(f"/api/dashboard?{query}")

        self.assertEqual(feed.status_code, 200)
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(feed.get_json()["total"], 1)
        self.assertEqual(
            dashboard.get_json()["stats"]["signals"],
            feed.get_json()["total"],
        )

    def test_guland_card_uses_first_seen_until_price_changes(self):
        from db.connection import get_conn

        first_seen = (datetime.now() - timedelta(days=12)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                SET first_seen_at=?, price_updated_at=NULL
                WHERE id=?
                """,
                (first_seen, self.guland_id),
            )

        self._login_as_admin()
        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}"
            "&source=guland&date_range=all&limit=10"
        )
        self.assertEqual(response.status_code, 200)

        row = response.get_json()["signals"][0]
        self.assertEqual(row["days_ago"], 12)
        self.assertEqual(row["card_date_reason"], "first_seen")

    def test_guland_card_uses_price_update_as_latest_activity(self):
        from db.connection import get_conn

        first_seen = (datetime.now() - timedelta(days=12)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        price_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                SET first_seen_at=?, price_updated_at=?
                WHERE id=?
                """,
                (first_seen, price_updated, self.guland_id),
            )

        self._login_as_admin()
        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}"
            "&source=guland&date_range=all&limit=10"
        )
        self.assertEqual(response.status_code, 200)

        row = response.get_json()["signals"][0]
        self.assertEqual(row["days_ago"], 0)
        self.assertEqual(row["card_date_reason"], "price_updated")

    def test_facebook_card_keeps_posted_date_semantics(self):
        from db.connection import get_conn

        posted_at = (datetime.now() - timedelta(days=4)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                SET posted_at=?, crawled_at=CURRENT_TIMESTAMP,
                    first_seen_at=CURRENT_TIMESTAMP,
                    price_updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (posted_at, self.facebook_id),
            )

        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&date_range=all&limit=10"
        )
        self.assertEqual(response.status_code, 200)

        row = response.get_json()["signals"][0]
        self.assertEqual(row["days_ago"], 4)
        self.assertEqual(row["card_date_reason"], "posted")

    def test_confirmed_inactive_listing_is_hidden_but_unreachable_stays_visible(self):
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute(
                "UPDATE listings SET source_status='inactive' WHERE id=?",
                (self.facebook_id,),
            )
            conn.execute(
                "UPDATE listings SET source_status='unreachable' WHERE id=?",
                (self.guland_id,),
            )

        guest = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&date_range=all&limit=10"
        ).get_json()
        self.assertEqual(guest["total"], 0)

        self._login_as_admin()
        admin = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}"
            "&source=guland&date_range=all&limit=10"
        ).get_json()
        self.assertEqual(admin["total"], 1)
        self.assertEqual(admin["signals"][0]["id"], self.guland_id)

    def test_admin_default_source_is_facebook(self):
        self._login_as_admin()

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=10")
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([s["source"] for s in payload["signals"]], ["facebook"])

    def test_signal_feed_defaults_to_three_month_listing_window(self):
        old_date = (datetime.now() - timedelta(days=130)).strftime("%Y-%m-%d %H:%M:%S")
        self._seed_signal(
            source="facebook",
            title="Old default hidden signal",
            source_id="fb-old-default-hidden",
            posted_at=old_date,
        )

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=20")
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([s["title"] for s in payload["signals"]], ["Facebook source policy signal"])

    def test_signal_feed_supports_all_time_listing_window(self):
        old_date = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S")
        self._seed_signal(
            source="facebook",
            title="Old all time visible signal",
            source_id="fb-old-all-visible",
            posted_at=old_date,
        )

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&date_range=all&limit=20")
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        titles = [s["title"] for s in payload["signals"]]
        self.assertEqual(payload["total"], 2)
        self.assertIn("Facebook source policy signal", titles)
        self.assertIn("Old all time visible signal", titles)

    def test_all_listings_uses_same_date_range_filter(self):
        old_date = (datetime.now() - timedelta(days=130)).strftime("%Y-%m-%d %H:%M:%S")
        self._seed_signal(
            source="facebook",
            title="Old listings hidden by default",
            source_id="fb-old-listings-hidden",
            posted_at=old_date,
        )

        default_response = self.client.get(f"/api/listings?city=Khac&ward={self.ward}&limit=20")
        self.assertEqual(default_response.status_code, 200)
        default_payload = default_response.get_json()
        self.assertEqual(default_payload["total"], 1)
        self.assertEqual([x["title"] for x in default_payload["listings"]], ["Facebook source policy signal"])

        all_response = self.client.get(f"/api/listings?city=Khac&ward={self.ward}&date_range=all&limit=20")
        self.assertEqual(all_response.status_code, 200)
        all_payload = all_response.get_json()
        titles = [x["title"] for x in all_payload["listings"]]
        self.assertEqual(all_payload["total"], 2)
        self.assertIn("Facebook source policy signal", titles)
        self.assertIn("Old listings hidden by default", titles)

    def test_all_listings_complete_filter_requires_ward_price_and_area(self):
        complete_id = self._seed_signal(
            source="facebook",
            title="Complete info filter match",
            source_id="fb-complete-info-match",
        )
        self._seed_signal(
            source="facebook",
            title="Complete info filter missing ward",
            source_id="fb-complete-info-missing-ward",
            ward="",
        )
        self._seed_signal(
            source="facebook",
            title="Complete info filter missing price",
            source_id="fb-complete-info-missing-price",
            price_ty=None,
        )
        self._seed_signal(
            source="facebook",
            title="Complete info filter missing area",
            source_id="fb-complete-info-missing-area",
            area_m2=None,
        )

        response = self.client.get(
            "/api/listings?city=Khac&q=complete info filter&complete=1&limit=20"
        )
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([row["id"] for row in payload["listings"]], [complete_id])

    def test_all_listings_complete_filter_button_renders(self):
        html = self.client.get("/").get_data(as_text=True)

        self.assertIn('id="completeListingsOnly"', html)
        self.assertIn("Tin đủ thông tin", html)

    def test_signal_feed_accepts_multiple_area_ranges(self):
        self._seed_signal(source="facebook", title="Area 200 signal", source_id="fb-area-200", area_m2=200, price_ty=2.0)
        self._seed_signal(source="facebook", title="Area 600 signal", source_id="fb-area-600", area_m2=600, price_ty=6.0)

        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&area_range=150:500&area_range=500:&limit=20"
        )
        self.assertEqual(response.status_code, 200)

        titles = {row["title"] for row in response.get_json()["signals"]}
        self.assertNotIn("Facebook source policy signal", titles)
        self.assertIn("Area 200 signal", titles)
        self.assertIn("Area 600 signal", titles)

    def test_signal_feed_accepts_multiple_price_ranges(self):
        self._seed_signal(source="facebook", title="Price 0.5 signal", source_id="fb-price-low", area_m2=100, price_ty=0.5)
        self._seed_signal(source="facebook", title="Price 3 signal", source_id="fb-price-mid", area_m2=100, price_ty=3.0)
        self._seed_signal(source="facebook", title="Price 5 signal", source_id="fb-price-high", area_m2=100, price_ty=5.0)

        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&price_range=:1&price_range=5:&limit=20"
        )
        self.assertEqual(response.status_code, 200)

        titles = {row["title"] for row in response.get_json()["signals"]}
        self.assertIn("Price 0.5 signal", titles)
        self.assertIn("Price 5 signal", titles)
        self.assertNotIn("Facebook source policy signal", titles)
        self.assertNotIn("Price 3 signal", titles)

    def test_signal_feed_returns_image_count(self):
        no_image_id = self._seed_signal(
            source="facebook",
            title="No image signal",
            source_id="fb-no-image",
            image_count=0,
        )
        one_image_id = self._seed_signal(
            source="facebook",
            title="One image signal",
            source_id="fb-one-image",
            image_count=1,
        )
        many_image_id = self._seed_signal(
            source="facebook",
            title="Many image signal",
            source_id="fb-many-image",
            image_count=5,
        )

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=20")
        self.assertEqual(response.status_code, 200)

        counts = {row["id"]: row["image_count"] for row in response.get_json()["signals"]}
        self.assertEqual(counts[no_image_id], 0)
        self.assertEqual(counts[one_image_id], 1)
        self.assertEqual(counts[many_image_id], 5)

    def test_signal_feed_returns_lot_dimensions(self):
        listing_id = self._seed_signal(
            source="facebook",
            title="Dimension signal",
            source_id="fb-dimension",
            area_m2=100,
            frontage_m=5,
            depth_m=20,
        )

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&limit=20")
        self.assertEqual(response.status_code, 200)

        rows = {row["id"]: row for row in response.get_json()["signals"]}
        self.assertEqual(rows[listing_id]["frontage_m"], 5)
        self.assertEqual(rows[listing_id]["depth_m"], 20)

    def test_keyword_search_filters_signal_feed_without_accents(self):
        matched_id = self._seed_signal(
            source="facebook",
            title="Đường Nguyễn Chí Thanh giá tốt",
            source_id="fb-nguyen-chi-thanh",
        )
        self._seed_signal(
            source="facebook",
            title="Đường khác không khớp",
            source_id="fb-other-road",
        )

        response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&q=nguyen chi thanh&limit=20"
        )
        self.assertEqual(response.status_code, 200)

        rows = response.get_json()["signals"]
        self.assertEqual([row["id"] for row in rows], [matched_id])

    def test_stale_price_drop_flag_without_total_price_drop_is_suppressed(self):
        stale_id = self._seed_signal(
            source="facebook",
            title="Stale drop flag Nguyen Chi Thanh",
            source_id="fb-stale-drop-flag",
            area_m2=146,
            price_ty=1.59,
            price_first_ty=1.59,
            price_dropped=1,
            price_drop_pct=1.38,
        )

        signal_response = self.client.get(
            f"/api/signals?city=Khac&ward={self.ward}&q=stale drop flag&limit=20"
        )
        self.assertEqual(signal_response.status_code, 200)
        signal_rows = signal_response.get_json()["signals"]
        self.assertEqual([row["id"] for row in signal_rows], [stale_id])
        self.assertFalse(signal_rows[0]["price_dropped"])
        self.assertIsNone(signal_rows[0]["drop_pct"])

        listing_response = self.client.get(
            f"/api/listings?city=Khac&ward={self.ward}&q=stale drop flag&limit=20"
        )
        self.assertEqual(listing_response.status_code, 200)
        listing_rows = listing_response.get_json()["listings"]
        self.assertEqual([row["id"] for row in listing_rows], [stale_id])
        self.assertFalse(listing_rows[0]["price_dropped"])
        self.assertIsNone(listing_rows[0]["drop_pct"])

    def test_exact_search_matches_compact_query_to_spaced_road_code(self):
        matched_id = self._seed_signal(
            source="facebook",
            title="Lo goc mat tien duong lon",
            description="Can ban nen gan duong DX 44 khu dan cu hien huu",
            source_id="fb-dx44-spaced",
        )
        self._seed_signal(
            source="facebook",
            title="Lo khac o duong DX 45",
            description="Can ban nen gan duong DX 45",
            source_id="fb-dx45",
        )

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&q=DX44&limit=20")
        self.assertEqual(response.status_code, 200)

        rows = response.get_json()["signals"]
        self.assertEqual([row["id"] for row in rows], [matched_id])

    def test_exact_search_matches_spaced_query_to_compact_road_code(self):
        matched_id = self._seed_signal(
            source="facebook",
            title="Nen gan DH3A My Phuoc",
            description="Lo dep truc DH3A, thich hop dau tu",
            source_id="fb-dh3a-compact",
        )
        self._seed_signal(
            source="facebook",
            title="Nen gan DH3",
            description="Lo dep truc DH3",
            source_id="fb-dh3",
        )

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&q=DH 3A&limit=20")
        self.assertEqual(response.status_code, 200)

        rows = response.get_json()["signals"]
        self.assertEqual([row["id"] for row in rows], [matched_id])

    def test_exact_search_matches_area_code_and_my_phuoc_shorthand(self):
        khu_l_id = self._seed_signal(
            source="facebook",
            title="Nen khu L My Phuoc 3",
            description="Lo khu L gan cong vien",
            ward="My Phuoc 3",
            source_id="fb-khu-l-mp3",
        )
        khu_m_id = self._seed_signal(
            source="facebook",
            title="Nen khu M My Phuoc 2",
            description="Lo khu M gan cho",
            ward="My Phuoc 2",
            source_id="fb-khu-m-mp2",
        )

        khu_response = self.client.get(f"/api/signals?city=Khac&q=khu L&limit=20")
        self.assertEqual(khu_response.status_code, 200)
        khu_ids = {row["id"] for row in khu_response.get_json()["signals"]}
        self.assertIn(khu_l_id, khu_ids)
        self.assertNotIn(khu_m_id, khu_ids)

        mp_response = self.client.get(f"/api/signals?city=Khac&q=MP3&limit=20")
        self.assertEqual(mp_response.status_code, 200)
        mp_ids = {row["id"] for row in mp_response.get_json()["signals"]}
        self.assertIn(khu_l_id, mp_ids)
        self.assertNotIn(khu_m_id, mp_ids)

    def test_generic_road_keyword_does_not_narrow_signal_feed(self):
        first_id = self._seed_signal(
            source="facebook",
            title="Nen gan duong DX 44",
            description="Mat tien duong lon",
            source_id="fb-generic-road-a",
        )
        second_id = self._seed_signal(
            source="facebook",
            title="Nen trong khu dan cu",
            description="Duong noi bo thong thoang",
            source_id="fb-generic-road-b",
        )

        response = self.client.get(f"/api/signals?city=Khac&ward={self.ward}&q=duong&limit=20")
        self.assertEqual(response.status_code, 200)

        ids = {row["id"] for row in response.get_json()["signals"]}
        self.assertTrue({first_id, second_id}.issubset(ids))

    def test_exact_keyword_search_filters_all_listings_by_road_code(self):
        matched_id = self._seed_signal(
            source="facebook",
            title="Dat gan duong DL 12",
            description="Can ban gap lo dat duong DL 12",
            source_id="fb-dl12-spaced",
        )
        self._seed_signal(
            source="facebook",
            title="Dat gan duong DL 13",
            description="Can ban gap lo dat duong DL 13",
            source_id="fb-dl13",
        )

        response = self.client.get(f"/api/listings?city=Khac&ward={self.ward}&q=DL12&limit=20")
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([row["id"] for row in payload["listings"]], [matched_id])

    def test_keyword_search_filters_all_listings_without_accents(self):
        matched_id = self._seed_signal(
            source="facebook",
            title="Nhà gần địa danh Chánh Nghĩa",
            source_id="fb-chanh-nghia",
        )
        self._seed_signal(
            source="facebook",
            title="Nhà khu vực khác",
            source_id="fb-other-place",
        )

        response = self.client.get(
            f"/api/listings?city=Khac&ward={self.ward}&q=chanh nghia&limit=20"
        )
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([row["id"] for row in payload["listings"]], [matched_id])

    def test_source_filter_group_only_renders_for_admin(self):
        guest_html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("NGUỒN DỮ LIỆU", guest_html)
        self.assertNotIn('id="sourceFilters"', guest_html)

        self._login_as_admin()
        admin_html = self.client.get("/").get_data(as_text=True)

        self.assertIn("NGUỒN DỮ LIỆU", admin_html)
        self.assertIn('id="sourceFilters"', admin_html)
        self.assertRegex(
            admin_html,
            r'name="source"\s+value="facebook"\s+checked',
        )
        guland_pos = admin_html.index('value="guland"')
        self.assertNotIn("checked", admin_html[guland_pos:guland_pos + 100])


if __name__ == "__main__":
    unittest.main()

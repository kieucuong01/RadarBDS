import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class AdminControlRoomGateTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema
        import app as app_module

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_admin_gate.db"
        self.admin_identifier = f"admin-{uuid.uuid4().hex}@example.test"
        self.admin_token = f"admin-control-room-token-{uuid.uuid4().hex}"
        connection.close_all()
        self.patches = [
            mock.patch.object(connection, "DB_PATH", self.db_path),
            mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path),
        ]
        for patcher in self.patches:
            patcher.start()

        init_schema()
        self.client = app_module.app.test_client()

    def tearDown(self):
        from db import connection
        from db.connection import get_conn

        try:
            with get_conn() as conn:
                conn.execute("DELETE FROM user_sessions WHERE token = ?", (self.admin_token,))
                conn.execute("DELETE FROM users WHERE identifier = ?", (self.admin_identifier,))
                conn.execute("DELETE FROM listings WHERE url LIKE ?", ("https://example.test/%",))
                conn.execute("DELETE FROM raw_listings WHERE url LIKE ?", ("https://example.test/%",))
                conn.execute("DELETE FROM crawl_runs WHERE area LIKE ?", ("ops-test-%",))
        except Exception:
            pass

        connection.close_all()
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

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

    def _insert_suspected_dx132_pair(self):
        from db.connection import get_conn

        token = uuid.uuid4().hex
        with get_conn() as conn:
            raw_old = conn.execute(
                "INSERT INTO raw_listings (source, url, raw_json) VALUES (?, ?, ?)",
                ("facebook", f"https://example.test/raw-dx132-old-{token}", "{}"),
            )
            old = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, road_type,
                    road_tier, tho_cu_m2, possibly_duplicate, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    raw_old.lastrowid,
                    "facebook",
                    f"fb-dx132-old-{token}",
                    f"https://example.test/dx132-old-{token}",
                    "Old DX132 garden lot",
                    "Ban dat Tan An mat tien DX132, dien tich 1083m2, tho cu 200m2, duong nhua 5m.",
                    "Thu Dau Mot",
                    "Tan An",
                    "dat_nen",
                    5.95,
                    5.49,
                    1083.0,
                    "duong_nhua",
                    2,
                    200.0,
                    "2026-04-16",
                ),
            )
            raw_new = conn.execute(
                "INSERT INTO raw_listings (source, url, raw_json) VALUES (?, ?, ?)",
                ("facebook", f"https://example.test/raw-dx132-new-{token}", "{}"),
            )
            new = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, road_type,
                    road_tier, tho_cu_m2, possibly_duplicate, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    raw_new.lastrowid,
                    "facebook",
                    f"fb-dx132-new-{token}",
                    f"https://example.test/dx132-new-{token}",
                    "New DX132 garden lot",
                    "Dat dep Tan An duong DX132, DT 1083.7m2, TC 200m2, gia tot.",
                    "Thu Dau Mot",
                    "Tan An",
                    "dat_vuon",
                    5.5,
                    5.08,
                    1083.7,
                    "duong_nhua",
                    2,
                    200.0,
                    "2026-05-28",
                ),
            )
        return old.lastrowid, new.lastrowid

    def _insert_near_identical_dx132_pair(self):
        from db.connection import get_conn

        token = uuid.uuid4().hex
        with get_conn() as conn:
            raw_old = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", f"fb-near-old-{token}", f"https://example.test/raw-near-old-{token}", "{}"),
            )
            old = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                    road_type, road_tier, tho_cu_m2, possibly_duplicate, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    raw_old.lastrowid,
                    "facebook",
                    f"fb-near-old-{token}",
                    f"https://example.test/near-old-{token}",
                    "Ban dat Tan An DX132",
                    "Ban dat Tan An duong DX132, dien tich 1083m2, ngang 18m dai 60.2m, tho cu 200m2.",
                    "Thu Dau Mot",
                    "Tan An",
                    "dat_nen",
                    5.95,
                    5.49,
                    1083.0,
                    18.0,
                    60.2,
                    "duong_nhua",
                    2,
                    200.0,
                    "2026-04-16",
                ),
            )
            raw_new = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", f"fb-near-new-{token}", f"https://example.test/raw-near-new-{token}", "{}"),
            )
            new = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                    road_type, road_tier, tho_cu_m2, possibly_duplicate, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    raw_new.lastrowid,
                    "facebook",
                    f"fb-near-new-{token}",
                    f"https://example.test/near-new-{token}",
                    "Ban lai dat Tan An DX132",
                    "Ban lai lo dat Tan An duong DX132, dien tich 1083.4m2, ngang 18m dai 60.2m, tho cu 200m2.",
                    "Thu Dau Mot",
                    "Tan An",
                    "dat_nen",
                    5.9,
                    5.45,
                    1083.4,
                    18.0,
                    60.2,
                    "duong_nhua",
                    2,
                    200.0,
                    "2026-05-28",
                ),
            )
        return old.lastrowid, new.lastrowid

    def _insert_missing_ward_near_identical_pair(self):
        from db.connection import get_conn

        token = uuid.uuid4().hex
        description_old = "Ban nha 1 tret 1 lau, dien tich 5x15, 75m2, gan cho, duong oto, so rieng."
        description_new = "Ban nha 1 tret 1 lau, dien tich 5x15, 75m2, gan cho, duong oto, so rieng, can ban."
        with get_conn() as conn:
            raw_old = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", f"fb-missing-ward-old-{token}", f"https://example.test/raw-missing-ward-old-{token}", "{}"),
            )
            old = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                    possibly_duplicate, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    raw_old.lastrowid,
                    "facebook",
                    f"fb-missing-ward-old-{token}",
                    f"https://example.test/missing-ward-old-{token}",
                    "Ban nha 5x15",
                    description_old,
                    "Thu Dau Mot",
                    None,
                    "nha_dat",
                    3.2,
                    42.67,
                    75.0,
                    5.0,
                    15.0,
                    "2026-05-20",
                ),
            )
            raw_new = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", f"fb-missing-ward-new-{token}", f"https://example.test/raw-missing-ward-new-{token}", "{}"),
            )
            new = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                    possibly_duplicate, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    raw_new.lastrowid,
                    "facebook",
                    f"fb-missing-ward-new-{token}",
                    f"https://example.test/missing-ward-new-{token}",
                    "Ban lai nha 5x15",
                    description_new,
                    "Thu Dau Mot",
                    None,
                    "nha_dat",
                    3.18,
                    42.4,
                    75.0,
                    5.0,
                    15.0,
                    "2026-05-28",
                ),
            )
        return old.lastrowid, new.lastrowid

    def _insert_same_phone_text_duplicate_pair(self, *, road_old="DX94", road_new="DX94"):
        from db.connection import get_conn

        token = uuid.uuid4().hex
        phone = f"09{int(token[:8], 16) % 100000000:08d}"
        with get_conn() as conn:
            raw_old = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", f"fb-phone-old-{token}", f"https://example.test/raw-phone-old-{token}", "{}"),
            )
            old = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                    contact_phone, possibly_duplicate, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    raw_old.lastrowid,
                    "facebook",
                    f"fb-phone-old-{token}",
                    f"https://example.test/phone-old-{token}",
                    "Ban dat moi gioi dang lai",
                    f"Moi gioi dang lai lo dat duong {road_old}, so rieng, gia tot, lien he {phone}.",
                    "Thu Dau Mot",
                    "Hiep An",
                    "dat_nen",
                    1.95,
                    None,
                    None,
                    None,
                    None,
                    phone,
                    "2026-05-20",
                ),
            )
            raw_new = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", f"fb-phone-new-{token}", f"https://example.test/raw-phone-new-{token}", "{}"),
            )
            new = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                    contact_phone, possibly_duplicate, duplicate_of_id, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    raw_new.lastrowid,
                    "facebook",
                    f"fb-phone-new-{token}",
                    f"https://example.test/phone-new-{token}",
                    "Ban dat moi gioi repost",
                    f"Moi gioi dang lai lo dat duong {road_new}, so rieng, gia tot, lien he {phone}.",
                    "Thu Dau Mot",
                    "Hiep An",
                    "dat_nen",
                    1.95,
                    None,
                    None,
                    None,
                    None,
                    phone,
                    old.lastrowid,
                    "2026-05-28",
                ),
            )
        return old.lastrowid, new.lastrowid

    def _insert_distinctive_area_text_pair(self, *, road_old="", road_new="", area=747.4, ward_old="Tan An", ward_new="Tan An"):
        from db.connection import get_conn

        token = uuid.uuid4().hex
        road_text_old = f" duong {road_old}" if road_old else ""
        road_text_new = f" duong {road_new}" if road_new else road_text_old
        with get_conn() as conn:
            raw_old = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", f"fb-area-old-{token}", f"https://example.test/raw-area-old-{token}", "{}"),
            )
            old = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, possibly_duplicate, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    raw_old.lastrowid,
                    "facebook",
                    f"fb-area-old-{token}",
                    f"https://example.test/area-old-{token}",
                    "Ban lo dat dien tich dac thu",
                    f"Can ban lo dat{road_text_old}, dien tich {area}m2, so rieng, vi tri dep.",
                    "Thu Dau Mot",
                    ward_old,
                    "dat_nen",
                    4.1,
                    round(4.1 * 1000 / area, 2),
                    area,
                    "2026-05-20",
                ),
            )
            raw_new = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", f"fb-area-new-{token}", f"https://example.test/raw-area-new-{token}", "{}"),
            )
            new = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, possibly_duplicate, duplicate_of_id, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    raw_new.lastrowid,
                    "facebook",
                    f"fb-area-new-{token}",
                    f"https://example.test/area-new-{token}",
                    "Moi gioi dang lai lo dat dien tich dac thu",
                    f"Dang lai lo dat{road_text_new}, dien tich {area}m2, so rieng, vi tri dep.",
                    "Thu Dau Mot",
                    ward_new,
                    "dat_nen",
                    4.08,
                    round(4.08 * 1000 / area, 2),
                    area,
                    old.lastrowid,
                    "2026-05-28",
                ),
            )
        return old.lastrowid, new.lastrowid

    def _insert_review_duplicate_pair(
        self,
        *,
        ward_old="Hiep An",
        ward_new="Hiep An",
        area_old=100.0,
        area_new=100.0,
        frontage_old=None,
        frontage_new=None,
        depth_old=None,
        depth_new=None,
        road_old="",
        road_new="",
        description_old="",
        description_new="",
        property_type="dat_nen",
    ):
        from db.connection import get_conn

        token = uuid.uuid4().hex
        road_text_old = f" duong {road_old}" if road_old else ""
        road_text_new = f" duong {road_new}" if road_new else road_text_old
        desc_old = description_old or f"Can ban lo dat{road_text_old}, so rieng, vi tri dep."
        desc_new = description_new or f"Dang lai lo dat{road_text_new}, so rieng, vi tri dep."
        price = 2.4

        def ppm(area):
            return round(price * 1000 / area, 2) if area else None

        with get_conn() as conn:
            raw_old = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", f"fb-review-old-{token}", f"https://example.test/raw-review-old-{token}", "{}"),
            )
            old = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                    possibly_duplicate, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    raw_old.lastrowid,
                    "facebook",
                    f"fb-review-old-{token}",
                    f"https://example.test/review-old-{token}",
                    "Tin goc review duplicate",
                    desc_old,
                    "Thu Dau Mot",
                    ward_old,
                    property_type,
                    price,
                    ppm(area_old),
                    area_old,
                    frontage_old,
                    depth_old,
                    "2026-05-20",
                ),
            )
            raw_new = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", f"fb-review-new-{token}", f"https://example.test/raw-review-new-{token}", "{}"),
            )
            new = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description, area, ward,
                    property_type, price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                    possibly_duplicate, duplicate_of_id, posted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    raw_new.lastrowid,
                    "facebook",
                    f"fb-review-new-{token}",
                    f"https://example.test/review-new-{token}",
                    "Tin dang lai review duplicate",
                    desc_new,
                    "Thu Dau Mot",
                    ward_new,
                    property_type,
                    price,
                    ppm(area_new),
                    area_new,
                    frontage_new,
                    depth_new,
                    old.lastrowid,
                    "2026-05-28",
                ),
            )
        return old.lastrowid, new.lastrowid

    def test_guest_control_room_renders_login_modal_gate(self):
        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="authModal"', html)
        self.assertIn("Đăng nhập admin", html)
        self.assertIn("js/auth.js", html)
        self.assertNotIn("js/admin.js", html)

    def test_public_auth_header_keeps_vietnamese_labels(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Đăng nhập", html)
        self.assertIn("Đăng nhập tài khoản", html)

        self._login_as_admin()
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Tài khoản", html)
        self.assertIn("Tài khoản của bạn", html)

    def test_guest_admin_api_still_requires_admin(self):
        response = self.client.get("/admin/api/users")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "admin_required")

    def test_admin_can_delete_lead_and_audit_the_action(self):
        from db.connection import get_conn

        self._login_as_admin()
        token = uuid.uuid4().hex
        with get_conn() as conn:
            lead = conn.execute(
                """
                INSERT INTO lead_captures (listing_url, zalo_phone, source_context, note, status)
                VALUES (?, ?, 'card_signal', 'test lead delete', 'new')
                """,
                (f"https://example.test/lead-delete-{token}", f"090{token[:7]}"),
            )
            lead_id = lead.lastrowid

        response = self.client.delete(f"/admin/api/leads/{lead_id}")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        with get_conn() as conn:
            self.assertIsNone(
                conn.execute("SELECT id FROM lead_captures WHERE id=?", (lead_id,)).fetchone()
            )
            audit = conn.execute(
                """
                SELECT action, entity_type, entity_id, before_json, reason
                FROM admin_audit_log
                WHERE action='lead_delete' AND entity_id=?
                """,
                (lead_id,),
            ).fetchone()
        self.assertIsNotNone(audit)
        self.assertEqual(audit["entity_type"], "lead")
        self.assertEqual(audit["reason"], "admin_delete")
        self.assertIn("zalo_phone", audit["before_json"])

    def test_public_lead_capture_creates_lead_and_audit_row(self):
        from db.connection import get_conn

        token = uuid.uuid4().hex
        lead_id = None
        with get_conn() as conn:
            raw = conn.execute(
                "INSERT INTO raw_listings (source, url, raw_json) VALUES ('facebook', ?, '{}')",
                (f"https://example.test/lead-capture-raw-{token}",),
            )
            listing = conn.execute(
                """
                INSERT INTO listings (raw_id, source, url, title, area, property_type, price_ty, area_m2)
                VALUES (?, 'facebook', ?, 'Lead capture listing', 'Thu Dau Mot', 'dat_nen', 1.2, 80)
                """,
                (raw.lastrowid, f"https://example.test/lead-capture-listing-{token}"),
            )
            listing_id = listing.lastrowid

        response = self.client.post(
            "/api/leads",
            json={
                "listing_id": listing_id,
                "zalo_phone": "0901 222 333",
                "source_context": "card_signal",
                "note": "Xin tu van them",
            },
            environ_base={"REMOTE_ADDR": f"10.81.{int(token[:2], 16)}.{int(token[2:4], 16)}"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        lead_id = data["lead_id"]
        with get_conn() as conn:
            lead = conn.execute(
                "SELECT listing_id, zalo_phone, source_context, status FROM lead_captures WHERE id=?",
                (lead_id,),
            ).fetchone()
            audit = conn.execute(
                "SELECT action, listing_id FROM user_audit_log WHERE action='lead_capture' AND listing_id=?",
                (listing_id,),
            ).fetchone()
            conn.execute("DELETE FROM lead_captures WHERE id=?", (lead_id,))

        self.assertIsNotNone(lead)
        self.assertEqual(lead["listing_id"], listing_id)
        self.assertEqual(lead["zalo_phone"], "901222333")
        self.assertEqual(lead["source_context"], "card_signal")
        self.assertEqual(lead["status"], "new")
        self.assertIsNotNone(audit)

    def test_guest_lead_capture_defaults_note_for_existing_listing(self):
        from db.connection import get_conn

        token = uuid.uuid4().hex
        with get_conn() as conn:
            raw = conn.execute(
                "INSERT INTO raw_listings (source, url, raw_json) VALUES ('facebook', ?, '{}')",
                (f"https://example.test/guest-lead-raw-{token}",),
            )
            listing = conn.execute(
                """
                INSERT INTO listings (raw_id, source, url, title, area, property_type, price_ty, area_m2)
                VALUES (?, 'facebook', ?, 'Guest lead listing', 'Thu Dau Mot', 'dat_nen', 1.2, 80)
                """,
                (raw.lastrowid, f"https://example.test/guest-lead-listing-{token}"),
            )
            listing_id = listing.lastrowid

        response = self.client.post(
            "/api/lead-capture-guest",
            json={"listing_id": listing_id, "contact": "0901 222 334", "context": "modal_signal"},
            environ_base={"REMOTE_ADDR": f"10.82.{int(token[:2], 16)}.{int(token[2:4], 16)}"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        lead_id = data["lead_id"]
        with get_conn() as conn:
            lead = conn.execute(
                "SELECT listing_id, zalo_phone, source_context, note, urgency FROM lead_captures WHERE id=?",
                (lead_id,),
            ).fetchone()
            conn.execute("DELETE FROM lead_captures WHERE id=?", (lead_id,))

        self.assertIsNotNone(lead)
        self.assertEqual(lead["listing_id"], listing_id)
        self.assertEqual(lead["zalo_phone"], "0901222334")
        self.assertEqual(lead["source_context"], "modal_signal")
        self.assertIn(f"#{listing_id}", lead["note"])
        self.assertEqual(lead["urgency"], "guest")

    def test_admin_can_delete_user_dependents_but_not_current_admin(self):
        from db.connection import get_conn

        self._login_as_admin()
        token = uuid.uuid4().hex
        with get_conn() as conn:
            admin_id = conn.execute(
                "SELECT id FROM users WHERE identifier=?",
                (self.admin_identifier,),
            ).fetchone()["id"]
            user = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier)
                VALUES (?, 'email', 'hash', 'vip')
                """,
                (f"user-delete-{token}@example.test",),
            )
            user_id = user.lastrowid
            conn.execute(
                "INSERT INTO user_sessions (token, user_id, expires_at) VALUES (?, ?, '2099-01-01T00:00:00')",
                (f"user-delete-session-{token}", user_id),
            )
            conn.execute(
                "INSERT INTO user_watchlists (user_id, name, wards, prop_types) VALUES (?, 'Watch', '[]', '[]')",
                (user_id,),
            )
            raw = conn.execute(
                "INSERT INTO raw_listings (source, url, raw_json) VALUES ('facebook', ?, '{}')",
                (f"https://example.test/user-delete-raw-{token}",),
            )
            listing = conn.execute(
                """
                INSERT INTO listings (raw_id, source, url, title, area, property_type, price_ty, area_m2)
                VALUES (?, 'facebook', ?, 'User delete dependent listing', 'Thu Dau Mot', 'dat_nen', 1.2, 80)
                """,
                (raw.lastrowid, f"https://example.test/user-delete-listing-{token}"),
            )
            conn.execute(
                "INSERT INTO notification_log (user_id, listing_id, channel) VALUES (?, ?, 'email')",
                (user_id, listing.lastrowid),
            )
            lead = conn.execute(
                """
                INSERT INTO lead_captures (user_id, listing_url, zalo_phone, source_context, note, status)
                VALUES (?, ?, '0911222333', 'modal_signal', 'linked lead', 'called')
                """,
                (user_id, f"https://example.test/user-delete-lead-{token}"),
            )
            lead_id = lead.lastrowid

        self_response = self.client.delete(f"/admin/api/users/{admin_id}")
        response = self.client.delete(f"/admin/api/users/{user_id}")

        self.assertEqual(self_response.status_code, 400)
        self.assertEqual(self_response.get_json()["error"], "cannot_delete_self")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        with get_conn() as conn:
            self.assertIsNone(conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone())
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM user_sessions WHERE user_id=?", (user_id,)).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM user_watchlists WHERE user_id=?", (user_id,)).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM notification_log WHERE user_id=?", (user_id,)).fetchone()[0],
                0,
            )
            self.assertIsNone(
                conn.execute("SELECT user_id FROM lead_captures WHERE id=?", (lead_id,)).fetchone()["user_id"]
            )
            audit = conn.execute(
                "SELECT action, entity_type, entity_id, before_json FROM admin_audit_log WHERE action='user_delete' AND entity_id=?",
                (user_id,),
            ).fetchone()
        self.assertIsNotNone(audit)
        self.assertEqual(audit["entity_type"], "user")
        self.assertIn("identifier", audit["before_json"])

    def test_admin_session_loads_control_room_workspace(self):
        self._login_as_admin()

        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("js/admin.js", html)
        self.assertNotIn('id="authModal"', html)

    def test_admin_control_room_accepts_panel_slug_path(self):
        self._login_as_admin()

        response = self.client.get("/admin/facebook-crawl")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-admin-initial-panel="crawl"', html)
        self.assertIn('data-panel-slug="facebook-crawl"', html)

    def test_admin_control_room_rejects_unknown_panel_slug(self):
        self._login_as_admin()

        response = self.client.get("/admin/not-a-panel")

        self.assertEqual(response.status_code, 404)

    def test_legacy_control_room_path_redirects_to_short_admin_slug(self):
        self._login_as_admin()

        response = self.client.get("/admin/control-room/facebook-crawl")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/facebook-crawl")

    def test_admin_js_updates_panel_slug_history(self):
        js = (Path(__file__).resolve().parent.parent / "static/js/admin.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("ADMIN_PANEL_SLUGS", js)
        self.assertIn("function panelFromLocation", js)
        self.assertIn("return `/admin/${panelSlug(name)}`", js)
        self.assertIn("history.pushState", js)
        self.assertIn("popstate", js)

    def test_admin_workspace_uses_real_icons_not_text_abbreviations(self):
        root = Path(__file__).resolve().parent.parent
        html = (root / "templates/admin_control_room.html").read_text(encoding="utf-8")
        css = (root / "static/css/admin.css").read_text(encoding="utf-8")

        self.assertIn('class="admin-icon {{ extra }}"', html)
        self.assertIn("admin_icon('users', 'nav-svg')", html)
        self.assertIn("admin_icon('shield-check', 'nav-svg')", html)
        self.assertIn("admin_icon('refresh', 'btn-svg')", html)
        self.assertIn('aria-hidden="true"', html)
        self.assertNotIn('<span class="nav-icon">LC</span>', html)
        self.assertNotIn('<span class="nav-icon">DQ</span>', html)
        self.assertIn(".admin-icon", css)
        self.assertIn(".nav-item.active .nav-icon", css)
        self.assertIn(".btn-icon-label", css)

    def test_data_quality_duplicate_queue_loads_duplicate_pairs(self):
        from db.connection import get_conn

        self._login_as_admin()
        token = uuid.uuid4().hex
        with get_conn() as conn:
            raw_canonical = conn.execute(
                "INSERT INTO raw_listings (source, url, raw_json) VALUES (?, ?, ?)",
                ("facebook", f"https://example.test/raw-canonical-{token}", "{}"),
            )
            canonical = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, url, title, area, property_type,
                    price_ty, price_per_m2, area_m2, possibly_duplicate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    raw_canonical.lastrowid,
                    "facebook",
                    f"https://example.test/canonical-{token}",
                    "Canonical lot",
                    "Thu Dau Mot",
                    "dat_nen",
                    1.8,
                    18.0,
                    100.0,
                ),
            )
            raw_dup = conn.execute(
                "INSERT INTO raw_listings (source, url, raw_json) VALUES (?, ?, ?)",
                ("facebook", f"https://example.test/raw-duplicate-{token}", "{}"),
            )
            conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, url, title, area, property_type,
                    price_ty, price_per_m2, area_m2, possibly_duplicate, duplicate_of_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    raw_dup.lastrowid,
                    "facebook",
                    f"https://example.test/duplicate-{token}",
                    "Duplicate lot",
                    "Thu Dau Mot",
                    "dat_nen",
                    1.82,
                    18.2,
                    100.0,
                    canonical.lastrowid,
                ),
            )

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        items = response.get_json()["items"]
        self.assertTrue(any(item["canonical_title"] == "Canonical lot" for item in items))

    def test_data_quality_duplicate_queue_hides_high_confidence_pairs(self):
        from db.connection import get_conn

        self._login_as_admin()
        token = uuid.uuid4().hex
        with get_conn() as conn:
            raw_canonical = conn.execute(
                "INSERT INTO raw_listings (source, url, raw_json) VALUES (?, ?, ?)",
                ("facebook", f"https://example.test/raw-clear-canonical-{token}", "{}"),
            )
            canonical = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, url, title, area, ward, property_type,
                    price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                    possibly_duplicate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    raw_canonical.lastrowid,
                    "facebook",
                    f"https://example.test/clear-canonical-{token}",
                    "Clear canonical lot",
                    "Thu Dau Mot",
                    "Phu Loi",
                    "dat_nen",
                    1.8,
                    18.0,
                    100.0,
                    5.0,
                    20.0,
                ),
            )
            raw_dup = conn.execute(
                "INSERT INTO raw_listings (source, url, raw_json) VALUES (?, ?, ?)",
                ("facebook", f"https://example.test/raw-clear-duplicate-{token}", "{}"),
            )
            duplicate = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, url, title, area, ward, property_type,
                    price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                    possibly_duplicate, duplicate_of_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    raw_dup.lastrowid,
                    "facebook",
                    f"https://example.test/clear-duplicate-{token}",
                    "Clear duplicate lot",
                    "Thu Dau Mot",
                    "Phu Loi",
                    "dat_nen",
                    1.79,
                    17.9,
                    100.5,
                    5.02,
                    20.1,
                    canonical.lastrowid,
                ),
            )

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.get_json()["items"]}
        self.assertNotIn(duplicate.lastrowid, ids)

    def test_data_quality_duplicate_queue_hides_same_facebook_post_pairs(self):
        from db.connection import get_conn

        self._login_as_admin()
        token = uuid.uuid4().hex
        same_source_id = f"fb-post-{token}"
        with get_conn() as conn:
            raw_canonical = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", same_source_id, f"https://example.test/raw-same-post-canonical-{token}", "{}"),
            )
            canonical = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, area, property_type,
                    price_ty, price_per_m2, area_m2, possibly_duplicate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    raw_canonical.lastrowid,
                    "facebook",
                    same_source_id,
                    f"https://example.test/same-post-canonical-{token}",
                    "Same Facebook post canonical",
                    "Thu Dau Mot",
                    "dat_nen",
                    1.8,
                    18.0,
                    100.0,
                ),
            )
            raw_dup = conn.execute(
                "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                ("facebook", same_source_id, f"https://example.test/raw-same-post-duplicate-{token}", "{}"),
            )
            duplicate = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, area, property_type,
                    price_ty, price_per_m2, area_m2, possibly_duplicate, duplicate_of_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    raw_dup.lastrowid,
                    "facebook",
                    same_source_id,
                    f"https://example.test/same-post-duplicate-{token}",
                    "Same Facebook post duplicate",
                    "Thu Dau Mot",
                    "dat_nen",
                    1.82,
                    18.2,
                    100.0,
                    canonical.lastrowid,
                ),
            )

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.get_json()["items"]}
        self.assertNotIn(duplicate.lastrowid, ids)

    def test_data_quality_duplicate_queue_hides_unmerged_same_facebook_post_pairs(self):
        from db.connection import get_conn

        self._login_as_admin()
        token = uuid.uuid4().hex
        same_source_id = f"fb-unmerged-post-{token}"
        with get_conn() as conn:
            for suffix, price in (("old", 5.9), ("new", 5.8)):
                raw = conn.execute(
                    "INSERT INTO raw_listings (source, source_id, url, raw_json) VALUES (?, ?, ?, ?)",
                    ("facebook", same_source_id, f"https://example.test/raw-unmerged-{suffix}-{token}", "{}"),
                )
                conn.execute(
                    """
                    INSERT INTO listings (
                        raw_id, source, source_id, url, title, description, area, ward,
                        property_type, price_ty, price_per_m2, area_m2, frontage_m, depth_m,
                        road_type, road_tier, tho_cu_m2, possibly_duplicate, posted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        raw.lastrowid,
                        "facebook",
                        same_source_id,
                        f"https://example.test/unmerged-{suffix}-{token}",
                        f"Same post DX132 {suffix}",
                        "Ban dat Tan An duong DX132, dien tich 1083m2, tho cu 200m2.",
                        "Thu Dau Mot",
                        "Tan An",
                        "dat_nen",
                        price,
                        round(price * 1000 / 1083, 2),
                        1083.0,
                        18.0,
                        60.2,
                        "duong_nhua",
                        2,
                        200.0,
                        "2026-05-28",
                    ),
                )

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        items = response.get_json()["items"]
        self.assertFalse(
            any(item.get("source_id") == same_source_id and item.get("canonical_source_id") == same_source_id for item in items)
        )

    def test_data_quality_duplicate_queue_hides_near_identical_unmerged_pairs_without_writing(self):
        from db.connection import get_conn

        self._login_as_admin()
        old_id, new_id = self._insert_near_identical_dx132_pair()

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        pairs = {(item["id"], item["duplicate_of_id"]) for item in response.get_json()["items"]}
        self.assertNotIn((old_id, new_id), pairs)
        with get_conn() as conn:
            merged = conn.execute(
                "SELECT possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
                (old_id,),
            ).fetchone()
            override = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM dedup_overrides
                WHERE listing_id=? AND target_listing_id=? AND active=1
                """,
                (old_id, new_id),
            ).fetchone()["count"]

        self.assertEqual(merged["possibly_duplicate"], 0)
        self.assertIsNone(merged["duplicate_of_id"])
        self.assertEqual(override, 0)

    def test_data_quality_duplicate_queue_auto_merges_near_identical_pairs_when_both_wards_missing(self):
        from db.connection import get_conn

        self._login_as_admin()
        old_id, new_id = self._insert_missing_ward_near_identical_pair()
        with get_conn() as conn:
            conn.execute(
                "UPDATE listings SET possibly_duplicate=1, duplicate_of_id=? WHERE id=?",
                (new_id, old_id),
            )

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        pairs = {(item["id"], item["duplicate_of_id"]) for item in response.get_json()["items"]}
        self.assertNotIn((old_id, new_id), pairs)

    def test_data_quality_duplicate_queue_hides_same_phone_near_identical_text_reposts(self):
        self._login_as_admin()
        old_id, new_id = self._insert_same_phone_text_duplicate_pair()

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        pairs = {(item["id"], item["duplicate_of_id"]) for item in response.get_json()["items"]}
        self.assertNotIn((new_id, old_id), pairs)

    def test_data_quality_duplicate_queue_hides_same_phone_text_reposts_when_roads_conflict_without_writing(self):
        self._login_as_admin()
        old_id, new_id = self._insert_same_phone_text_duplicate_pair(road_old="DX94", road_new="DX127")

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        pairs = {(item["id"], item["duplicate_of_id"]) for item in response.get_json()["items"]}
        self.assertNotIn((new_id, old_id), pairs)

        from db.connection import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
                (new_id,),
            ).fetchone()

        self.assertEqual(row["possibly_duplicate"], 1)
        self.assertEqual(row["duplicate_of_id"], old_id)

    def test_data_quality_duplicate_queue_hides_distinctive_area_near_text_reposts(self):
        self._login_as_admin()
        old_id, new_id = self._insert_distinctive_area_text_pair(area=747.4)

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        pairs = {(item["id"], item["duplicate_of_id"]) for item in response.get_json()["items"]}
        self.assertNotIn((new_id, old_id), pairs)

    def test_data_quality_duplicate_queue_hides_distinctive_area_near_text_with_missing_ward_without_writing(self):
        self._login_as_admin()
        old_id, new_id = self._insert_distinctive_area_text_pair(area=747.4, ward_new="")

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        pairs = {(item["id"], item["duplicate_of_id"]) for item in response.get_json()["items"]}
        self.assertNotIn((new_id, old_id), pairs)

        from db.connection import get_conn

        with get_conn() as conn:
            override_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM dedup_overrides
                WHERE listing_id=?
                """,
                (new_id,),
            ).fetchone()["count"]

        self.assertEqual(override_count, 0)

        second_response = self.client.get("/admin/api/qc/duplicates")
        self.assertEqual(second_response.status_code, 200)
        with get_conn() as conn:
            override_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM dedup_overrides
                WHERE listing_id=?
                  AND target_listing_id=?
                  AND action='merge'
                  AND note='admin_qc_auto_merge_near_identical'
                """,
                (new_id, old_id),
            ).fetchone()["count"]
        self.assertEqual(override_count, 0)

    def test_data_quality_duplicate_queue_hides_distinctive_area_reposts_when_roads_conflict_without_writing(self):
        self._login_as_admin()
        old_id, new_id = self._insert_distinctive_area_text_pair(road_old="DX94", road_new="DX127", area=747.4)

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        pairs = {(item["id"], item["duplicate_of_id"]) for item in response.get_json()["items"]}
        self.assertNotIn((new_id, old_id), pairs)
        # GET only reads/filters the review queue. It must not mutate production rows while loading the tab.
        from db.connection import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
                (new_id,),
            ).fetchone()

        self.assertEqual(row["possibly_duplicate"], 1)
        self.assertEqual(row["duplicate_of_id"], old_id)

    def test_data_quality_duplicate_queue_hides_missing_area_same_ward_near_text_without_writing(self):
        self._login_as_admin()
        old_id, new_id = self._insert_review_duplicate_pair(
            area_old=None,
            area_new=None,
            description_old="Ban dat Hiep An so rieng gia tot, can ban nhanh.",
            description_new="Ban dat Hiep An so rieng gia tot, can ban nhanh.",
        )

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        pairs = {(item["id"], item["duplicate_of_id"]) for item in response.get_json()["items"]}
        self.assertNotIn((new_id, old_id), pairs)

        from db.connection import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT possibly_duplicate, duplicate_of_id FROM listings WHERE id=?",
                (new_id,),
            ).fetchone()
        self.assertEqual(row["possibly_duplicate"], 1)
        self.assertEqual(row["duplicate_of_id"], old_id)

    def test_data_quality_duplicate_queue_hides_relaxed_depth_same_road_signature(self):
        self._login_as_admin()
        old_id, new_id = self._insert_review_duplicate_pair(
            area_old=119.0,
            area_new=118.0,
            frontage_old=5.0,
            frontage_new=5.0,
            depth_old=23.8,
            depth_new=22.8,
            road_old="DX94",
            road_new="DX94",
            description_old="Lo dat Hiep An DX94 5x23.8 so hong rieng.",
            description_new="Chinh chu can ra nhanh nen DX94 kich thuoc 5m x 22.8m.",
        )

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        pairs = {(item["id"], item["duplicate_of_id"]) for item in response.get_json()["items"]}
        self.assertNotIn((new_id, old_id), pairs)

    def test_data_quality_duplicate_queue_hides_missing_ward_shared_road_matching_dimensions(self):
        self._login_as_admin()
        old_id, new_id = self._insert_review_duplicate_pair(
            ward_old=None,
            ward_new=None,
            area_old=187.0,
            area_new=187.0,
            frontage_old=5.0,
            frontage_new=5.0,
            depth_old=38.0,
            depth_new=38.0,
            road_old="DX132",
            road_new="DX132",
            description_old="Ban dat duong DX132 ngang 5 dai 38, so rieng.",
            description_new="Dang lai dat DX132 ngang 5 dai 38 can ban nhanh.",
        )

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        pairs = {(item["id"], item["duplicate_of_id"]) for item in response.get_json()["items"]}
        self.assertNotIn((new_id, old_id), pairs)

    def test_data_quality_duplicate_queue_surfaces_unmerged_suspected_same_lot_pairs(self):
        self._login_as_admin()
        old_id, new_id = self._insert_suspected_dx132_pair()

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        items = response.get_json()["items"]
        suspected = [
            item for item in items
            if item["id"] == old_id and item["duplicate_of_id"] == new_id
        ]
        self.assertTrue(suspected)
        self.assertTrue(suspected[0]["suspected_duplicate"])
        self.assertIn("Nghi ngờ cùng lô", suspected[0]["qc_reasons"])

    def test_data_quality_duplicate_queue_hides_suspected_pair_after_admin_split_override(self):
        from db.connection import get_conn

        self._login_as_admin()
        old_id, new_id = self._insert_suspected_dx132_pair()
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO dedup_overrides (action, listing_id, target_listing_id, note, active, updated_at)
                VALUES ('split', ?, ?, 'not_same_lot', 1, datetime('now'))
                """,
                (old_id, new_id),
            )

        response = self.client.get("/admin/api/qc/duplicates")

        self.assertEqual(response.status_code, 200)
        pairs = {(item["id"], item["duplicate_of_id"]) for item in response.get_json()["items"]}
        self.assertNotIn((old_id, new_id), pairs)

    def test_admin_duplicate_review_ui_explains_the_decision(self):
        root = Path(__file__).resolve().parent.parent
        js = (root / "static/js/admin.js").read_text(encoding="utf-8")
        css = (root / "static/css/admin.css").read_text(encoding="utf-8")
        template = (root / "templates/admin_control_room.html").read_text(encoding="utf-8")

        self.assertEqual(js.count("function duplicateCard"), 1)
        self.assertIn("Tin nghi trùng cần admin review", js)
        self.assertIn("Tin nghi trùng", js)
        self.assertIn("Tin gốc để so sánh", js)
        self.assertIn("Mở tin gốc", js)
        self.assertIn("So sánh nhanh", js)
        self.assertIn("Tên đường", js)
        self.assertIn("Gộp vào tin gốc", js)
        self.assertIn("Giữ cả hai tin và không hỏi lại", js)
        self.assertNotIn("Gộp: ẩn tin bên trái", js)
        self.assertIn("dup-summary-grid", js)
        self.assertIn("dup-source-links", js)
        self.assertIn("dup-facts", js)
        self.assertIn(".dup-summary-grid", css)
        self.assertIn(".dup-source-links", css)
        self.assertIn(".dup-fact.price", css)
        self.assertIn(".dup-decision-copy", css)
        self.assertIn("admin-v39-delete-actions", template)
        self.assertIn("admin-favicon-32.png", template)
        self.assertIn("admin-apple-touch-icon.png", template)
        self.assertIn("admin.webmanifest", template)
        self.assertIn("images/logo.png", template)
        self.assertIn(".brand-mark img", css)
        self.assertIn('content: "AD"', css)

    def test_ai_training_requires_explicit_valuation_choice_in_js(self):
        js = (Path(__file__).resolve().parent.parent / "static/js/admin.js").read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            'class="chip active" data-card="${cid}" data-group="valuation" data-value="cheap_real"',
            js,
        )
        self.assertIn("if (!valuation)", js)
        self.assertNotIn("syncExtractionState", js)
        self.assertNotIn('data-group="extraction"', js)
        self.assertNotIn("wrong_ward", js)
        self.assertNotIn("wrong_road", js)
        self.assertNotIn("wrong_property_type", js)
        self.assertNotIn("wrong_price", js)
        self.assertNotIn("wrong_area", js)
        self.assertNotIn("legalStatus !== 'has_document'", js)
        self.assertNotIn("(x.is_legal_qc || legal.status) ? `", js)

    def test_ai_training_template_is_valuation_only(self):
        self._login_as_admin()

        response = self.client.get("/admin/ai-training")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="trainingGrid"', html)
        self.assertNotIn('id="trnQueue"', html)
        self.assertNotIn('value="source_qc"', html)
        self.assertNotIn('value="legal_qc"', html)
        self.assertNotIn('value="recheck"', html)

    def test_admin_js_has_loading_toast_feedback_for_actions(self):
        root = Path(__file__).resolve().parent.parent
        js = (root / "static/js/admin.js").read_text(encoding="utf-8")
        css = (root / "static/css/admin.css").read_text(encoding="utf-8")

        self.assertIn("function showAdminToast", js)
        self.assertIn("async function withAdminToast", js)
        self.assertIn("adminToastDepth", js)
        self.assertIn("Đang xử lý tác vụ", js)
        self.assertIn("Đang tải dữ liệu", js)
        self.assertNotIn("Dang tai du lieu", js)
        self.assertNotIn("Dang xu ly tac vu", js)
        self.assertIn("facebook-crawl/jobs", js)
        self.assertIn("Fetched ${Number(crawl.fetched || 0)}", js)
        self.assertIn("Reprocess new ${Number(reprocess.new || 0)}", js)
        self.assertIn("function ensureAdminLoadingOverlay", js)
        self.assertIn("function syncAdminLoadingOverlay", js)
        self.assertIn("adminLoadingOverlay", js)
        self.assertIn(".admin-toast-root", css)
        self.assertIn(".admin-toast.loading", css)
        self.assertIn(".admin-main-loading", css)
        self.assertIn("backdrop-filter", css)
        self.assertIn("body.sidebar-collapsed .admin-main-loading", css)

    def test_admin_manual_first_crawl_allows_900_post_limit(self):
        import app as app_module

        self._login_as_admin()

        class FakeThread:
            def __init__(self, target=None, args=(), daemon=None):
                self.target = target
                self.args = args
                self.daemon = daemon

            def start(self):
                return None

        with app_module.FACEBOOK_CRAWL_LOCK:
            app_module.FACEBOOK_CRAWL_JOBS.clear()
            app_module.FACEBOOK_CRAWL_JOB_ORDER.clear()

        with mock.patch.object(app_module.threading, "Thread", FakeThread):
            response = self.client.post(
                "/admin/api/facebook-crawl/run",
                json={
                    "url": "https://www.facebook.com/nhadatkhanhmy",
                    "mode": "first",
                    "limit": 900,
                    "download_images": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["job"]["limit"], 900)

    def test_admin_crawl_config_includes_ops_summary(self):
        import app as app_module
        from db.connection import get_conn

        self._login_as_admin()
        token = uuid.uuid4().hex[:8]
        area = f"ops-test-{token}"
        started_ok = f"2099-01-01T00:{int(token[:2], 16) % 50:02d}:00"
        started_err = f"2099-01-01T00:{int(token[:2], 16) % 50:02d}:30"
        before_images = app_module._facebook_crawl_summary()["missing_images"]
        with get_conn() as conn:
            raw = conn.execute(
                """
                INSERT INTO raw_listings (source, url, raw_json)
                VALUES (?, ?, ?)
                """,
                ("facebook", f"https://example.test/{uuid.uuid4().hex}", "{}"),
            )
            listing = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, url, title, area, property_type,
                    price_ty, price_per_m2, area_m2
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw.lastrowid,
                    "facebook",
                    f"https://example.test/listing/{uuid.uuid4().hex}",
                    "Signal seed",
                    "Ben Cat",
                    "dat",
                    1.0,
                    10.0,
                    100.0,
                ),
            )
            conn.execute(
                """
                INSERT INTO valuation_results (listing_id, fair_ppm2, actual_ppm2, mos_pct, is_signal)
                VALUES (?, 10, 7, 30, 1)
                """,
                (listing.lastrowid,),
            )
            conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order, local_path)
                VALUES (?, ?, 0, ?)
                """,
                (listing.lastrowid, "https://facebook.example/image-ok.jpg", "1_0.jpg"),
            )
            conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order, local_path)
                VALUES (?, ?, 1, NULL)
                """,
                (listing.lastrowid, "https://facebook.example/image-missing.jpg"),
            )
            conn.execute(
                """
                INSERT INTO crawl_runs (
                    source, area, n_fetched, n_new, n_updated, n_skipped,
                    status, error_msg, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "guland",
                    area,
                    12,
                    4,
                    2,
                    1,
                    "done",
                    "",
                    started_ok,
                    "2099-01-01T00:59:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO crawl_runs (
                    source, area, n_fetched, n_new, n_updated, n_skipped,
                    status, error_msg, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "batdongsan",
                    area,
                    0,
                    0,
                    0,
                    0,
                    "error",
                    "Cloudflare",
                    started_err,
                    "2099-01-01T00:58:00",
                ),
            )

        with mock.patch.object(app_module, "_daily_crawl_schedule_status", return_value={
            "task_name": "RadarBDS_DailyCrawl",
            "installed": True,
            "state": "Ready",
            "next_run_time": "5/27/2026 9:00:00 PM",
            "last_run_time": "5/26/2026 9:00:00 PM",
            "last_result": "0",
            "run_time": "21:00",
            "task_to_run": "cmd /c crawl-daily",
            "error": "",
        }), mock.patch.object(app_module, "_active_radar_lock_blockers", return_value=[
            {"name": "reprocess", "pid": 1234, "state": "idle in transaction", "age_seconds": 90}
        ]):
            response = self.client.get("/admin/api/facebook-crawl/config")

        self.assertEqual(response.status_code, 200)
        summary = response.get_json()["summary"]
        missing_images = summary["missing_images"]
        self.assertEqual(summary["pending_images"], before_images["missing_image_refs"] + 1)
        self.assertEqual(missing_images["missing_image_refs"], before_images["missing_image_refs"] + 1)
        self.assertEqual(missing_images["downloaded_image_refs"], before_images["downloaded_image_refs"] + 1)
        self.assertEqual(missing_images["total_image_refs"], before_images["total_image_refs"] + 2)
        self.assertEqual(
            missing_images["listings_with_missing_images"],
            before_images["listings_with_missing_images"] + 1,
        )
        self.assertEqual(missing_images["listings_with_images"], before_images["listings_with_images"] + 1)
        self.assertIsInstance(missing_images["missing_pct"], float)
        ops = summary["ops"]
        self.assertEqual(ops["schedule"]["run_time"], "21:00")
        self.assertEqual(ops["last_run"]["source"], "batdongsan")
        self.assertEqual(ops["last_24h"]["new"], 4)
        self.assertGreaterEqual(ops["signal_count"], 1)
        self.assertEqual(ops["source_errors"][0]["source"], "batdongsan")
        self.assertEqual(ops["lock_blockers"][0]["name"], "reprocess")

    def test_admin_facebook_crawl_config_scores_broker_cadence_without_penalizing_reposts(self):
        from datetime import datetime, timedelta, timezone
        import json
        import app as app_module
        from db.connection import get_conn

        self._login_as_admin()
        token = uuid.uuid4().hex
        profile_url = f"https://www.facebook.com/broker-{token}"
        profile_path = self.tmpdir / "facebook_profiles.json"
        profile_path.write_text(
            json.dumps({
                "Bến Cát": [{
                    "url": profile_url,
                    "broker_name": "Broker repost tốt",
                    "daily_limit": 8,
                    "range_days": 7,
                    "active": True,
                }]
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with mock.patch.object(app_module, "FACEBOOK_PROFILE_PATH", profile_path):
            with get_conn() as conn:
                for idx in range(18):
                    crawled_at = (now - timedelta(days=idx // 6)).strftime("%Y-%m-%d %H:%M:%S")
                    raw_payload = {
                        "profile_url": profile_url,
                        "title": "Repost cập nhật cùng một lô đất DX124",
                        "description": "Bán đất nền Tân An đường DX124, giá rõ, diện tích rõ, có ảnh thực tế.",
                        "imgs": [f"https://example.test/image-{token}-{idx}.jpg"],
                    }
                    raw = conn.execute(
                        """
                        INSERT INTO raw_listings (source, source_id, url, raw_json, crawled_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            "facebook",
                            f"fb-broker-{token}-{idx}",
                            f"https://example.test/broker-repost-{token}-{idx}",
                            json.dumps(raw_payload, ensure_ascii=False),
                            crawled_at,
                        ),
                    )
                    listing = conn.execute(
                        """
                        INSERT INTO listings (
                            raw_id, source, source_id, url, title, description, area, ward,
                            property_type, price_ty, price_per_m2, area_m2, probably_sold,
                            is_blacklisted, review_hidden, possibly_duplicate
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
                        """,
                        (
                            raw.lastrowid,
                            "facebook",
                            f"fb-broker-listing-{token}-{idx}",
                            f"https://example.test/broker-listing-{token}-{idx}",
                            "Repost cập nhật cùng một lô đất DX124",
                            "Bán đất nền Tân An đường DX124, giá rõ, diện tích rõ, có ảnh thực tế.",
                            "Tân An",
                            "Tân An",
                            "dat_nen",
                            2.5,
                            25.0,
                            100.0,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO valuation_results (
                            listing_id, fair_ppm2, actual_ppm2, mos_pct, is_signal,
                            source_quality_recheck, source_quality_flags
                        ) VALUES (?, 30, 25, 16, 0, 0, '')
                        """,
                        (listing.lastrowid,),
                    )

            response = self.client.get("/admin/api/facebook-crawl/config")

        self.assertEqual(response.status_code, 200)
        profile = response.get_json()["profiles"][0]
        self.assertEqual(profile["raw_count"], 18)
        self.assertGreaterEqual(profile["activity"]["recommended_daily_limit"], 12)
        self.assertEqual(profile["activity"]["posts_7d"], 18)
        self.assertGreaterEqual(profile["data_quality"]["score"], 85)
        self.assertEqual(profile["data_quality"]["serious_flag_pct"], 0.0)
        self.assertNotIn("deal", json.dumps(profile["data_quality"], ensure_ascii=False).lower())

    def test_admin_js_renders_crawl_ops_panel(self):
        root = Path(__file__).resolve().parent.parent
        js = (root / "static/js/admin.js").read_text(encoding="utf-8")
        html = (root / "templates/admin_control_room.html").read_text(encoding="utf-8")
        css = (root / "static/css/admin.css").read_text(encoding="utf-8")

        self.assertIn('id="crawlOpsPanel"', html)
        self.assertIn("function renderCrawlOps", js)
        self.assertIn("source_errors", js)
        self.assertIn("lock_blockers", js)
        self.assertIn("schedule.task_name", js)
        self.assertIn("serviceFailed", js)
        self.assertIn("crawl-ops-alert", js)
        self.assertIn("function crawlActivityHtml", js)
        self.assertIn("function crawlQualityHtml", js)
        self.assertIn("recommended_daily_limit", js)
        self.assertIn("function renderApifyTokenShell", js)
        self.assertIn("toggleApifyTokensPanel", js)
        self.assertIn('id="apifyTokenSummary"', html)
        self.assertIn('id="apifyTokenMiniStats"', html)
        self.assertIn('id="apifyTokenBody"', html)
        self.assertIn(".apify-token-head", css)
        self.assertIn(".apify-token-scroll", css)
        self.assertIn("Nhịp đăng", html)
        self.assertIn("Độ sạch", html)
        self.assertIn(".broker-quality", css)
        self.assertIn(".broker-apply-btn", css)
        self.assertIn("Mobile admin shell", css)
        self.assertIn("body.sidebar-collapsed .nav-item > span:last-child", css)
        self.assertIn(".data-table:not(.apify-token-table):not(.crawl-table) td::before", css)
        self.assertIn("function deleteLead", js)
        self.assertIn("/admin/api/leads/${leadId}", js)
        self.assertIn("function deleteUser", js)
        self.assertIn("/admin/api/users/${userId}", js)
        self.assertIn("icon-btn danger", js)
        self.assertIn('data-label="Số Zalo"', js)
        self.assertIn('data-label="Hành động"', js)
        self.assertIn(".crawl-ops-panel", css)
        self.assertIn(".crawl-ops-alert", css)

    def test_admin_icons_use_standard_app_icon_with_admin_badge(self):
        root = Path(__file__).resolve().parent.parent
        manifest = (root / "static/admin.webmanifest").read_text(encoding="utf-8")

        self.assertIn("RadarBDS Admin", manifest)
        self.assertIn("admin-icon-192.png", manifest)
        self.assertIn("admin-icon-512.png", manifest)
        self.assertIn("admin-icon-maskable-512.png", manifest)
        for name in [
            "admin-favicon-16.png",
            "admin-favicon-32.png",
            "admin-apple-touch-icon.png",
            "admin-icon-192.png",
            "admin-icon-512.png",
            "admin-icon-maskable-512.png",
        ]:
            path = root / "static/images" / name
            self.assertTrue(path.exists(), name)
            self.assertGreater(path.stat().st_size, 500, name)

    def test_admin_data_quality_summary_includes_images_tokens_errors_and_suppressed_signals(self):
        import app as app_module
        from db.connection import get_conn

        self._login_as_admin()
        token = uuid.uuid4().hex
        area = f"ops-test-dq-{token[:8]}"
        with get_conn() as conn:
            raw = conn.execute(
                """
                INSERT INTO raw_listings (source, url, raw_json)
                VALUES (?, ?, ?)
                """,
                ("facebook", f"https://example.test/raw-dq-{token}", "{}"),
            )
            suppressed = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, url, title, area, ward, property_type,
                    price_ty, price_per_m2, area_m2, probably_sold,
                    is_blacklisted, review_hidden, possibly_duplicate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
                """,
                (
                    raw.lastrowid,
                    "facebook",
                    f"https://example.test/listing-dq-{token}",
                    "Suppressed quality signal",
                    "Ben Cat",
                    "My Phuoc",
                    "dat_nen",
                    1.2,
                    12.0,
                    100.0,
                ),
            )
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct, is_signal,
                    source_quality_recheck, source_quality_flags
                ) VALUES (?, 18, 12, 33, 1, 1, ?)
                """,
                (suppressed.lastrowid, "parsed_discount_as_price,too_low_absolute_price"),
            )
            conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order, local_path)
                VALUES (?, ?, 0, ?)
                """,
                (suppressed.lastrowid, "https://facebook.example/dq-ok.jpg", "dq-ok.jpg"),
            )
            conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order, local_path)
                VALUES (?, ?, 1, NULL)
                """,
                (suppressed.lastrowid, "https://facebook.example/dq-missing.jpg"),
            )

            raw_low_conf = conn.execute(
                """
                INSERT INTO raw_listings (source, url, raw_json)
                VALUES (?, ?, ?)
                """,
                ("facebook", f"https://example.test/raw-dq-low-conf-{token}", "{}"),
            )
            low_conf = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, url, title, area, ward, property_type,
                    price_ty, price_per_m2, area_m2, probably_sold,
                    is_blacklisted, review_hidden, possibly_duplicate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
                """,
                (
                    raw_low_conf.lastrowid,
                    "facebook",
                    f"https://example.test/listing-dq-low-conf-{token}",
                    "Low confidence but visible signal",
                    "Ben Cat",
                    "My Phuoc",
                    "dat_nen",
                    1.3,
                    13.0,
                    100.0,
                ),
            )
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct, is_signal,
                    source_quality_recheck, source_quality_flags
                ) VALUES (?, 18, 13, 27, 1, 1, ?)
                """,
                (low_conf.lastrowid, "low_segment_confidence"),
            )
            conn.execute(
                """
                INSERT INTO crawl_runs (
                    source, area, n_fetched, n_new, n_updated, n_skipped,
                    status, error_msg, started_at, finished_at
                ) VALUES (?, ?, 0, 0, 0, 0, 'error', ?, ?, ?)
                """,
                (
                    "guland",
                    area,
                    "Cloudflare 403",
                    "2099-02-01T21:00:00",
                    "2099-02-01T21:00:20",
                ),
            )

        with mock.patch.object(app_module, "_apify_tokens_public", return_value=[
            {
                "id": "tok-a",
                "label": "Key A",
                "token_mask": "apify_***1234",
                "active": True,
                "monthly_quota": 100,
                "used_this_month": 88,
                "remaining": 12,
                "month": "2026-06",
                "last_error": "",
            }
        ]), mock.patch.object(app_module, "_daily_crawl_schedule_status", return_value={
            "task_name": "RadarBDS_DailyCrawl",
            "installed": True,
            "state": "Ready",
            "next_run_time": "2099-02-02 21:00:00",
            "last_run_time": "2099-02-01 21:00:00",
            "last_result": "1",
            "run_time": "21:00",
            "task_to_run": "radar.py crawl-daily",
            "error": "",
        }), mock.patch.object(app_module, "_active_radar_lock_blockers", return_value=[]):
            response = self.client.get("/admin/api/data-quality/summary")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertGreaterEqual(data["missing_images"]["missing_image_refs"], 1)
        self.assertGreaterEqual(data["missing_images"]["listings_with_missing_images"], 1)
        self.assertEqual(data["apify_pool"]["active_tokens"], 1)
        self.assertEqual(data["apify_pool"]["total_remaining"], 12)
        self.assertEqual(data["crawl_health"]["source_errors"][0]["source"], "guland")
        self.assertIn("Cloudflare 403", data["crawl_health"]["source_errors"][0]["error_msg"])
        self.assertGreaterEqual(data["suppressed_signals"]["total"], 1)
        flags = {item["flag"]: item["count"] for item in data["suppressed_signals"]["by_flag"]}
        self.assertGreaterEqual(flags["parsed_discount_as_price"], 1)
        self.assertNotIn("low_segment_confidence", flags)

    def test_admin_quality_panel_renders_data_quality_dashboard_shell(self):
        self._login_as_admin()

        response = self.client.get("/admin/data-quality")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="qualityOverview"', html)
        self.assertIn("data-quality-overview", html)
        self.assertNotIn('data-quality-tab="recheck"', html)
        self.assertNotIn('data-quality-tab="extraction_qc"', html)
        self.assertIn('data-quality-tab="source_qc"', html)
        self.assertIn('data-quality-tab="legal_qc"', html)
        self.assertNotIn('id="qualityRecheckGrid"', html)
        self.assertNotIn('id="qualityExtractionQcGrid"', html)

    def test_admin_js_loads_data_quality_summary_for_quality_panel(self):
        root = Path(__file__).resolve().parent.parent
        js = (root / "static/js/admin.js").read_text(encoding="utf-8")
        css = (root / "static/css/admin.css").read_text(encoding="utf-8")

        self.assertIn("/admin/api/data-quality/summary", js)
        self.assertIn("function renderDataQualitySummary", js)
        self.assertIn("loadDataQualitySummary", js)
        self.assertIn("qualityOverview", js)
        self.assertNotIn("qualityExtractionQcGrid", js)
        self.assertNotIn("qualityRecheckGrid", js)
        self.assertNotIn("extraction_audit", js)
        self.assertNotIn("Manual LLM", js)
        self.assertIn(".quality-kpi-grid", css)
        self.assertIn(".quality-detail-grid", css)

    def test_daily_crawl_schedule_status_reads_linux_systemd_timer(self):
        import app as app_module

        def fake_run(cmd, **_kwargs):
            if cmd[:3] == ["systemctl", "show", "radar-bds-crawl.timer"]:
                return mock.Mock(
                    returncode=0,
                    stdout=(
                        "LoadState=loaded\n"
                        "ActiveState=active\n"
                        "SubState=waiting\n"
                        "Unit=radar-bds-crawl.service\n"
                        "NextElapseUSecRealtime=Tue 2026-06-02 21:00:00 +07\n"
                        "LastTriggerUSec=Mon 2026-06-01 21:00:04 +07\n"
                    ),
                    stderr="",
                )
            if cmd[:3] == ["systemctl", "show", "radar-bds-crawl.service"]:
                return mock.Mock(
                    returncode=0,
                    stdout=(
                        "LoadState=loaded\n"
                        "ActiveState=inactive\n"
                        "SubState=dead\n"
                        "Result=success\n"
                        "ExecMainStatus=0\n"
                        "InactiveExitTimestamp=Mon 2026-06-01 21:14:04 +07\n"
                    ),
                    stderr="",
                )
            if cmd[:3] == ["systemctl", "cat", "radar-bds-crawl.timer"]:
                return mock.Mock(
                    returncode=0,
                    stdout="[Timer]\nOnCalendar=*-*-* 21:00:00\n",
                    stderr="",
                )
            raise AssertionError(cmd)

        with mock.patch.object(app_module.platform, "system", return_value="Linux"), \
             mock.patch.object(app_module.subprocess, "run", side_effect=fake_run):
            status = app_module._daily_crawl_schedule_status()

        self.assertTrue(status["installed"])
        self.assertEqual(status["task_name"], "radar-bds-crawl.timer")
        self.assertEqual(status["state"], "active/waiting")
        self.assertEqual(status["run_time"], "21:00")
        self.assertEqual(status["next_run_time"], "Tue 2026-06-02 21:00:00 +07")
        self.assertEqual(status["last_run_time"], "Mon 2026-06-01 21:00:04 +07")
        self.assertEqual(status["task_to_run"], "radar-bds-crawl.service")
        self.assertFalse(status["service_failed"])

    def test_daily_crawl_schedule_status_exposes_linux_service_failure(self):
        import app as app_module

        def fake_run(cmd, **_kwargs):
            if cmd[:3] == ["systemctl", "show", "radar-bds-crawl.timer"]:
                return mock.Mock(
                    returncode=0,
                    stdout=(
                        "LoadState=loaded\n"
                        "ActiveState=active\n"
                        "SubState=waiting\n"
                        "Unit=radar-bds-crawl.service\n"
                        "NextElapseUSecRealtime=Wed 2026-06-03 21:00:00 +07\n"
                        "LastTriggerUSec=Tue 2026-06-02 21:03:25 +07\n"
                    ),
                    stderr="",
                )
            if cmd[:3] == ["systemctl", "show", "radar-bds-crawl.service"]:
                return mock.Mock(
                    returncode=0,
                    stdout=(
                        "LoadState=loaded\n"
                        "ActiveState=failed\n"
                        "SubState=failed\n"
                        "Result=exit-code\n"
                        "ExecMainStatus=1\n"
                        "InactiveExitTimestamp=Tue 2026-06-02 21:03:25 +07\n"
                    ),
                    stderr="",
                )
            if cmd[:3] == ["systemctl", "cat", "radar-bds-crawl.timer"]:
                return mock.Mock(
                    returncode=0,
                    stdout="[Timer]\nOnCalendar=*-*-* 21:00:00\n",
                    stderr="",
                )
            raise AssertionError(cmd)

        with mock.patch.object(app_module.platform, "system", return_value="Linux"), \
             mock.patch.object(app_module.subprocess, "run", side_effect=fake_run):
            status = app_module._daily_crawl_schedule_status()

        self.assertTrue(status["installed"])
        self.assertTrue(status["service_failed"])
        self.assertEqual(status["service_state"], "failed/failed")
        self.assertEqual(status["service_result"], "exit-code")
        self.assertEqual(status["service_exit_code"], "1")
        self.assertIn("logs/crawl-daily.log", status["service_log_hint"])

    def test_admin_crawl_reprocesses_only_refreshed_raw_ids(self):
        import app as app_module
        import cli.crawlers as crawlers
        import cleansing.reprocess as reprocess
        import db.connection as connection

        @contextmanager
        def fake_lock(_name):
            yield

        job_id = f"job-{uuid.uuid4().hex}"
        with app_module.FACEBOOK_CRAWL_LOCK:
            app_module.FACEBOOK_CRAWL_JOBS[job_id] = {
                "id": job_id,
                "status": "queued",
                "stage": "queued",
                "mode": "daily",
                "profile_url": "https://www.facebook.com/nhadatkhanhmy",
                "broker_name": "Duy Khánh bds",
                "city": "Thủ Dầu Một",
                "limit": 30,
                "days": 7,
                "download_images": False,
                "stats": {},
                "logs": [],
            }
            app_module.FACEBOOK_CRAWL_JOB_ORDER.append(job_id)

        calls = {}

        def fake_crawl_to_raw(**_kwargs):
            return {
                "fetched": 12,
                "inserted": 0,
                "skipped": 0,
                "irrelevant": 0,
                "out_of_area": 0,
                "range_filtered": 0,
                "refreshed_images": 12,
                "refreshed_raw_ids": [101, 102, 103],
            }

        def fake_reprocess(**kwargs):
            calls.update(kwargs)
            return {"listings": {"processed_ids": [1, 2, 3]}, "valuation": {"total": 3}}

        with mock.patch.object(connection, "advisory_lock", fake_lock), \
             mock.patch.object(crawlers, "_facebook_crawl_to_raw", side_effect=fake_crawl_to_raw), \
             mock.patch.object(reprocess, "run_full_reprocess", side_effect=fake_reprocess):
            app_module._run_admin_facebook_crawl_job(job_id)

        self.assertEqual(calls.get("source"), "facebook")
        self.assertEqual(calls.get("raw_ids"), [101, 102, 103])
        self.assertFalse(calls.get("full", False))
        self.assertEqual(app_module.FACEBOOK_CRAWL_JOBS[job_id]["status"], "succeeded")
        logs = "\n".join(app_module.FACEBOOK_CRAWL_JOBS[job_id]["logs"])
        self.assertIn("fetched=12", logs)
        self.assertIn("skipped=0", logs)
        self.assertIn("Reprocess xong: processed=3, new=0, updated=0, skipped=0", logs)


class PublicAuthHeaderAssetTest(unittest.TestCase):
    def test_public_auth_header_mobile_css_keeps_labels_readable(self):
        css = Path("static/css/main/leads_chat.css").read_text(encoding="utf-8")

        self.assertNotIn(".user-menu-trigger span:not(.user-avatar)", css)
        self.assertNotIn("max-width: 82px", css)
        self.assertIn(".header .user-menu-label", css)
        self.assertIn("line-height: 1.2", css)

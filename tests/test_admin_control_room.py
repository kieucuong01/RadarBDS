import shutil
import sys
import tempfile
import unittest
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

        connection.close_all()
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _login_as_admin(self):
        from auth.core import SESSION_COOKIE_NAME
        from db.connection import get_conn

        token = "admin-control-room-token"
        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (identifier, identifier_type, password_hash, tier)
                VALUES ('admin@example.test', 'email', 'hash', 'admin')
                """
            )
            conn.execute(
                """
                INSERT INTO user_sessions (token, user_id, expires_at)
                VALUES (?, ?, '2099-01-01T00:00:00')
                """,
                (token, cur.lastrowid),
            )
        try:
            self.client.set_cookie(SESSION_COOKIE_NAME, token)
        except TypeError:
            self.client.set_cookie("localhost", SESSION_COOKIE_NAME, token)

    def test_guest_control_room_renders_login_modal_gate(self):
        response = self.client.get("/admin/control-room")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="authModal"', html)
        self.assertIn("Đăng nhập admin", html)
        self.assertIn("js/auth.js", html)
        self.assertNotIn("js/admin.js", html)

    def test_guest_admin_api_still_requires_admin(self):
        response = self.client.get("/admin/api/users")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "admin_required")

    def test_admin_session_loads_control_room_workspace(self):
        self._login_as_admin()

        response = self.client.get("/admin/control-room")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("js/admin.js", html)
        self.assertNotIn('id="authModal"', html)

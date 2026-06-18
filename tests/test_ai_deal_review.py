import io
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class AiDealReviewTest(unittest.TestCase):
    def setUp(self):
        from db import connection
        from db.schema import init_schema

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "radar_ai_review.db"
        self.token = uuid.uuid4().hex
        self.url_prefix = f"https://ai-review-{self.token}.test"
        self.ward = f"AIReviewWard{self.token[:8]}"
        self.listing_ids = []
        self.user_ids = []
        connection.close_all()
        self.db_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        init_schema()
        self._delete_test_rows()

    def tearDown(self):
        from db import connection

        self._delete_test_rows()
        connection.close_all()
        self.db_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ---- helpers -------------------------------------------------------
    def _url(self, url: str) -> str:
        if url.startswith("https://t.test/"):
            return f"{self.url_prefix}/{url.rsplit('/', 1)[-1]}"
        return f"{self.url_prefix}/{len(self.listing_ids) + 1}"

    def _delete_test_rows(self):
        from db.connection import get_conn

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id FROM listings WHERE url LIKE ?",
                (f"{self.url_prefix}%",),
            ).fetchall()
            ids = {r["id"] for r in rows}
            ids.update(self.listing_ids)
            if ids:
                placeholders = ",".join("?" * len(ids))
                params = list(ids)
                conn.execute(f"DELETE FROM ai_deal_review WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM ai_training_feedback WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM valuation_results WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM price_history WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM listing_images WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM legal_verifications WHERE listing_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM listings WHERE id IN ({placeholders})", params)
            user_rows = conn.execute(
                "SELECT id FROM users WHERE identifier LIKE ?",
                (f"%{self.token}%",),
            ).fetchall()
            user_ids = {r["id"] for r in user_rows}
            user_ids.update(self.user_ids)
            if user_ids:
                placeholders = ",".join("?" * len(user_ids))
                params = list(user_ids)
                conn.execute(f"DELETE FROM user_sessions WHERE user_id IN ({placeholders})", params)
                conn.execute(f"DELETE FROM users WHERE id IN ({placeholders})", params)

    def _insert_signal(self, *, url, ward=None, price_ty=2.0,
                       area_m2=80.0, signal_score=70, mos_pct=35.0):
        from db.connection import get_conn

        with get_conn() as conn:
            lid = conn.execute(
                """
                INSERT INTO listings (source, url, title, ward, property_type,
                    price_ty, area_m2, road_tier, has_so, crawled_at)
                VALUES ('guland', ?, 'Tin test', ?, 'dat_nen',
                        ?, ?, 1, 1, '2026-05-01T00:00:00')
                """,
                (self._url(url), ward or self.ward, price_ty, area_m2),
            ).lastrowid
            self.listing_ids.append(lid)
            conn.execute(
                """
                INSERT INTO valuation_results (listing_id, fair_ppm2,
                    actual_ppm2, mos_pct, is_signal, signal_score, n_segment)
                VALUES (?, 30.0, 20.0, ?, 1, ?, 25)
                """,
                (lid, mos_pct, signal_score),
            )
            return lid

    def _save_args(self, **kw):
        base = dict(id=None, verdict=None, confidence=None, reasoning=None,
                    red_flags=None, needs_map_check=False, memo_file=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def _run_save(self, **kw):
        from cli.review import cmd_review_save

        return cmd_review_save(self._save_args(**kw))

    def _run_queue(self, top=5, ward=None):
        from cli.review import cmd_review_queue

        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_review_queue(SimpleNamespace(top=top, ward=ward or self.ward))
        return json.loads(buf.getvalue())

    def _count(self, table):
        from db.connection import get_conn

        with get_conn() as conn:
            if table in ("ai_deal_review", "ai_training_feedback") and self.listing_ids:
                placeholders = ",".join("?" * len(self.listing_ids))
                return conn.execute(
                    f"SELECT COUNT(*) c FROM {table} WHERE listing_id IN ({placeholders})",
                    list(self.listing_ids),
                ).fetchone()["c"]
            return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]

    # ---- 1. idempotent schema -----------------------------------------
    def test_schema_idempotent(self):
        from db.connection import get_conn
        from db.schema import init_schema

        init_schema()  # second call must not raise
        with get_conn() as conn:
            row = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'ai_deal_review'"
            ).fetchone()
            self.assertIsNotNone(row)
            col = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'ai_deal_review' "
                "AND column_name = 'memo_markdown'"
            ).fetchone()
            self.assertIsNotNone(col)

    def test_schema_normalizes_legacy_positive_training_labels(self):
        from db.connection import get_conn
        from db.schema import init_schema

        correct_lid = self._insert_signal(url="https://t.test/legacy-correct")
        good_lid = self._insert_signal(url="https://t.test/legacy-good")

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO ai_training_feedback (
                    listing_id, actor, verdict, extraction_verdict,
                    valuation_verdict
                )
                VALUES (?, 'admin', 'correct', 'all_correct', 'correct')
                """,
                (correct_lid,),
            )
            conn.execute(
                """
                INSERT INTO ai_training_feedback (
                    listing_id, actor, verdict, extraction_verdict,
                    valuation_verdict
                )
                VALUES (?, 'admin', 'good', 'all_correct', 'good')
                """,
                (good_lid,),
            )

        init_schema()

        with get_conn() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT listing_id, verdict, valuation_verdict
                    FROM ai_training_feedback
                    WHERE listing_id IN (?, ?)
                    ORDER BY listing_id
                    """,
                    (correct_lid, good_lid),
                ).fetchall()
            ]

        self.assertEqual(
            rows,
            [
                {
                    "listing_id": correct_lid,
                    "verdict": "cheap_real",
                    "valuation_verdict": "cheap_real",
                },
                {
                    "listing_id": good_lid,
                    "verdict": "cheap_real",
                    "valuation_verdict": "cheap_real",
                },
            ],
        )

    # ---- 2. review-save validation ------------------------------------
    def test_review_save_insert_and_validation(self):
        lid = self._insert_signal(url="https://t.test/1")
        self._run_save(id=lid, verdict="suspect", confidence=0.7,
                       reasoning="nghi má»“i", red_flags="má»“i;giÃ¡ áº£o",
                       needs_map_check=True)
        from db.connection import get_conn

        with get_conn() as conn:
            r = conn.execute(
                "SELECT * FROM ai_deal_review WHERE listing_id=?", (lid,)
            ).fetchone()
        self.assertEqual(r["verdict"], "suspect")
        self.assertEqual(r["needs_map_check"], 1)
        self.assertEqual(json.loads(r["red_flags"]), ["má»“i", "giÃ¡ áº£o"])
        self.assertEqual(r["model"], "claude-code-interactive")

        with self.assertRaises(SystemExit):
            self._run_save(id=lid, verdict="bogus", reasoning="x")
        with self.assertRaises(SystemExit):
            self._run_save(id=lid, verdict="cheap_real",
                           confidence=1.5, reasoning="x")

    def test_review_save_accepts_memo_file_without_truncating(self):
        lid = self._insert_signal(url="https://t.test/memo-file")
        memo_path = self.tmpdir / "memo.md"
        long_memo = "# Investment Memo\n\n" + ("Chi tiáº¿t cá»‘ váº¥n riÃªng cho deal nÃ y.\n" * 120)
        memo_path.write_text(long_memo, encoding="utf-8")

        self._run_save(
            id=lid,
            verdict="cheap_real",
            confidence=0.82,
            reasoning="ráº» tháº­t, cáº§n xÃ¡c minh phÃ¡p lÃ½",
            memo_file=str(memo_path),
        )

        from db.connection import get_conn

        with get_conn() as conn:
            r = conn.execute(
                "SELECT reasoning, memo_markdown FROM ai_deal_review WHERE listing_id=?",
                (lid,),
            ).fetchone()

        self.assertEqual(r["reasoning"], "ráº» tháº­t, cáº§n xÃ¡c minh phÃ¡p lÃ½")
        self.assertEqual(r["memo_markdown"], long_memo)
        self.assertGreater(len(r["memo_markdown"]), 2000)

    # ---- 3. review-queue excludes rows with saved memo -----------------
    def test_review_queue_excludes_rows_with_memo_but_keeps_unmemoed_reviews(self):
        a = self._insert_signal(url="https://t.test/a")
        b = self._insert_signal(url="https://t.test/b")
        c = self._insert_signal(url="https://t.test/c")
        out = self._run_queue()
        self.assertEqual(out["count"], 3)

        self._run_save(id=a, verdict="cheap_real", confidence=0.8,
                       reasoning="ráº» tháº­t")
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO ai_deal_review (
                    listing_id, actor, verdict, confidence, reasoning,
                    memo_markdown, model, updated_at
                )
                VALUES (?, 'claude', 'cheap_real', 0.8, 'rule-based',
                        '# Memo rule-based', 'claude-code-advisory-opinion-v3',
                        datetime('now'))
                """,
                (b,),
            )
            conn.execute(
                """
                INSERT INTO ai_deal_review (
                    listing_id, actor, verdict, confidence, reasoning,
                    memo_markdown, model, updated_at
                )
                VALUES (?, 'claude', 'cheap_real', 0.8, 'old template',
                        '# Investment Memo Cá»‘ Váº¥n\n\n## Verdict\nold',
                        'claude-code-interactive', datetime('now'))
                """,
                (b,),
            )
        memo_path = self.tmpdir / "review-c.md"
        memo_path.write_text("Memo cá»‘ váº¥n Ä‘Ã£ viáº¿t cho deal C.", encoding="utf-8")
        self._run_save(id=c, verdict="suspect", confidence=0.6,
                       reasoning="cáº§n kiá»ƒm tra", memo_file=str(memo_path))

        out2 = self._run_queue()
        shown = {item["listing_id"] for item in out2["items"]}
        self.assertEqual(shown, {a, b})
        item = next(item for item in out2["items"] if item["listing_id"] == b)
        self.assertIn("context", item)
        self.assertNotIn("memo", item)
        self.assertIn("valuation", item["context"])
        self.assertIn("listing", item["context"])

    def test_review_queue_includes_data_backed_memo_dossier(self):
        lid = self._insert_signal(
            url="https://t.test/dossier",
            price_ty=2.0,
            area_m2=100.0,
            signal_score=72,
            mos_pct=40.0,
        )
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                   SET title='Lo dat 5x20 co nha cho thue',
                       description='Nha dang cho thue 6 trieu/thang, hem xe hoi.',
                       price_per_m2=20.0,
                       frontage_m=5.0,
                       depth_m=20.0,
                       road_type='hem_xe_hoi',
                       tho_cu_m2=60.0,
                       tho_cu_ratio=0.6,
                       price_dropped=1,
                       price_drop_pct=12.5,
                       price_first_ty=2.3,
                       is_hot=1
                 WHERE id=?
                """,
                (lid,),
            )
            conn.execute(
                """
                UPDATE valuation_results
                   SET fair_ppm2=33.0,
                       actual_ppm2=20.0,
                       n_segment=18,
                       segment='AIReviewWard/dat_nen/hem_xe_hoi',
                       source_quality_flags='low_segment_confidence',
                       source_quality_recheck=1,
                       legal_status='unverified',
                       trust_tier='candidate_signal',
                       trust_score=42,
                       legal_flags='legal_unverified'
                 WHERE listing_id=?
                """,
                (lid,),
            )
            conn.execute(
                """
                INSERT INTO price_history (listing_id, price_ty, price_per_m2, recorded_at)
                VALUES (?, 2.3, 23.0, '2026-05-01T00:00:00')
                """,
                (lid,),
            )
            conn.execute(
                """
                INSERT INTO price_history (listing_id, price_ty, price_per_m2, recorded_at)
                VALUES (?, 2.0, 20.0, '2026-05-03T00:00:00')
                """,
                (lid,),
            )

        out = self._run_queue(top=1)
        item = out["items"][0]
        dossier = item["context"]["memo_dossier"]

        self.assertEqual(dossier["valuation_principles"]["primary_method"], "so_sanh_thi_truong")
        self.assertIn("dong_tien_khi_co_khai_thac", dossier["valuation_principles"]["secondary_checks"])
        self.assertIn("gia_tri_su_dung_tot_nhat", dossier["valuation_principles"]["secondary_checks"])
        self.assertEqual(dossier["price"]["asking_price_ty"], 2.0)
        self.assertEqual(dossier["price"]["asking_ppm2"], 20.0)
        self.assertEqual(dossier["price"]["reference_ppm2"], 33.0)
        self.assertEqual(dossier["price"]["reference_total_ty"], 3.3)
        self.assertEqual(dossier["asset"]["frontage_m"], 5.0)
        self.assertEqual(dossier["asset"]["depth_m"], 20.0)
        self.assertIn("cho thue", dossier["asset"]["use_case_hints"])
        self.assertEqual(dossier["market"]["sample_size"], 18)
        self.assertEqual(dossier["market"]["sample_confidence"], "mong")
        self.assertIn("low_segment_confidence", dossier["risks"]["flags"])
        self.assertIn("phap_ly_chua_xac_minh", dossier["risks"]["verification_focus"])
        self.assertIn("gia_nen_di_xem_ty", dossier["action_pricing"])
        self.assertIn("gia_nen_tra_khi_con_rui_ro_ty", dossier["action_pricing"])
        self.assertGreaterEqual(len(dossier["action_pricing"]["due_diligence_questions"]), 3)

    def test_listing_memo_api_is_login_only_and_returns_pending_or_latest_memo(self):
        import app as app_module

        lid = self._insert_signal(url="https://t.test/api-memo")

        with mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path):
            guest_client = app_module.app.test_client()

            guest = guest_client.get(f"/api/listing/{lid}/memo")
            self.assertEqual(guest.status_code, 403)
            self.assertEqual(guest.get_json()["reason"], "login_required")

            free_client = app_module.app.test_client()
            self._login_tier(free_client, "free")
            free = free_client.get(f"/api/listing/{lid}/memo")
            self.assertEqual(free.status_code, 200)
            self.assertTrue(free.get_json()["pending"])

            client = app_module.app.test_client()
            self._login_tier(client, "vip")
            pending = client.get(f"/api/listing/{lid}/memo")
            self.assertEqual(pending.status_code, 200)
            self.assertTrue(pending.get_json()["pending"])

            from db.connection import get_conn

            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO ai_deal_review (
                        listing_id, actor, verdict, confidence, reasoning,
                        memo_markdown, model, updated_at
                    )
                    VALUES (?, 'claude', 'cheap_real', 0.8, 'rule-based',
                            '# Memo rule-based', 'claude-code-advisory-opinion-v3',
                            datetime('now'))
                    """,
                    (lid,),
                )
                conn.execute(
                    """
                    INSERT INTO ai_deal_review (
                        listing_id, actor, verdict, confidence, reasoning,
                        memo_markdown, model, updated_at
                    )
                    VALUES (?, 'claude', 'cheap_real', 0.8, 'old template',
                            '# Investment Memo Cá»‘ Váº¥n\n\n## Verdict\nold',
                            'claude-code-interactive', datetime('now'))
                    """,
                    (lid,),
                )
            generated_only = client.get(f"/api/listing/{lid}/memo")
            self.assertEqual(generated_only.status_code, 200)
            self.assertTrue(generated_only.get_json()["pending"])

            memo_path = self.tmpdir / "api-memo.md"
            memo_text = "# Memo cá»‘ váº¥n\n\nDeal nÃ y ráº» nhÆ°ng cáº§n kiá»ƒm tra Ä‘Æ°á»ng vÃ o."
            memo_path.write_text(memo_text, encoding="utf-8")
            self._run_save(id=lid, verdict="cheap_real", confidence=0.9,
                           reasoning="ráº» tháº­t", memo_file=str(memo_path))

            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO ai_deal_review (
                        listing_id, actor, verdict, confidence, reasoning,
                        memo_markdown, model, updated_at
                    )
                    VALUES (?, 'claude', 'not_cheap', 0.4, 'rule-based later',
                            '# Memo rule-based later', 'claude-code-advisory-specific-v2',
                            datetime('now'))
                    """,
                    (lid,),
                )

            full = free_client.get(f"/api/listing/{lid}/memo")
            data = full.get_json()
            self.assertEqual(full.status_code, 200)
            self.assertFalse(data["pending"])
            self.assertEqual(data["memo_markdown"], memo_text)
            self.assertEqual(data["verdict"], "cheap_real")
            self.assertEqual(data["tier"], "free")
            self.assertNotIn("admin_valuation_workflow_markdown", data)

            admin_client = app_module.app.test_client()
            self._login_tier(admin_client, "admin")
            admin_full = admin_client.get(f"/api/listing/{lid}/memo")
            admin_data = admin_full.get_json()
            self.assertEqual(admin_full.status_code, 200)
            self.assertEqual(admin_data["tier"], "admin")
            self.assertIn("admin_valuation_workflow_markdown", admin_data)
            self.assertIn("analytics/valuation.py", admin_data["admin_valuation_workflow_markdown"])
            self.assertIn("valuation_results", admin_data["admin_valuation_workflow_markdown"])
            self.assertIn("so sánh thị trường là trục chính", admin_data["admin_valuation_workflow_markdown"])
            self.assertIn("dòng tiền", admin_data["admin_valuation_workflow_markdown"])
            self.assertIn("giá trị sử dụng tốt nhất", admin_data["admin_valuation_workflow_markdown"])
            self.assertIn("mức giá hành động", admin_data["admin_valuation_workflow_markdown"])

    def test_review_queue_uses_latest_actionable_valuation_only(self):
        from db.connection import get_conn

        stale_signal = self._insert_signal(url="https://t.test/stale-signal")
        flagged_signal = self._insert_signal(url="https://t.test/flagged-signal")
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO valuation_results (listing_id, fair_ppm2,
                    actual_ppm2, mos_pct, is_signal, signal_score, n_segment)
                VALUES (?, 20.0, 25.0, -25.0, 0, 0, 25)
                """,
                (stale_signal,),
            )
            conn.execute(
                """
                UPDATE valuation_results
                   SET source_quality_recheck=1,
                       source_quality_flags='parsed_discount_as_price'
                 WHERE listing_id=?
                """,
                (flagged_signal,),
            )

        out = self._run_queue(top=10)
        shown = {item["listing_id"] for item in out["items"]}

        self.assertNotIn(stale_signal, shown)
        self.assertNotIn(flagged_signal, shown)

    def test_review_queue_skips_duplicate_actionable_reposts(self):
        from db.connection import get_conn

        canonical = self._insert_signal(url="https://t.test/review-canonical")
        duplicate = self._insert_signal(url="https://t.test/review-duplicate")
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                   SET possibly_duplicate=1,
                       duplicate_of_id=?
                 WHERE id=?
                """,
                (canonical, duplicate),
            )

        out = self._run_queue(top=10)
        shown = [item["listing_id"] for item in out["items"]]

        self.assertIn(canonical, shown)
        self.assertNotIn(duplicate, shown)

    # ---- 4. disagreement strict mapping -------------------------------
    def test_disagreement_strict(self):
        import app as app_module

        with mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path):
            client = app_module.app.test_client()
            self._login_admin(client)

            cases = [
                ("correct", "suspect", True),
                ("maybe", "cheap_real", False),
                ("good", "cheap_real", False),
                ("bad", "cheap_real", True),
            ]
            ids = {}
            for human, ai, expected in cases:
                lid = self._insert_signal(url=f"https://t.test/d-{human}-{ai}")
                ids[lid] = (human, ai, expected)
                self._insert_human_label(lid, human)
                self._run_save(id=lid, verdict=ai, confidence=0.6,
                               reasoning="r")

            resp = client.get("/admin/api/ai-training/disagreements")
            self.assertEqual(resp.status_code, 200)
            shown = {it["id"] for it in resp.get_json()["items"]}
            for lid, (human, ai, expected) in ids.items():
                self.assertEqual(lid in shown, expected,
                                 f"{human}+{ai} expected shown={expected}")

    # ---- 5. anti-bias separation --------------------------------------
    def test_anti_bias_separation(self):
        import app as app_module

        lid = self._insert_signal(url="https://t.test/ab")
        # human label must NOT create ai_deal_review
        self._insert_human_label(lid, "bad", via_app=app_module)
        self.assertEqual(self._count("ai_deal_review"), 0)

        from db.connection import get_conn

        with get_conn() as conn:
            hidden_before = conn.execute(
                "SELECT COALESCE(review_hidden,0) h FROM listings WHERE id=?",
                (lid,),
            ).fetchone()["h"]

        # review-save must NOT touch ai_training_feedback / review_hidden
        before_fb = self._count("ai_training_feedback")
        self._run_save(id=lid, verdict="cheap_real", confidence=0.9,
                       reasoning="ráº» tháº­t")
        self.assertEqual(self._count("ai_training_feedback"), before_fb)
        with get_conn() as conn:
            hidden_after = conn.execute(
                "SELECT COALESCE(review_hidden,0) h FROM listings WHERE id=?",
                (lid,),
            ).fetchone()["h"]
        self.assertEqual(hidden_before, hidden_after)

    # ---- 6. human training labels split extraction vs valuation --------
    def test_ai_training_feedback_separates_extraction_and_valuation_labels(self):
        import app as app_module
        from db.connection import get_conn

        cheap_lid = self._insert_signal(url="https://t.test/cheap-real")
        bad_lid = self._insert_signal(url="https://t.test/bad-data")
        fair_lid = self._insert_signal(url="https://t.test/fair")
        fake_lid = self._insert_signal(url="https://t.test/fake-price-hard")

        with app_module.app.test_request_context():
            with get_conn() as conn:
                cheap = app_module._save_ai_training_feedback(
                    conn,
                    cheap_lid,
                    {
                        "extraction_verdict": "all_correct",
                        "valuation_verdict": "cheap_real",
                    },
                )
                bad = app_module._save_ai_training_feedback(
                    conn,
                    bad_lid,
                    {
                        "extraction_verdict": "wrong_area",
                        "valuation_verdict": "cannot_price",
                        "reason_tags": ["wrong_area"],
                    },
                )
                fair = app_module._save_ai_training_feedback(
                    conn,
                    fair_lid,
                    {
                        "extraction_verdict": "all_correct",
                        "valuation_verdict": "fair",
                    },
                )
                fake = app_module._save_ai_training_feedback(
                    conn,
                    fake_lid,
                    {
                        "extraction_verdict": "wrong_price",
                        "valuation_verdict": "fake_price",
                        "reason_tags": ["fake_price"],
                    },
                )

        self.assertEqual(cheap["verdict"], "cheap_real")
        self.assertEqual(bad["verdict"], "bad_data")
        self.assertEqual(fair["verdict"], "fair")
        self.assertEqual(fake["verdict"], "fake_price")

        with get_conn() as conn:
            rows = {
                r["listing_id"]: dict(r)
                for r in conn.execute(
                    """
                    SELECT f.listing_id, f.verdict, f.extraction_verdict,
                           f.valuation_verdict, COALESCE(l.review_hidden,0) hidden,
                           l.review_hidden_reason
                    FROM ai_training_feedback f
                    JOIN listings l ON l.id = f.listing_id
                    WHERE f.listing_id IN (?, ?, ?, ?)
                    """,
                    (cheap_lid, bad_lid, fair_lid, fake_lid),
                ).fetchall()
            }

        self.assertEqual(rows[cheap_lid]["extraction_verdict"], "all_correct")
        self.assertEqual(rows[cheap_lid]["valuation_verdict"], "cheap_real")
        self.assertEqual(rows[cheap_lid]["hidden"], 0)

        self.assertEqual(rows[bad_lid]["verdict"], "bad_data")
        self.assertEqual(rows[bad_lid]["valuation_verdict"], "cannot_price")
        self.assertEqual(rows[bad_lid]["hidden"], 1)
        self.assertEqual(rows[bad_lid]["review_hidden_reason"], "bad_data")

        self.assertEqual(rows[fair_lid]["verdict"], "fair")
        self.assertEqual(rows[fair_lid]["valuation_verdict"], "fair")
        self.assertEqual(rows[fair_lid]["hidden"], 1)
        self.assertEqual(rows[fair_lid]["review_hidden_reason"], "fair")

        self.assertEqual(rows[fake_lid]["verdict"], "fake_price")
        self.assertEqual(rows[fake_lid]["valuation_verdict"], "fake_price")
        self.assertEqual(rows[fake_lid]["hidden"], 1)
        self.assertEqual(rows[fake_lid]["review_hidden_reason"], "fake_price")

    def test_data_quality_recheck_queue_shows_hidden_bad_data_signals_only(self):
        import app as app_module
        from db.connection import get_conn

        bad_lid = self._insert_signal(url="https://t.test/recheck-bad-data")
        fake_lid = self._insert_signal(url="https://t.test/recheck-fake-price")

        with app_module.app.test_request_context():
            with get_conn() as conn:
                app_module._save_ai_training_feedback(
                    conn,
                    bad_lid,
                    {
                        "extraction_verdict": "wrong_price",
                        "valuation_verdict": "cannot_price",
                        "reason_tags": ["wrong_price"],
                    },
                )
                app_module._save_ai_training_feedback(
                    conn,
                    fake_lid,
                    {
                        "extraction_verdict": "all_correct",
                        "valuation_verdict": "fake_price",
                        "reason_tags": ["fake_price"],
                    },
                )

        with mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path):
            client = app_module.app.test_client()
            self._login_admin(client)

            normal = client.get(f"/admin/api/ai-training/items?ward={self.ward}")
            self.assertEqual(normal.status_code, 200)
            normal_ids = {it["id"] for it in normal.get_json()["items"]}
            self.assertNotIn(bad_lid, normal_ids)
            self.assertNotIn(fake_lid, normal_ids)

            recheck = client.get(f"/admin/api/data-quality/items?queue=recheck&ward={self.ward}")
            self.assertEqual(recheck.status_code, 200)
            data = recheck.get_json()
            self.assertEqual(data["queue"], "source_qc")
            self.assertNotIn(bad_lid, {it["id"] for it in data["items"]})
            self.assertNotIn(fake_lid, {it["id"] for it in data["items"]})

    def test_data_quality_source_qc_queue_shows_suppressed_guland_quality_items(self):
        import app as app_module
        from db.connection import get_conn

        lid = self._insert_signal(url="https://t.test/source-qc-old-guland")
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE valuation_results
                   SET is_signal=0,
                       signal_score=0,
                       source_quality_recheck=1,
                       source_quality_flags='old_guland_post'
                 WHERE listing_id=?
                """,
                (lid,),
            )

        with mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path):
            client = app_module.app.test_client()
            self._login_admin(client)

            normal = client.get(f"/admin/api/ai-training/items?ward={self.ward}")
            self.assertEqual(normal.status_code, 200)
            self.assertNotIn(lid, {it["id"] for it in normal.get_json()["items"]})

            source_qc = client.get(f"/admin/api/data-quality/items?queue=source_qc&ward={self.ward}")
            self.assertEqual(source_qc.status_code, 200)
            data = source_qc.get_json()
            self.assertEqual(data["queue"], "source_qc")
            self.assertIn(lid, {it["id"] for it in data["items"]})
            item = next(it for it in data["items"] if it["id"] == lid)
            self.assertTrue(item["is_source_qc"])
            self.assertEqual(item["source_quality_flags"], "old_guland_post")

    def test_data_quality_extraction_qc_queue_falls_back_to_source_qc(self):
        import app as app_module
        from db.connection import get_conn

        lid = self._insert_signal(url="https://t.test/extraction-qc-price")
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE listings
                   SET source='facebook',
                       title='Giam 400 trieu gia 4,2 ty chi con 3,8 ty',
                       description='Ban nha Phu Loi, dien tich 100m2, gia con 3,8 ty',
                       price_ty=4.2,
                       area_m2=100,
                       ward='PhÃº Lá»£i',
                       property_type='nha_dat',
                       road_tier=3
                 WHERE id=?
                """,
                (lid,),
            )

        with mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path):
            client = app_module.app.test_client()
            self._login_admin(client)

            resp = client.get("/admin/api/data-quality/items?queue=extraction_qc&limit=200")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["queue"], "source_qc")
            self.assertNotIn(lid, {it["id"] for it in data["items"]})


    def test_ai_training_ignores_legacy_qc_queue_params(self):
        import app as app_module
        from db.connection import get_conn

        source_qc_lid = self._insert_signal(url="https://t.test/source-qc-not-training")

        with get_conn() as conn:
            conn.execute(
                """
                UPDATE valuation_results
                   SET is_signal=0,
                       signal_score=0,
                       source_quality_recheck=1,
                       source_quality_flags='old_guland_post'
                 WHERE listing_id=?
                """,
                (source_qc_lid,),
            )

        with mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path):
            client = app_module.app.test_client()
            self._login_admin(client)

            for queue in ("recheck", "source_qc", "legal_qc", "needs_valuation"):
                resp = client.get(
                    f"/admin/api/ai-training/items?queue={queue}&ward={self.ward}"
                )
                self.assertEqual(resp.status_code, 200)
                data = resp.get_json()
                self.assertEqual(data["queue"], "main")
                self.assertNotIn(source_qc_lid, {it["id"] for it in data["items"]})

    def test_data_quality_legal_qc_excludes_effective_has_document_status(self):
        import app as app_module
        from db.connection import get_conn

        lid = self._insert_signal(url="https://t.test/legal-has-document")

        with get_conn() as conn:
            conn.execute(
                """
                UPDATE valuation_results
                   SET legal_status='has_document',
                       trust_tier='has_legal_doc',
                       trust_score=80
                 WHERE listing_id=?
                """,
                (lid,),
            )
            conn.execute(
                """
                INSERT INTO legal_verifications (
                    listing_id, status, trust_tier, confidence_score
                )
                VALUES (?, 'unverified', 'candidate_signal', 0)
                """,
                (lid,),
            )

        with mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path):
            client = app_module.app.test_client()
            self._login_admin(client)

            resp = client.get(f"/admin/api/data-quality/items?queue=legal_qc&ward={self.ward}")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["queue"], "legal_qc")
            self.assertNotIn(lid, {it["id"] for it in data["items"]})

    def test_ai_training_feedback_endpoint_rejects_extraction_qc_labels(self):
        import app as app_module

        lid = self._insert_signal(url="https://t.test/reject-extraction-qc")

        with mock.patch.object(app_module.db_mod, "DB_PATH", self.db_path):
            client = app_module.app.test_client()
            self._login_admin(client)

            resp = client.post(
                "/admin/api/ai-training/feedback",
                json={
                    "listing_id": lid,
                    "extraction_verdict": "wrong_area",
                    "valuation_verdict": "cannot_price",
                    "reason_tags": ["wrong_area"],
                },
            )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "valuation_feedback_only")

    # ---- shared admin helpers -----------------------------------------
    def _login_tier(self, client, tier):
        from auth.core import SESSION_COOKIE_NAME
        from db.connection import get_conn

        token = f"ai-review-{tier}-token-{self.token}-{len(self.user_ids)}"
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (identifier, identifier_type, "
                "password_hash, tier) VALUES (?, 'email', 'h', ?)",
                (f"{tier}-{len(self.user_ids)}-{self.token}", tier),
            )
            self.user_ids.append(cur.lastrowid)
            conn.execute(
                "INSERT INTO user_sessions (token, user_id, expires_at) "
                "VALUES (?, ?, '2099-01-01T00:00:00')",
                (token, cur.lastrowid),
            )
        try:
            client.set_cookie(SESSION_COOKIE_NAME, token)
        except TypeError:
            client.set_cookie("localhost", SESSION_COOKIE_NAME, token)

    def _login_admin(self, client):
        from auth.core import SESSION_COOKIE_NAME
        from db.connection import get_conn

        token = f"ai-review-admin-token-{self.token}"
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (identifier, identifier_type, "
                "password_hash, tier) VALUES (?, 'email', 'h', 'admin')",
                (f"admin-{self.token}",),
            )
            self.user_ids.append(cur.lastrowid)
            conn.execute(
                "INSERT INTO user_sessions (token, user_id, expires_at) "
                "VALUES (?, ?, '2099-01-01T00:00:00')",
                (token, cur.lastrowid),
            )
        try:
            client.set_cookie(SESSION_COOKIE_NAME, token)
        except TypeError:
            client.set_cookie("localhost", SESSION_COOKIE_NAME, token)

    def _insert_human_label(self, listing_id, verdict, via_app=None):
        if via_app is not None:
            with via_app.app.test_request_context():
                from db.connection import get_conn

                with get_conn() as conn:
                    via_app._save_ai_training_feedback(
                        conn, listing_id, {"verdict": verdict})
            return
        from db.connection import get_conn

        with get_conn() as conn:
            conn.execute(
                "INSERT INTO ai_training_feedback (listing_id, actor, "
                "verdict) VALUES (?, 'admin', ?)",
                (listing_id, verdict),
            )


if __name__ == "__main__":
    unittest.main()

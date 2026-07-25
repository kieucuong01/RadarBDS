import datetime as dt
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path('/opt/radar-bds/current')


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seed = load_module('radar_group_comment_seed', ROOT / 'scripts/radar_group_comment_seed.py')
commenter = load_module('browser_use_group_comment', ROOT / 'scripts/browser_use_group_comment.py')

NOW = dt.datetime(2026, 7, 26, 20, 30, tzinfo=dt.timezone(dt.timedelta(hours=7)))
TARGET = {
    'id': 'g1',
    'name': 'Group 1',
    'url': 'https://www.facebook.com/groups/g1/',
    'comment_enabled': True,
    'comment_allow_link': False,
    'max_comments_per_week': 1,
}

QUESTION = '''Nguyễn Văn A
2 hours ago
 ·
Cho em hỏi em đang xem một lô đất ở Phú Mỹ, giá 2,4 tỷ diện tích 100m2. Mức này có nên mua không và cần so giá thế nào?
Comment as Radar BDS'''

SALES_POST = '''Môi Giới A
3 hours ago
 ·
BÁN GẤP LÔ ĐẤT PHÚ MỸ GIÁ CHỈ 2,4 TỶ. Liên hệ 0909123456 để chốt ngay.
Comment as Radar BDS'''


class RelevanceGateTests(unittest.TestCase):
    def test_accepts_recent_first_person_buyer_question(self):
        result = seed.score_candidate(QUESTION, now=NOW)
        self.assertTrue(result['eligible'])
        self.assertGreaterEqual(result['score'], 7)
        self.assertEqual(result['author'], 'Nguyễn Văn A')
        self.assertEqual(result['topic'], 'price_compare')
        self.assertEqual(result['location'], 'Phú Mỹ')

    def test_rejects_sales_post_without_real_question(self):
        result = seed.score_candidate(SALES_POST, now=NOW)
        self.assertFalse(result['eligible'])
        self.assertIn('sales_heavy', result['reasons'])

    def test_rejects_when_commenting_is_off(self):
        result = seed.score_candidate(QUESTION + '\nCommenting has been turned off for this post.', now=NOW)
        self.assertFalse(result['eligible'])
        self.assertIn('comments_off', result['reasons'])

    def test_rejects_stale_question(self):
        stale = QUESTION.replace('2 hours ago', 'May 12')
        result = seed.score_candidate(stale, now=NOW)
        self.assertFalse(result['eligible'])
        self.assertIn('not_recent', result['reasons'])

    def test_rejects_hour_based_question_older_than_configured_limit(self):
        stale = QUESTION.replace('2 hours ago', '80 hours ago')
        result = seed.score_candidate(stale, now=NOW, max_age_hours=72)
        self.assertFalse(result['eligible'])
        self.assertIn('not_recent', result['reasons'])


class FrequencyAndDedupeTests(unittest.TestCase):
    def test_shared_daily_cap_counts_group_post_attempt(self):
        post_state = {'actions': [{'at': '2026-07-26T10:00:00+07:00', 'status': 'removed_auto_link'}]}
        self.assertTrue(seed.daily_action_taken(NOW, post_state, {'actions': []}))

    def test_same_post_is_not_used_twice(self):
        candidate = {'post_url': 'https://www.facebook.com/groups/g1/posts/123/', 'author': 'A', 'topic': 'price_compare'}
        state = {'actions': [{'at': '2026-07-20T20:00:00+07:00', 'post_url': candidate['post_url'], 'author': 'A', 'topic': 'price_compare', 'status': 'published'}]}
        self.assertTrue(seed.candidate_already_used(candidate, state, NOW))

    def test_same_author_is_cooled_down_for_30_days(self):
        candidate = {'post_url': 'https://www.facebook.com/groups/g1/posts/456/', 'author': 'A', 'topic': 'legal'}
        state = {'actions': [{'at': '2026-07-20T20:00:00+07:00', 'post_url': 'other', 'author': 'A', 'topic': 'price_compare', 'status': 'published'}]}
        self.assertTrue(seed.candidate_already_used(candidate, state, NOW))

    def test_global_weekly_cap_blocks_after_three_published_comments(self):
        config = {'global': {'max_comments_per_week': 3}}
        state = {'actions': [
            {'at': '2026-07-21T20:00:00+07:00', 'status': 'published'},
            {'at': '2026-07-22T20:00:00+07:00', 'status': 'published'},
            {'at': '2026-07-23T20:00:00+07:00', 'status': 'published'},
        ]}
        self.assertTrue(seed.global_weekly_full(config, state, NOW))

    def test_daily_cap_uses_timezone_aware_instants_not_string_prefixes(self):
        now = dt.datetime(2026, 7, 26, 0, 30, tzinfo=dt.timezone(dt.timedelta(hours=7)))
        post_state = {'actions': [{'at': '2026-07-25T18:00:00+00:00', 'status': 'published'}]}
        self.assertTrue(seed.daily_action_taken(now, post_state, {'actions': []}))

    def test_existing_naive_iso_timestamps_do_not_crash_cooldowns_or_weekly_caps(self):
        candidate = {'post_url': 'https://www.facebook.com/groups/g1/posts/789/', 'author': 'A', 'topic': 'legal', 'target_id': 'g1'}
        state = {'actions': [{'at': '2026-07-20T20:00:00', 'post_url': 'other', 'author': 'A', 'topic': 'legal', 'target_id': 'g1', 'status': 'published'}]}
        self.assertTrue(seed.candidate_already_used(candidate, state, NOW))
        self.assertTrue(seed.target_weekly_full(TARGET, state, NOW))
        self.assertTrue(seed.global_weekly_full({'global': {'max_comments_per_week': 1}}, state, NOW))


class CopyAndExecutorGuardTests(unittest.TestCase):
    def test_comment_is_transparent_helpful_and_has_no_link(self):
        scored = seed.score_candidate(QUESTION, now=NOW)
        text = seed.build_comment(scored, TARGET)
        self.assertTrue(text.startswith('Radar BDS'))
        self.assertIn('giá/m²', text)
        self.assertIn('giá rao', text)
        self.assertNotIn('http://', text)
        self.assertNotIn('https://', text)
        self.assertLessEqual(len(text), 700)

    def test_executor_rejects_disabled_comment_target(self):
        queue = {'target': {'surface': 'group_comment', 'page_url': TARGET['url']}, 'content': {'comment': 'Radar BDS góp ý.'}}
        config = {'targets': [dict(TARGET, comment_enabled=False)]}
        with self.assertRaises(SystemExit):
            commenter.allowlisted(queue, config)

    def test_executor_binds_source_post_url_to_allowlisted_group_id(self):
        queue = {
            'target': {'surface': 'group_comment', 'page_url': TARGET['url']},
            'source': {'post_url': 'https://www.facebook.com/groups/other-group/posts/123/'},
            'content': {'comment': 'Radar BDS góp ý.'},
        }
        config = {'targets': [dict(TARGET, group_id='g1')]}
        with self.assertRaises(SystemExit):
            commenter.allowlisted(queue, config)

    def test_executor_rejects_link_when_target_disallows_it(self):
        with self.assertRaises(SystemExit):
            commenter.validate_comment('Radar BDS góp ý: xem https://radarbds.vn', TARGET)

    def test_executor_rejects_bare_domain_when_target_disallows_links(self):
        for domain in ('radarbds.vn', 'bit.ly/foo', 'example.ai', 'example.xyz/path'):
            with self.subTest(domain=domain):
                with self.assertRaises(SystemExit):
                    commenter.validate_comment(f'Radar BDS góp ý: xem {domain} để kiểm tra', TARGET)
                self.assertTrue(seed.contains_link(domain))

    def test_executor_rejects_newlines_tabs_and_control_characters(self):
        for text in (
            'Radar BDS góp ý dòng một\ndòng hai',
            'Radar BDS góp ý\ttab',
            'Radar BDS góp ý\x1bcontrol',
        ):
            with self.subTest(text=repr(text)):
                with self.assertRaises(SystemExit):
                    commenter.validate_comment(text, TARGET)

    def test_prepare_clears_editor_with_ctrl_modifier_and_verifies_empty(self):
        queue = {
            'target': {'surface': 'group_comment', 'page_url': TARGET['url']},
            'source': {
                'post_url': 'https://www.facebook.com/groups/g1/posts/123/',
                'post_needle': 'Cho em hỏi',
                'author': 'Nguyễn Văn A',
            },
            'content': {'comment': 'Radar BDS góp một cách kiểm tra hữu ích.'},
            'guards': {'relevance_gate_passed': False},
        }
        generated = commenter.program(queue, 'prepare', '/tmp/prepare.png', dict(TARGET, group_id='g1'))
        self.assertIn("press_key('a',modifiers=2)", generated)
        self.assertIn('Prepare cleanup failed: editor is not empty', generated)

    def test_publish_program_requires_new_rendered_comment_and_real_comment_permalink(self):
        queue = {
            'target': {'surface': 'group_comment', 'page_url': TARGET['url']},
            'source': {
                'post_url': 'https://www.facebook.com/groups/g1/posts/123/',
                'post_needle': 'Cho em hỏi',
                'author': 'Nguyễn Văn A',
            },
            'content': {'comment': 'Radar BDS góp một cách kiểm tra hữu ích.'},
            'guards': {'relevance_gate_passed': True},
        }
        generated = commenter.program(queue, 'publish', '/tmp/publish.png', dict(TARGET, group_id='g1'))
        self.assertIn('before_comment_count', generated)
        self.assertIn('after_comment_count <= before_comment_count', generated)
        self.assertIn('comment_id', generated)
        self.assertIn('reply_comment_id', generated)
        self.assertNotIn('permalink or post_url', generated)


class JsonStateConfigTests(unittest.TestCase):
    def test_missing_first_run_state_uses_default(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / 'missing-state.json'
            default = {'actions': []}
            self.assertEqual(seed.load_json(missing, default, missing_ok=True), default)

    def test_corrupt_existing_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'state.json'
            path.write_text('{not json', encoding='utf-8')
            with self.assertRaises(SystemExit):
                seed.load_json(path, {'actions': []}, missing_ok=True)

    def test_unreadable_existing_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'state.json'
            path.write_text('{"actions": []}', encoding='utf-8')
            path.chmod(0)
            try:
                with self.assertRaises(SystemExit):
                    seed.load_json(path, {'actions': []}, missing_ok=True)
            finally:
                path.chmod(0o600)


if __name__ == '__main__':
    unittest.main()

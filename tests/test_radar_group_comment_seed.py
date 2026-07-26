import argparse
import contextlib
import datetime as dt
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path('/opt/radar-bds/current')


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seed = load_module('radar_public_post_comment_seed', ROOT / 'scripts/radar_group_comment_seed.py')
commenter = load_module('browser_use_public_post_comment', ROOT / 'scripts/browser_use_group_comment.py')

NOW = dt.datetime(2026, 7, 26, 20, 30, tzinfo=dt.timezone(dt.timedelta(hours=7)))
GLOBAL = {
    'identity': 'Tiny Sudo',
    'editor_identity': 'Tiny',
    'restore_identity': 'Radar BDS',
    'max_comments_per_day': 3,
    'max_comments_per_week': 21,
    'max_comment_age_hours': 72,
    'min_reactions': 10,
    'min_comments': 3,
    'min_total_engagement': 15,
    'min_relevance_score': 6,
    'automated_link_policy': 'single_contextual_radar_link',
    'allowed_link_host': 'radarbds.vn',
}
DEAL_COVERAGE = {
    'THỦ DẦU MỘT': ['Hòa Phú', 'Phú Cường'],
}
CONFIG = {
    'schema': 'radar_social_public_post_comment.v1',
    'global': GLOBAL,
    'deal_coverage': DEAL_COVERAGE,
    'queries': ['giá đất Bình Dương'],
}
RADAR_LINK = 'https://radarbds.vn/?tab=signals&city=TH%E1%BB%A6+D%E1%BA%A6U+M%E1%BB%98T&ward=H%C3%B2a+Ph%C3%BA&date_range=3m&mos_min=10&utm_source=facebook&utm_medium=comment&utm_campaign=public_post_seeding&utm_content=hoa-phu-price-compare'
VALID_COMMENT = f'Có thể xem các tin và tín hiệu giá tại Hòa Phú ở đây: {RADAR_LINK}. Nên kiểm tra ngày đăng, vị trí, pháp lý và giá thực tế trước khi đi xem.'
PUBLIC_POST = '''Báo Bình Dương
2 hours ago
Giá đất tại Hòa Phú Thủ Dầu Một đang được nhiều người quan tâm. Khi so sánh bất động sản, nên nhìn giá/m², loại hình và vị trí thay vì chỉ nhìn giá tổng.
53 reactions
12 comments
2 shares'''
UNRELATED_POST = '''Tin Công Nghệ
2 hours ago
Điện thoại mới ra mắt, pin tốt và camera đẹp.
100 reactions
30 comments
10 shares'''
SPONSORED_POST = '''Dự án A
Sponsored
MUA LÀ LỜI, GIÁ TUYỆT CHỦNG. Send message để nhận bảng giá căn hộ.
100 reactions
30 comments
10 shares'''


def item(**overrides):
    base = {
        'query': 'giá đất Bình Dương',
        'surface': 'public_post',
        'post_url': 'https://www.facebook.com/baobinhduong/posts/pfbid012345/',
        'author': 'Báo Bình Dương',
        'author_url': 'https://www.facebook.com/baobinhduong',
        'text': PUBLIC_POST,
        'engagement': {'reactions': 53, 'comments': 12, 'shares': 2},
    }
    base.update(overrides)
    return base


def valid_queue(**overrides):
    queue = {
        'target': {'surface': 'public_post_comment', 'identity': 'Tiny Sudo'},
        'source': {
            'post_url': item()['post_url'],
            'post_needle': 'Giá đất tại Hòa Phú',
            'author': 'Báo Bình Dương',
            'author_url': 'https://www.facebook.com/baobinhduong',
            'topic': 'price_compare',
            'location': 'Hòa Phú',
            'engagement': {'reactions': 53, 'comments': 12, 'shares': 2},
        },
        'content': {'comment': VALID_COMMENT, 'link': RADAR_LINK, 'link_policy': 'single_contextual_radar_link'},
        'guards': {'relevance_gate_passed': True, 'broker_exclusion_passed': True},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(queue.get(key), dict):
            queue[key] = {**queue[key], **value}
        else:
            queue[key] = value
    return queue


class BrokerExclusionTests(unittest.TestCase):
    def test_normalizes_profile_urls_without_tracking_parameters(self):
        self.assertEqual(
            seed.normalize_profile_url('https://www.facebook.com/foo.bar/?__cft__[0]=abc'),
            'https://www.facebook.com/foo.bar',
        )

    def test_normalizes_profile_php_by_numeric_id(self):
        self.assertEqual(
            seed.normalize_profile_url('https://www.facebook.com/profile.php?id=61500123&__tn__=x'),
            'https://www.facebook.com/profile.php?id=61500123',
        )

    def test_loads_all_selected_brokers_as_exact_exclusions(self):
        data = {
            'Thủ Dầu Một': [{'url': 'https://www.facebook.com/chosen.broker', 'broker_name': 'Chosen Broker'}],
            'Bến Cát': [{'url': 'https://www.facebook.com/other.broker/', 'broker_name': 'Other Broker'}],
        }
        exclusions = seed.load_broker_exclusions(data)
        self.assertIn('https://www.facebook.com/chosen.broker', exclusions['urls'])
        self.assertIn('chosen broker', exclusions['names'])
        self.assertEqual(len(exclusions['urls']), 2)

    def test_rejects_selected_broker_by_exact_profile_url(self):
        exclusions = {'urls': {'https://www.facebook.com/chosen.broker'}, 'names': set()}
        self.assertTrue(seed.is_excluded_broker('Tên Khác', 'https://www.facebook.com/chosen.broker?ref=search', exclusions))

    def test_rejects_selected_broker_by_exact_normalized_name_fallback(self):
        exclusions = {'urls': set(), 'names': {'chosen broker'}}
        self.assertTrue(seed.is_excluded_broker('Chosen   Broker', '', exclusions))

    def test_does_not_use_fuzzy_name_matching_for_unrelated_author(self):
        exclusions = {'urls': set(), 'names': {'nguyễn đạt'}}
        self.assertFalse(seed.is_excluded_broker('Nguyễn Đạt Tin Tức', '', exclusions))


class PublicPostGateTests(unittest.TestCase):
    def test_accepts_recent_engaged_binh_duong_real_estate_post(self):
        result = seed.score_candidate(item(), now=NOW, global_config=GLOBAL)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['location'], 'Hòa Phú')
        self.assertGreaterEqual(result['score'], GLOBAL['min_relevance_score'])

    def test_rejects_unrelated_post_even_with_high_engagement(self):
        result = seed.score_candidate(item(text=UNRELATED_POST), now=NOW, global_config=GLOBAL)
        self.assertFalse(result['eligible'])
        self.assertIn('not_relevant_real_estate', result['reasons'])

    def test_rejects_real_estate_post_outside_thu_dau_mot_context(self):
        text = PUBLIC_POST.replace('Hòa Phú Thủ Dầu Một', 'Phú Mỹ Hưng Quận 7 TP.HCM')
        result = seed.score_candidate(item(text=text), now=NOW, global_config=GLOBAL)
        self.assertFalse(result['eligible'])
        self.assertEqual(result['location'], '')
        self.assertIn('outside_target_market', result['reasons'])

    def test_requires_explicit_thu_dau_mot_context_for_target_ward(self):
        no_city_context = PUBLIC_POST.replace('Hòa Phú Thủ Dầu Một', 'Hòa Phú Bình Dương')
        result = seed.score_candidate(item(text=no_city_context), now=NOW, global_config=GLOBAL)
        self.assertFalse(result['eligible'])
        self.assertEqual(result['location'], '')

    def test_detects_explicit_thu_dau_mot_ward_without_raw_substring_collision(self):
        self.assertEqual(seed.detect_location('Giá đất Phú Mỹ Thủ Dầu Một tăng, bất động sản nhiều người hỏi'), 'Phú Mỹ')
        self.assertEqual(seed.detect_location('Giá đất Phú Mỹ Hưng Quận 7 TP.HCM nhiều người hỏi'), '')

    def test_rejects_sponsored_or_paid_ad(self):
        result = seed.score_candidate(item(text=SPONSORED_POST), now=NOW, global_config=GLOBAL)
        self.assertFalse(result['eligible'])
        self.assertIn('sponsored_or_ad', result['reasons'])

    def test_accepts_verified_group_post_surface(self):
        result = seed.score_candidate(item(surface='group_post', post_url='https://www.facebook.com/groups/g/posts/123/'), now=NOW, global_config=GLOBAL)
        self.assertTrue(result['eligible'])
        self.assertNotIn('unsupported_surface', result['reasons'])

    def test_rejects_unsupported_surface(self):
        result = seed.score_candidate(item(surface='profile_post'), now=NOW, global_config=GLOBAL)
        self.assertFalse(result['eligible'])
        self.assertIn('unsupported_surface', result['reasons'])

    def test_rejects_post_below_reaction_threshold(self):
        result = seed.score_candidate(item(engagement={'reactions': 9, 'comments': 12, 'shares': 2}), now=NOW, global_config=GLOBAL)
        self.assertFalse(result['eligible'])
        self.assertIn('low_reactions', result['reasons'])

    def test_rejects_post_below_comment_threshold(self):
        result = seed.score_candidate(item(engagement={'reactions': 50, 'comments': 2, 'shares': 3}), now=NOW, global_config=GLOBAL)
        self.assertFalse(result['eligible'])
        self.assertIn('low_comments', result['reasons'])

    def test_rejects_stale_post(self):
        result = seed.score_candidate(item(text=PUBLIC_POST.replace('2 hours ago', 'May 12')), now=NOW, global_config=GLOBAL)
        self.assertFalse(result['eligible'])
        self.assertIn('not_recent', result['reasons'])

    def test_choose_candidate_excludes_selected_broker_before_ranking(self):
        selected = item(text=PUBLIC_POST.replace('Dĩ An', 'Hòa Phú'), author='Chosen Broker', author_url='https://www.facebook.com/chosen.broker', engagement={'reactions': 500, 'comments': 100, 'shares': 20})
        allowed = item(text=PUBLIC_POST.replace('Dĩ An', 'Hòa Phú'), post_url='https://www.facebook.com/baobinhduong/posts/pfbid999/')
        exclusions = {'urls': {'https://www.facebook.com/chosen.broker'}, 'names': {'chosen broker'}}
        chosen, report = seed.choose_candidate(CONFIG, {'actions': []}, [selected, allowed], NOW, exclusions)
        self.assertEqual(chosen['post_url'], allowed['post_url'])
        self.assertEqual(report['rejected']['selected_broker'], 1)

    def test_choose_candidate_rejects_disabled_city_and_city_only_posts(self):
        disabled = item(text=PUBLIC_POST.replace('Hòa Phú Thủ Dầu Một', 'Dĩ An Bình Dương'))
        broad_city = item(text=PUBLIC_POST.replace('Hòa Phú Thủ Dầu Một', 'Thủ Dầu Một'))
        chosen, report = seed.choose_candidate(CONFIG, {'actions': []}, [disabled, broad_city], NOW, {'urls': set(), 'names': set()})
        self.assertIsNone(chosen)
        self.assertEqual(report['rejected']['outside_target_market'], 2)


class UrlAndEmbedTests(unittest.TestCase):
    def test_accepts_direct_public_post_reel_and_video_urls(self):
        urls = [
            'https://www.facebook.com/page/posts/pfbid123/',
            'https://www.facebook.com/reel/1699041781220369/',
            'https://www.facebook.com/page/videos/123456/',
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(seed.is_public_post_url(url))
                self.assertTrue(commenter.is_public_post_url(url))

    def test_rejects_legacy_permalink_photo_and_watch_urls(self):
        urls = [
            'https://www.facebook.com/permalink.php?story_fbid=123&id=456',
            'https://www.facebook.com/photo.php?fbid=123',
            'https://www.facebook.com/watch/123456/',
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertFalse(seed.is_public_post_url(url))
                self.assertFalse(commenter.is_public_post_url(url))

    def test_accepts_group_post_and_permalink_urls(self):
        urls = [
            'https://www.facebook.com/groups/g/posts/123/',
            'https://www.facebook.com/groups/123456789/permalink/987654321/',
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(seed.is_public_post_url(url))
                self.assertTrue(commenter.is_public_post_url(url))

    def test_rejects_search_profile_and_group_home_urls(self):
        urls = [
            'https://www.facebook.com/groups/g/',
            'https://www.facebook.com/search/posts/?q=abc',
            'https://www.facebook.com/some.profile',
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertFalse(seed.is_public_post_url(url))
                self.assertFalse(commenter.is_public_post_url(url))

    def test_generated_discovery_harness_is_valid_python(self):
        class Completed:
            returncode = 0
            stdout = '{"restored": true, "results": []}\n'
            stderr = ''

        original_run = seed.subprocess.run
        original_ensure = seed.ensure_browser
        try:
            seed.ensure_browser = lambda: None

            def compile_harness(*args, **kwargs):
                compile(kwargs['input'], '<generated-facebook-discovery>', 'exec')
                return Completed()

            seed.subprocess.run = compile_harness
            self.assertEqual(seed.discover_posts(CONFIG, now=NOW), [])
        finally:
            seed.subprocess.run = original_run
            seed.ensure_browser = original_ensure

    def test_extracts_permalink_from_embed_code(self):
        code = '<iframe src="https://www.facebook.com/plugins/video.php?href=https%3A%2F%2Fwww.facebook.com%2Freel%2F1699041781220369%2F&show_text=false"></iframe>'
        self.assertEqual(seed.extract_facebook_post_url(code), 'https://www.facebook.com/reel/1699041781220369/')

    def test_embed_extraction_fails_closed_without_public_permalink(self):
        self.assertEqual(seed.extract_facebook_post_url('<iframe src="https://example.com/x"></iframe>'), '')

    def test_embed_extraction_rejects_legacy_permalink_and_photo_targets(self):
        permalink = '<iframe src="https://www.facebook.com/plugins/post.php?href=https%3A%2F%2Fwww.facebook.com%2Fpermalink.php%3Fstory_fbid%3D123%26id%3D456"></iframe>'
        photo = '<iframe src="https://www.facebook.com/plugins/post.php?href=https%3A%2F%2Fwww.facebook.com%2Fphoto.php%3Ffbid%3D123"></iframe>'
        self.assertEqual(seed.extract_facebook_post_url(permalink), '')
        self.assertEqual(seed.extract_facebook_post_url(photo), '')


class FrequencyAndDedupeTests(unittest.TestCase):
    def test_daily_comment_cap_allows_group_post_but_blocks_after_three_comments(self):
        post_state = {'actions': [{'at': '2026-07-26T10:00:00+07:00', 'status': 'published'}]}
        self.assertFalse(seed.daily_comment_cap_full(CONFIG, {'actions': []}, NOW))
        state = {'actions': [
            {'at': '2026-07-26T08:00:00+07:00', 'status': 'published'},
            {'at': '2026-07-26T12:00:00+07:00', 'status': 'published'},
            {'at': '2026-07-26T16:00:00+07:00', 'status': 'published'},
        ]}
        self.assertTrue(seed.daily_comment_cap_full(CONFIG, state, NOW))

    def test_same_post_is_not_used_twice(self):
        candidate = item()
        state = {'actions': [{'at': '2026-07-20T20:00:00+07:00', 'post_url': candidate['post_url'], 'author': candidate['author'], 'topic': 'market_discussion', 'status': 'published'}]}
        self.assertTrue(seed.candidate_already_used(candidate, state, NOW))

    def test_same_author_is_cooled_down(self):
        candidate = item()
        state = {'actions': [{'at': '2026-07-20T20:00:00+07:00', 'post_url': 'other', 'author': candidate['author'], 'topic': 'other', 'status': 'published'}]}
        self.assertTrue(seed.candidate_already_used(candidate, state, NOW))

    def test_global_weekly_cap_blocks_at_configured_cap(self):
        cfg = json.loads(json.dumps(CONFIG))
        cfg['global']['max_comments_per_week'] = 3
        state = {'actions': [
            {'at': '2026-07-21T20:00:00+07:00', 'status': 'published'},
            {'at': '2026-07-22T20:00:00+07:00', 'status': 'published'},
            {'at': '2026-07-23T20:00:00+07:00', 'status': 'published'},
        ]}
        self.assertTrue(seed.global_weekly_full(cfg, state, NOW))

    def test_executor_state_caps_allow_first_run_empty_state(self):
        commenter.validate_executor_state_caps(valid_queue(), CONFIG, {'actions': []}, {'actions': []}, NOW)

    def test_executor_state_caps_reject_direct_rerun_bypasses(self):
        queue = valid_queue()
        source = queue['source']
        cases = {
            'daily': (
                {'actions': [{'at': '2026-07-26T08:00:00+07:00', 'status': 'published'}]},
                {'actions': [
                    {'at': '2026-07-26T08:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-26T12:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-26T16:00:00+07:00', 'status': 'published'},
                ]},
            ),
            'weekly': (
                {'actions': []},
                {'actions': [
                    {'at': '2026-07-20T08:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-21T08:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-22T08:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-23T08:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-24T08:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-25T08:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-26T08:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-20T09:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-21T09:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-22T09:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-23T09:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-24T09:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-25T09:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-26T09:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-20T10:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-21T10:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-22T10:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-23T10:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-24T10:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-25T10:00:00+07:00', 'status': 'published'},
                    {'at': '2026-07-26T10:00:00+07:00', 'status': 'published'},
                ]},
            ),
            'same_post': (
                {'actions': []},
                {'actions': [{'at': '2026-07-20T08:00:00+07:00', 'status': 'published', 'post_url': source['post_url']}]},
            ),
            'same_author': (
                {'actions': []},
                {'actions': [{'at': '2026-07-20T08:00:00+07:00', 'status': 'published', 'post_url': 'https://www.facebook.com/other/posts/1/', 'author': source['author']}]},
            ),
            'same_topic': (
                {'actions': []},
                {'actions': [{'at': '2026-07-20T08:00:00+07:00', 'status': 'published', 'post_url': 'https://www.facebook.com/other/posts/2/', 'author': 'Other', 'location': source['location'], 'topic': source['topic']}]},
            ),
        }
        for name, (post_state, comment_state) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(SystemExit):
                    commenter.validate_executor_state_caps(queue, CONFIG, post_state, comment_state, NOW)


class StandaloneExecutorStateTests(unittest.TestCase):
    def test_executor_imports_urllib_request_and_checks_deals_in_fresh_python(self):
        code = f'''
import importlib.util, json
from pathlib import Path
p=Path({str(ROOT / 'scripts/browser_use_group_comment.py')!r})
s=importlib.util.spec_from_file_location("isolated_commenter",p)
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
class Response:
    status=200
    def __enter__(self): return self
    def __exit__(self,*args): return False
m.urllib.request.urlopen=lambda request,timeout=20: Response()
m.json.load=lambda response: {{"stats":{{"hot":1,"total":1}}}}
assert m.landing_has_deals({RADAR_LINK!r}) is True
'''
        proc = subprocess.run([sys.executable, '-I', '-c', code], text=True, capture_output=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_direct_publish_records_one_action_then_blocks_rerun(self):
        class Completed:
            returncode = 0
            stderr = ''
            stdout = json.dumps({
                'ok': True,
                'status': 'published',
                'identity': 'Tiny Sudo',
                'post_url': item()['post_url'],
                'comment_permalink': 'https://www.facebook.com/x/posts/1/?comment_id=123',
                'comment': VALID_COMMENT,
                'screenshot': '/tmp/published.png',
            }) + '\n'

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            queue_path = root / 'queue.json'
            targets_path = root / 'targets.json'
            brokers_path = root / 'brokers.json'
            state_path = root / 'state.json'
            queue_path.write_text(json.dumps(valid_queue(), ensure_ascii=False), encoding='utf-8')
            targets_path.write_text(json.dumps(CONFIG, ensure_ascii=False), encoding='utf-8')
            brokers_path.write_text('{}', encoding='utf-8')
            args = argparse.Namespace(
                queue=str(queue_path), mode='publish', yes=True,
                targets=str(targets_path), brokers=str(brokers_path),
                post_state=str(root / 'missing-post-state.json'), state=str(state_path),
                cdp_url='http://127.0.0.1:9224', artifact_dir=str(root / 'artifacts'),
                run_dir=str(root / 'runs'), timeout=10,
            )
            original_run = commenter.subprocess.run
            original_deals = commenter.landing_has_deals
            calls = []
            try:
                commenter.landing_has_deals = lambda link: True
                commenter.subprocess.run = lambda *a, **k: calls.append((a, k)) or Completed()
                with contextlib.redirect_stdout(io.StringIO()):
                    commenter.run(args)
                saved = json.loads(state_path.read_text(encoding='utf-8'))
                self.assertEqual(len(saved['actions']), 1)
                self.assertEqual(saved['actions'][0]['status'], 'published')
                self.assertIn('comment_id=', saved['actions'][0]['comment_permalink'])
                with self.assertRaises(SystemExit):
                    commenter.run(args)
                self.assertEqual(len(calls), 1)
            finally:
                commenter.subprocess.run = original_run
                commenter.landing_has_deals = original_deals


class CopyAndExecutorGuardTests(unittest.TestCase):
    def test_builds_one_contextual_radar_link_with_city_ward_and_utm(self):
        scored = seed.score_candidate(item(text=PUBLIC_POST.replace('Dĩ An', 'Hòa Phú')), now=NOW, global_config=GLOBAL)
        link = seed.build_deal_link(scored, CONFIG)
        text = seed.build_comment(scored, CONFIG)
        self.assertEqual(link, RADAR_LINK)
        self.assertEqual(text.count('https://'), 1)
        self.assertIn(link, text)
        self.assertIn('giá/m²', text)
        self.assertIn('kiểm tra', text.casefold())
        self.assertLessEqual(len(text), 500)

    def test_city_level_or_disabled_city_is_not_seedable(self):
        examples = (
            PUBLIC_POST.replace('Hòa Phú Thủ Dầu Một', 'Thủ Dầu Một'),
            PUBLIC_POST.replace('Hòa Phú Thủ Dầu Một', 'Dĩ An Bình Dương'),
        )
        for text in examples:
            scored = seed.score_candidate(item(text=text), now=NOW, global_config=GLOBAL)
            with self.subTest(location=scored['location']):
                with self.assertRaises(ValueError):
                    seed.build_deal_link(scored, CONFIG)

    def test_landing_requires_at_least_one_hot_deal_signal(self):
        self.assertFalse(seed.landing_has_deals(RADAR_LINK, lambda _: {'stats': {'hot': 0, 'total': 26}}))
        self.assertTrue(seed.landing_has_deals(RADAR_LINK, lambda _: {'stats': {'hot': 1, 'total': 1}}))

    def test_executor_requires_tiny_sudo_identity(self):
        bad = dict(CONFIG, global_=dict(GLOBAL, identity='Radar BDS'))
        bad['global'] = dict(GLOBAL, identity='Radar BDS')
        with self.assertRaises(SystemExit):
            commenter.validate_config(bad)

    def test_executor_accepts_verified_group_post_target(self):
        queue = valid_queue(
            target={'surface': 'facebook_comment', 'identity': 'Tiny Sudo'},
            source={'post_url': 'https://www.facebook.com/groups/g/posts/123/'}
        )
        commenter.validate_queue(queue, CONFIG)

    def test_executor_requires_broker_exclusion_evidence(self):
        queue = valid_queue(guards={'relevance_gate_passed': True, 'broker_exclusion_passed': False})
        with self.assertRaises(SystemExit):
            commenter.validate_queue(queue, CONFIG)

    def test_executor_rejects_queue_below_interaction_threshold(self):
        queue = valid_queue(source={'engagement': {'reactions': 9, 'comments': 2, 'shares': 0}})
        with self.assertRaises(SystemExit):
            commenter.validate_queue(queue, CONFIG)

    def test_executor_rechecks_current_broker_watchlist_before_action(self):
        queue = {
            'target': {'surface': 'public_post_comment'},
            'source': {
                'post_url': 'https://www.facebook.com/chosen.broker/posts/pfbid1/',
                'post_needle': 'Giá đất',
                'author': 'Chosen Broker',
                'author_url': 'https://www.facebook.com/chosen.broker',
            },
            'content': {'comment': 'Theo mình nên so giá trên mét vuông trước.'},
            'guards': {'relevance_gate_passed': True, 'broker_exclusion_passed': True},
        }
        broker_data = {'Dĩ An': [{'url': 'https://www.facebook.com/chosen.broker', 'broker_name': 'Chosen Broker'}]}
        with self.assertRaises(SystemExit):
            commenter.validate_not_excluded(queue, broker_data)

    def test_executor_allows_exactly_one_contextual_radar_link(self):
        self.assertEqual(commenter.validate_comment(VALID_COMMENT, CONFIG), VALID_COMMENT)

    def test_executor_rejects_radar_link_missing_required_deal_filters(self):
        missing_date_range = RADAR_LINK.replace('&date_range=3m', '')
        missing_mos_min = RADAR_LINK.replace('&mos_min=10', '')
        for link in (missing_date_range, missing_mos_min):
            with self.subTest(link=link):
                with self.assertRaises(SystemExit):
                    commenter.validate_radar_link(link, CONFIG)

    def test_executor_rejects_missing_external_or_multiple_links_and_promotional_claims(self):
        bad = (
            'Chỉ có nội dung hữu ích nhưng thiếu link.',
            'Xem https://example.com/deal nhé.',
            f'Xem {RADAR_LINK} và https://radarbds.vn/binh-duong.',
            f'Cơ hội vàng, chốt nhanh: {RADAR_LINK}',
            'Xem radarbds.vn nhé',
        )
        for text in bad:
            with self.subTest(text=text):
                with self.assertRaises(SystemExit):
                    commenter.validate_comment(text, CONFIG)

    def test_executor_requires_queue_link_to_match_comment(self):
        queue = valid_queue(content={'comment': VALID_COMMENT, 'link': 'https://radarbds.vn/binh-duong', 'link_policy': 'single_contextual_radar_link'})
        with self.assertRaises(SystemExit):
            commenter.validate_queue(queue, CONFIG)

    def test_executor_requires_source_location_to_match_link_ward(self):
        phu_cuong_link = RADAR_LINK.replace('ward=H%C3%B2a+Ph%C3%BA', 'ward=Ph%C3%BA+C%C6%B0%E1%BB%9Dng').replace('utm_content=hoa-phu-price-compare', 'utm_content=phu-cuong-price-compare')
        phu_cuong_comment = VALID_COMMENT.replace(RADAR_LINK, phu_cuong_link)
        queue = valid_queue(content={'comment': phu_cuong_comment, 'link': phu_cuong_link, 'link_policy': 'single_contextual_radar_link'})
        with self.assertRaises(SystemExit):
            commenter.validate_queue(queue, CONFIG)

    def test_prepare_program_switches_to_tiny_and_restores_radar_in_finally(self):
        queue = valid_queue()
        generated = commenter.program(queue, 'prepare', '/tmp/prepare.png', CONFIG)
        self.assertIn("switch_identity('Tiny Sudo')", generated)
        self.assertIn("switch_identity('Radar BDS')", generated)
        self.assertIn('finally:', generated)
        self.assertIn('Comment as Tiny', generated)
        self.assertIn('Prepare cleanup failed: editor is not empty', generated)

    def test_publish_program_requires_new_rendered_comment_and_permalink(self):
        queue = valid_queue()
        generated = commenter.program(queue, 'publish', '/tmp/publish.png', CONFIG)
        self.assertIn('before_comment_count', generated)
        self.assertIn('after_comment_count <= before_comment_count', generated)
        self.assertIn('comment_id', generated)
        self.assertIn('reply_comment_id', generated)


class JsonStateTests(unittest.TestCase):
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

    def test_executor_missing_first_run_state_uses_default(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / 'missing-state.json'
            default = {'actions': []}
            self.assertEqual(commenter.load_json(missing, default, missing_ok=True), default)

    def test_executor_corrupt_existing_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'state.json'
            path.write_text('{not json', encoding='utf-8')
            with self.assertRaises(SystemExit):
                commenter.load_json(path, {'actions': []}, missing_ok=True)


if __name__ == '__main__':
    unittest.main()

import datetime as dt
import importlib.util
import unittest
from pathlib import Path

ROOT=Path('/opt/radar-bds/current')

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

auto=load_module('radar_group_auto_post',ROOT/'scripts/radar_group_auto_post.py')
poster=load_module('browser_use_group_post',ROOT/'scripts/browser_use_group_post.py')

PAGE={
    'path':'/tin-tuc/demo',
    'title':'Bài dữ liệu demo | Radar BDS',
    'hero_title':'Bài dữ liệu demo',
    'hero_text':'Radar BDS ghi nhận 120 tin rao trong 14 ngày, có 18 tín hiệu đáng kiểm tra và giá/m² cần so theo phường.',
    'article':{'published_at':dt.date.today().isoformat(),'modified_at':dt.date.today().isoformat()},
}
TARGET={'id':'g1','name':'Group 1','url':'https://www.facebook.com/groups/g1/','enabled':True,'requires_review':False,'max_posts_per_week':1,'min_gap_hours':120}

class GroupAutoPostTests(unittest.TestCase):
    def test_group_message_has_one_link_no_hashtag_and_disclaimer(self):
        text=auto.build_message('demo',PAGE)
        self.assertEqual(text.count('https://'),1)
        self.assertNotIn('#',text)
        self.assertIn('không thay thẩm định pháp lý',text)
        self.assertIn('utm_medium=group_post',text)


    def test_group_auto_post_rejects_generic_knowledge_article(self):
        generic=dict(PAGE, hero_title='Vì sao không nên so nhà đất chung với đất nền', hero_text='Bài giải thích kiến thức chung cho người mua.')
        self.assertFalse(auto.is_radar_value_article('vi-sao-khong-nen-so-nha-dat-chung-voi-dat-nen', generic))
        with self.assertRaises(ValueError): auto.build_message('vi-sao-khong-nen-so-nha-dat-chung-voi-dat-nen', generic)

    def test_choose_article_prefers_radar_value_not_generic_recent(self):
        original=auto.candidates
        generic=dict(PAGE, hero_title='Vì sao không nên so nhà đất chung với đất nền', hero_text='Bài giải thích kiến thức chung.')
        value=dict(PAGE, hero_title='Phú Mỹ có bao nhiêu tin đáng kiểm tra', hero_text='Radar BDS ghi nhận 220 tin rao trong 14 ngày, 31 tín hiệu và giá/m² theo phường.')
        auto.candidates=lambda:[('vi-sao-khong-nen-so-nha-dat-chung-voi-dat-nen',generic),('phu-my-tin-dang-kiem-tra',value)]
        try:
            picked=auto.choose_article({'actions':[]},TARGET)
            self.assertEqual(picked[0],'phu-my-tin-dang-kiem-tra')
        finally: auto.candidates=original

    def test_allowlist_rejects_disabled_target(self):
        queue={'target':{'surface':'group','page_url':TARGET['url']},'content':{'message':'x'}}
        cfg={'targets':[dict(TARGET,enabled=False)]}
        with self.assertRaises(SystemExit) as cm: poster.allowlisted(queue,cfg)
        self.assertIn('not enabled',str(cm.exception))

    def test_group_program_waits_for_native_blob_visual_in_caption_composer(self):
        queue={
            'target':{'surface':'group','page_url':TARGET['url']},
            'content':{'message':'Hook line\nBody','image':'/tmp/visual.png'},
        }
        original=poster.Path.exists
        poster.Path.exists=lambda _self: True
        try:
            program=poster.program(queue,'publish','/tmp/shot.png',TARGET)
        finally:
            poster.Path.exists=original
        compile(program,'<group-browser-program>','exec')
        self.assertIn('for _ in range(20):',program)
        self.assertIn('img[src^="blob:"]',program)

    def test_daily_cap_blocks_second_action(self):
        now=dt.datetime.now().astimezone()
        state={'actions':[{'at':now.isoformat(),'target_id':'other','status':'published'}]}
        self.assertIsNone(auto.choose_target({'targets':[TARGET]},state,now))

    def test_weekly_cap_blocks_target(self):
        now=dt.datetime.now().astimezone()
        state={'actions':[{'at':(now-dt.timedelta(days=2)).isoformat(),'target_id':'g1','status':'pending_review'}]}
        self.assertIsNone(auto.choose_target({'targets':[TARGET]},state,now))

    def test_duplicate_article_is_not_selected(self):
        original=auto.candidates
        auto.candidates=lambda:[('demo',PAGE)]
        try:
            state={'actions':[{'target_id':'g1','slug':'demo','status':'pending_review'}]}
            self.assertIsNone(auto.choose_article(state,TARGET))
        finally: auto.candidates=original

if __name__=='__main__': unittest.main()

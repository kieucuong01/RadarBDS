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
    'hero_text':'Một insight có ích cho người mua bất động sản Bình Dương.',
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

    def test_allowlist_rejects_disabled_target(self):
        queue={'target':{'surface':'group','page_url':TARGET['url']},'content':{'message':'x'}}
        cfg={'targets':[dict(TARGET,enabled=False)]}
        with self.assertRaises(SystemExit) as cm: poster.allowlisted(queue,cfg)
        self.assertIn('not enabled',str(cm.exception))

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

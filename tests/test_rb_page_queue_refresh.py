"""Migration is local-only; published proofs and unrelated queues are immutable."""
import json
from pathlib import Path

from scripts import rb_page_queue_refresh as m


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def item(slug, date='2026-07-25'):
    return {'schema':'radar_social_queue.v1','created_at':date,'source':{'slug':slug,'article_date':date},'target':{'surface':'page','mode':'publish'},'content':{'message':'old'},'status':'queued'}


def test_inventory_preserves_posted_slug_even_when_article_date_changed(tmp_path):
    root=tmp_path/'queue'
    proof=put(root/'autopost/a.json',item('posted','2026-09-01'))
    fresh=put(root/'b.json',item('unposted'))
    put(root/'posted_slugs.json',{'posted':{'posted:2026-07-25':{'slug':'posted','queue':str(proof)}}})
    plan=m.inventory(root)
    assert [x['path'] for x in plan if x['action']=='regenerate']==[str(fresh)]
    assert [x['path'] for x in plan if x['action']=='preserve_posted']==[str(proof)]


def test_inventory_excludes_groups_and_comment_states(tmp_path):
    put(tmp_path/'group-autopost/queue/g.json',item('group'))
    put(tmp_path/'state.json',{'posted':{}})
    assert m.inventory(tmp_path)==[]


def test_refresh_preserves_history_and_downgrades_old_publish_permission(tmp_path):
    p=put(tmp_path/'a.json',item('one'))
    before=p.read_bytes()
    new=item('one');new['content']['message']='new readable caption'
    result=m.replace_pending(p,new,backup_dir=tmp_path/'backup')
    saved=json.loads(p.read_text())
    assert saved['content']['message']=='new readable caption'
    assert saved['created_at']=='2026-07-25'
    assert saved['target']['mode']=='review'
    assert saved['target']['requires_review'] is True
    assert saved['regeneration']['original_source_date']=='2026-07-25'
    assert Path(result['backup']).read_bytes()==before


def test_failed_regeneration_does_not_leave_old_publishable_payload(tmp_path):
    p=put(tmp_path/'a.json',item('missing'))
    result=m.block_pending(p,'source_missing',backup_dir=tmp_path/'backup')
    d=json.loads(p.read_text())
    assert d['status']=='blocked'
    assert d['content']['message']==''
    assert d['target']['mode']=='review'
    assert 'source_missing' in d['regeneration']['blocked_reason']
    assert Path(result['backup']).exists()

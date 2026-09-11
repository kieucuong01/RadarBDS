"""Block legacy/review-only queue before any browser action."""
import pytest
from scripts import browser_use_page_post as p


def queue():
    return {'status':'queued','target':{'mode':'publish','requires_review':False},
        'source':{'http_status':200},'content':{'message':'Có bớt giá chưa chắc đã rẻ. Hỏi rõ đường vào và giấy tờ trước khi hẹn xem.'}}


def test_reject_review_permission():
    q=queue();q['target']['mode']='review'
    with pytest.raises(SystemExit,match='review'):p._assert_queue_publishable(q)


def test_reject_blocked_status():
    q=queue();q['status']='blocked'
    with pytest.raises(SystemExit,match='blocked'):p._assert_queue_publishable(q)


@pytest.mark.parametrize('value',[None,404,403])
def test_reject_unverified_source(value):
    q=queue();q['source']['http_status']=value
    with pytest.raises(SystemExit,match='source'):p._assert_queue_publishable(q)


@pytest.mark.parametrize('text',['Đất nền: 14/432 · 3,2%','giá trung vị 23 triệu/m²','Có 1.918 tin tin Radar đang theo dõi','property_type = dat_nen'])
def test_reject_robotic_legacy_copy(text):
    q=queue();q['content']['message']=text
    with pytest.raises(SystemExit,match='legacy'):p._assert_queue_publishable(q)

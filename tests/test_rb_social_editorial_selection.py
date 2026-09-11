"""Source selection for a mixed editorial Page, not latest-article reposting."""
import datetime as dt
from scripts import radar_social_auto_post as a


def test_posted_slug_not_republished_by_new_article_date():
    posted={'abc:2026-07-25':{'slug':'abc','posted_at':'2026-07-25'}}
    assert a.was_slug_posted('abc',posted)
    assert not a.was_slug_posted('other',posted)


def test_posted_state_parse_failure_is_not_an_empty_history(tmp_path, monkeypatch):
    import pytest
    state=tmp_path/'posted.json';state.write_text('{broken')
    monkeypatch.setattr(a,'STATE_PATH',state)
    with pytest.raises(SystemExit,match='posted state'):a.load_state()


def test_rank_avoids_recent_topic_and_last_pillar():
    rows=[{'slug':'latest','date':'2026-09-11','pillar':'radar_insight','topic':'same'},
          {'slug':'other','date':'2026-09-10','pillar':'radar_howto','topic':'new'},
          {'slug':'third','date':'2026-09-09','pillar':'buyer_checklist','topic':'fresh'}]
    recent=[{'pillar':'radar_insight','topic':'same'}]
    result=a.rank_editorial_candidates(rows,recent)
    assert result[0]['slug']!='latest'
    assert all(x['slug']!='latest' for x in result)


def test_rank_returns_no_repetitive_filler_when_every_topic_recent():
    rows=[{'slug':'a','date':'2026-09-11','pillar':'radar_insight','topic':'same'}]
    assert a.rank_editorial_candidates(rows,[{'pillar':'radar_insight','topic':'same'}])==[]

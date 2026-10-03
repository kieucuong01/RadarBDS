from copy import deepcopy
import pytest
from config.seo_articles import SEO_ARTICLES
from scripts import rb_social_editorial as engine

SLUGS = [
    'bang-gia-dat-va-gia-rao-khac-nhau-the-nao',
    'gia-rao-khac-gia-giao-dich-the-nao',
    'cach-doc-gia-m2-dat-nen-binh-duong',
    'vi-sao-khong-nen-so-nha-dat-chung-voi-dat-nen',
    'cach-dinh-gia-nha-dat-binh-duong-bang-gia-rao-theo-phuong',
    'khi-nao-nen-dung-cong-cu-dinh-gia-truoc-khi-goi-moi-gioi',
    'mos-la-gi-loc-tin-duoi-gia-co-so',
    'ty-le-cat-mau-nha-dat-thu-dau-mot-phuong-nao-can-kiem-tra',
]

def draft(slug, page=None):
    return engine.build_editorial(deepcopy(page or SEO_ARTICLES[slug]),
        'https://radarbds.vn/tin-tuc/' + slug, slug,
        make_visual=False, source_http_status=200)

@pytest.mark.parametrize('slug', SLUGS)
def test_real_sources_have_specific_standalone_copy_and_evidence(slug):
    result = draft(slug)
    assert result['status'] == 'ready'
    assert result['metadata'].get('copy_origin') == 'source_topic'
    assert result['metadata']['reader_angle_ready'] is True
    assert result['metadata']['source_sections']
    assert result['metadata']['source_date']
    text = result['caption']
    assert '\n\n' in text
    assert len(text.split()) >= 70
    assert not text.startswith(('Khi xem nhà đất ở', 'Muốn hỏi “bớt được bao nhiêu”'))
    assert not engine.caption_quality_issues(text)
    assert 'bình luận' in text


def test_topics_do_not_share_hooks_or_reader_benefits():
    rows = [draft(slug) for slug in SLUGS]
    assert len({r['caption'].split('\n')[0] for r in rows}) == len(rows)
    assert len({r['metadata']['topic'] for r in rows}) == len(rows)
    assert len({r['metadata']['reader_benefit'] for r in rows}) == len(rows)


def test_missing_source_sections_does_not_authorize_topic_copy():
    slug = SLUGS[0]
    page = deepcopy(SEO_ARTICLES[slug])
    page['article']['sections'] = []
    result = draft(slug, page)
    assert result['metadata'].get('reader_angle_ready') is False
    assert result['metadata']['copy_origin'] == 'legacy_fallback'


def test_valid_authored_copy_is_not_overwritten():
    slug = SLUGS[0]
    page = deepcopy(SEO_ARTICLES[slug])
    text = 'Bảng giá đất không phải giá chủ buộc phải bán.\n\nKhi thương lượng, so lại các tin cùng loại nhà đất trước.'
    page['social_editorial'] = {'caption': text}
    result = draft(slug, page)
    assert result['caption'] == text
    assert result['metadata'].get('copy_origin') == 'authored'


def test_generic_ward_caption_not_treated_as_publish_ready_angle():
    result = draft('gia-dat-chanh-my-hien-bao-nhieu')
    assert result['metadata'].get('reader_angle_ready') is False


def test_auto_selection_skips_generic_ward_copy_but_has_new_topics():
    from scripts.radar_social_auto_post import editorial_candidates
    candidates = editorial_candidates({})
    slugs = {r['slug'] for r in candidates}
    assert 'gia-dat-chanh-my-hien-bao-nhieu' not in slugs
    assert set(SLUGS).issubset(slugs)

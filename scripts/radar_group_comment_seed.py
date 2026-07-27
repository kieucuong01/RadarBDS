#!/usr/bin/env python3
"""Seed value-first Tiny Sudo comments on engaged Facebook real-estate posts.

The legacy filename is retained so the existing scheduler path remains stable. Public posts and
verified visible group posts are eligible; broker-watchlist profiles remain excluded.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path('/opt/radar-bds/current')
CONFIG = REPO / 'config/social_group_comment_targets.json'
BROKER_PROFILES = REPO / 'data/facebook_profiles.json'
EXECUTOR = REPO / 'scripts/browser_use_group_comment.py'
START_BROWSER = Path('/home/hermesops/radar-browser-use/start-radar-social-browser.sh')
BROWSER_USE = Path('/home/hermesops/radar-browser-use/.venv/bin/browser-use')
CDP = 'http://127.0.0.1:9224'
POST_STATE = Path('/opt/radar-bds/var/social_queue/group-autopost/state.json')
STATE = Path('/opt/radar-bds/var/social_queue/public-post-comment/state.json')
QUEUE_DIR = Path('/opt/radar-bds/var/social_queue/public-post-comment/queue')

TARGET_CITY = 'Thủ Dầu Một'
TARGET_WARDS = [
    'Tân An', 'Hiệp An', 'Tương Bình Hiệp', 'Định Hòa', 'Chánh Mỹ', 'Phú Mỹ',
    'Phú Cường', 'Phú Hòa', 'Phú Lợi', 'Hiệp Thành', 'Chánh Nghĩa', 'Phú Tân',
    'Phú Thọ', 'Hòa Phú',
]
OUTSIDE_CITY_CONTEXT = (
    'di an', 'thuan an', 'ben cat', 'tan uyen', 'bau bang', 'bac tan uyen',
    'phu giao', 'dau tieng', 'quan 7', 'q7', 'tp hcm', 'tphcm', 'ho chi minh',
    'sai gon', 'phu my hung',
)
REAL_ESTATE_TERMS = (
    'bất động sản', 'nhà đất', 'đất nền', 'giá đất', 'giá nhà', 'mua nhà', 'mua đất',
    'bán nhà', 'bán đất', 'cho thuê', 'nhà cấp 4', 'lô đất', 'đất mặt tiền',
    'căn hộ', 'chung cư', 'nhà phố', 'biệt thự', 'quy hoạch', 'sổ hồng', 'sổ đỏ',
    'thổ cư', 'giá/m²', 'giá/m2', 'thị trường nhà ở', 'thị trường địa ốc',
)


def load_json(path: Path, default: Any = None, *, missing_ok: bool = False) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        if missing_ok:
            return default
        raise SystemExit(f'Refusing: required JSON file is missing: {path}')
    except Exception as exc:
        raise SystemExit(f'Refusing: JSON file is corrupt or unreadable: {path}: {exc}')


def parse_time(value: str, default_tz: dt.tzinfo | None = None) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz or dt.datetime.now().astimezone().tzinfo)
    return parsed


def normalize_text(value: str) -> str:
    return re.sub(r'\s+', ' ', str(value or '').replace('\ufeff', ' ')).strip()


def normalize_name(value: str) -> str:
    return normalize_text(unicodedata.normalize('NFKC', str(value or ''))).casefold()


def normalize_profile_url(value: str) -> str:
    raw = html.unescape(str(value or '').strip())
    if not raw:
        return ''
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        return ''
    host = parsed.netloc.casefold().split(':', 1)[0]
    if host not in {'facebook.com', 'www.facebook.com', 'm.facebook.com', 'mbasic.facebook.com'}:
        return ''
    path = re.sub(r'/+', '/', parsed.path or '/').rstrip('/')
    if path.casefold() == '/profile.php':
        ident = urllib.parse.parse_qs(parsed.query).get('id', [''])[0]
        return f'https://www.facebook.com/profile.php?id={ident}' if ident.isdigit() else ''
    if not path or path == '/':
        return ''
    return 'https://www.facebook.com' + path.casefold()


def load_broker_exclusions(data: dict) -> dict[str, set[str]]:
    urls: set[str] = set()
    names: set[str] = set()
    for rows in (data or {}).values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = normalize_profile_url(row.get('url') or '')
            name = normalize_name(row.get('broker_name') or '')
            if url:
                urls.add(url)
            if name:
                names.add(name)
    return {'urls': urls, 'names': names}


def is_excluded_broker(author: str, author_url: str, exclusions: dict[str, set[str]]) -> bool:
    url = normalize_profile_url(author_url)
    name = normalize_name(author)
    return bool((url and url in exclusions.get('urls', set())) or (name and name in exclusions.get('names', set())))


def is_public_post_url(value: str) -> bool:
    raw = html.unescape(str(value or '').strip())
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        return False
    host = parsed.netloc.casefold().split(':', 1)[0]
    if host not in {'facebook.com', 'www.facebook.com', 'm.facebook.com', 'mbasic.facebook.com'}:
        return False
    path = re.sub(r'/+', '/', parsed.path or '/').casefold()
    if path.startswith('/search/'):
        return False
    if re.match(r'^/groups/[^/]+/(?:posts|permalink)/[^/]+/?$', path):
        return True
    if re.match(r'^/[^/]+/posts/[^/]+/?$', path):
        return True
    if re.match(r'^/reel/[^/]+/?$', path):
        return True
    if re.match(r'^/[^/]+/videos/[^/]+/?$', path):
        return True
    return False


def canonical_post_url(value: str) -> str:
    raw = html.unescape(str(value or '').strip())
    if not is_public_post_url(raw):
        return ''
    parsed = urllib.parse.urlparse(raw)
    host = 'www.facebook.com'
    path = re.sub(r'/+', '/', parsed.path)
    return urllib.parse.urlunparse(('https', host, path.rstrip('/') + '/', '', '', ''))


def extract_facebook_post_url(embed_code: str) -> str:
    value = html.unescape(str(embed_code or ''))
    for _ in range(3):
        decoded = urllib.parse.unquote(value)
        if decoded == value:
            break
        value = decoded
    candidates = re.findall(r'https://(?:www\.|m\.)?facebook\.com/[^\s"<>]+', value, flags=re.I)
    for candidate in candidates:
        candidate = candidate.rstrip('&)\'')
        # Plugin src can contain the public permalink in its href query value.
        if '/plugins/' in candidate:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(candidate).query)
            nested = query.get('href', [''])[0]
            if nested and is_public_post_url(nested):
                return canonical_post_url(nested)
        if is_public_post_url(candidate):
            return canonical_post_url(candidate)
    return ''


def contains_link(text: str) -> bool:
    label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    tld = r'(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})'
    domain = rf'(?:{label}\.)+{tld}'
    return bool(re.search(rf'https?://\S+|\bwww\.\S+|\b{domain}\b(?:/\S*)?', str(text or ''), flags=re.I))


def is_recent(text: str, now: dt.datetime, max_age_hours: int = 72, posted_at: str = '') -> bool:
    explicit = parse_time(posted_at, now.tzinfo) if posted_at else None
    if explicit:
        explicit = explicit.astimezone(now.tzinfo) if now.tzinfo else explicit.replace(tzinfo=None)
        age = (now - explicit).total_seconds() / 3600
        return 0 <= age <= max_age_hours
    low = str(text or '').casefold()
    numeric_units = [
        (r'\b(\d+)\s*(?:minutes?|mins?)\s+ago\b', 1 / 60),
        (r'\b(\d+)\s*(?:hours?|hrs?)\s+ago\b', 1),
        (r'\b(\d+)\s+days?\s+ago\b', 24),
        (r'\b(\d+)\s+phút\s+trước\b', 1 / 60),
        (r'\b(\d+)\s+giờ\s+trước\b', 1),
        (r'\b(\d+)\s+ngày\s+trước\b', 24),
    ]
    for pattern, multiplier in numeric_units:
        match = re.search(pattern, low)
        if match:
            return int(match.group(1)) * multiplier <= max_age_hours
    if re.search(r'\b(?:a|an|about an?)\s+minute\s+ago\b|\bjust now\b|\bvừa xong\b', low):
        return True
    if re.search(r'\b(?:a|an|about an?)\s+hour\s+ago\b', low):
        return max_age_hours >= 1
    if re.search(r'\ba day\s+ago\b|\b(?:yesterday|hôm qua)\b', low):
        return max_age_hours >= 24
    months = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
    }
    for name, month in months.items():
        match = re.search(rf'\b{name}\s+(\d{{1,2}})(?:,\s*(\d{{4}}))?', low)
        if match:
            year = int(match.group(2) or now.year)
            try:
                age_days = (now.date() - dt.date(year, month, int(match.group(1)))).days
                return 0 <= age_days and age_days * 24 <= max_age_hours
            except ValueError:
                return False
    return False


def location_search_text(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', normalize_text(value))
    ascii_text = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+', ' ', ascii_text.casefold()).strip()


def has_target_city_context(search_text: str) -> bool:
    return bool(re.search(r'\b(?:thu dau mot|tdm|tp tdm|tp thu dau mot)\b', search_text))


def has_outside_city_context(search_text: str) -> bool:
    return any(re.search(rf'\b{re.escape(term)}\b', search_text) for term in OUTSIDE_CITY_CONTEXT)


def contains_location_phrase(search_text: str, location: str) -> bool:
    phrase = location_search_text(location)
    return bool(phrase and re.search(rf'\b{re.escape(phrase)}\b', search_text))


def detect_location(text: str) -> str:
    search_text = location_search_text(text)
    if not has_target_city_context(search_text) or has_outside_city_context(search_text):
        return ''
    for location in TARGET_WARDS:
        if contains_location_phrase(search_text, location):
            return location
    return ''


def detect_topic(text: str) -> str:
    low = str(text or '').casefold()
    if any(x in low for x in ('quy hoạch', 'lộ giới', 'hạ tầng', 'vành đai', 'cao tốc')):
        return 'planning'
    if any(x in low for x in ('pháp lý', 'sổ hồng', 'sổ đỏ', 'thổ cư', 'đặt cọc')):
        return 'legal'
    if any(x in low for x in ('giá', 'bao nhiêu', 'giá/m²', 'giá/m2', 'so giá', 'triệu/m')):
        return 'price_compare'
    return 'market_discussion'


def post_needle(text: str, author: str = '') -> str:
    ignored = {'see more', 'see translation', 'like', 'reply', 'share', 'send message', normalize_name(author)}
    lines = []
    for raw in str(text or '').splitlines():
        line = normalize_text(raw)
        low = normalize_name(line)
        if not line or low in ignored or re.fullmatch(r'[\d.,kKmM\s]+', line):
            continue
        if len(line) >= 18:
            lines.append(line)
    return max(lines, key=len, default='')[:120]


def score_candidate(item: dict, now: dt.datetime | None = None, global_config: dict | None = None) -> dict:
    now = now or dt.datetime.now().astimezone()
    cfg = global_config or {}
    text = str(item.get('text') or '')
    low = text.casefold()
    reasons: list[str] = []
    engagement = item.get('engagement') or {}
    reactions = max(0, int(engagement.get('reactions') or 0))
    comments = max(0, int(engagement.get('comments') or 0))
    shares = max(0, int(engagement.get('shares') or 0))
    total_engagement = reactions + comments + shares
    location = detect_location(text)
    topic = detect_topic(text)
    relevant = any(term in low for term in REAL_ESTATE_TERMS)
    recent = is_recent(text, now, int(cfg.get('max_comment_age_hours', 72)), str(item.get('posted_at') or ''))
    is_group_post = str(item.get('surface') or '') == 'group_post' or '/groups/' in str(item.get('post_url') or '').casefold()
    min_reactions = int(cfg.get('group_post_min_reactions', 0) if is_group_post else cfg.get('min_reactions', 10))
    min_comments = int(cfg.get('group_post_min_comments', 0) if is_group_post else cfg.get('min_comments', 3))
    min_total = int(cfg.get('group_post_min_total_engagement', 0) if is_group_post else cfg.get('min_total_engagement', 15))
    sponsored = any(x in low for x in (
        'sponsored', 'được tài trợ', 'why am i seeing this ad', 'report ad', 'hide ad',
        'send message', 'nhận bảng giá', 'mua là lời', 'giá tuyệt chủng', 'booking ngay',
    ))
    surface = str(item.get('surface') or '')
    post_url = str(item.get('post_url') or '')
    comments_off = any(x in low for x in ('commenting has been turned off', 'đã tắt tính năng bình luận'))

    if surface not in {'public_post', 'group_post'}:
        reasons.append('unsupported_surface')
    if not is_public_post_url(post_url):
        reasons.append('invalid_public_permalink')
    if not relevant:
        reasons.append('not_relevant_real_estate')
    if not location:
        reasons.append('outside_target_market')
    if sponsored:
        reasons.append('sponsored_or_ad')
    if not recent:
        reasons.append('not_recent')
    if comments_off:
        reasons.append('comments_off')
    if reactions < min_reactions:
        reasons.append('low_reactions')
    if comments < min_comments:
        reasons.append('low_comments')
    if total_engagement < min_total:
        reasons.append('low_total_engagement')

    score = 0
    score += 2 if relevant else 0
    score += 2 if location else 0
    score += 1 if recent else 0
    score += 1 if reactions >= min_reactions else 0
    score += 1 if comments >= min_comments else 0
    score += 1 if total_engagement >= min_total else 0
    disqualifying = {
        'unsupported_surface', 'invalid_public_permalink', 'not_relevant_real_estate', 'outside_target_market',
        'sponsored_or_ad', 'not_recent', 'comments_off', 'low_reactions', 'low_comments',
        'low_total_engagement',
    }
    eligible = score >= int(cfg.get('min_relevance_score', 6)) and not disqualifying.intersection(reasons)
    return {
        **item,
        'eligible': eligible,
        'score': score,
        'reasons': reasons,
        'topic': topic,
        'location': location,
        'post_needle': post_needle(text, str(item.get('author') or '')),
        'post_text': text[:5000],
        'engagement': {'reactions': reactions, 'comments': comments, 'shares': shares, 'total': total_engagement},
    }


def daily_comment_count(now: dt.datetime, comment_state: dict) -> int:
    tz = now.tzinfo or dt.datetime.now().astimezone().tzinfo
    count = 0
    for action in (comment_state or {}).get('actions', []):
        at = parse_time(action.get('at', ''), tz)
        if at and at.astimezone(tz).date() == now.date() and action.get('status') not in ('failed', 'skipped'):
            count += 1
    return count


def daily_comment_cap_full(config: dict, comment_state: dict, now: dt.datetime) -> bool:
    cap = int((config.get('global') or {}).get('max_comments_per_day', 1))
    return daily_comment_count(now, comment_state) >= cap


def candidate_already_used(candidate: dict, state: dict, now: dt.datetime) -> bool:
    author_url = normalize_profile_url(candidate.get('author_url') or '')
    author_name = normalize_name(candidate.get('author') or '')
    for action in state.get('actions', []):
        at = parse_time(action.get('at', ''), now.tzinfo)
        if canonical_post_url(action.get('post_url') or '') == canonical_post_url(candidate.get('post_url') or ''):
            return True
        if not at:
            continue
        at = at.astimezone(now.tzinfo) if now.tzinfo else at.replace(tzinfo=None)
        age_days = (now - at).total_seconds() / 86400
        same_author = bool(
            (author_url and normalize_profile_url(action.get('author_url') or '') == author_url)
            or (author_name and normalize_name(action.get('author') or '') == author_name)
        )
        if same_author and age_days < 30:
            return True
        if action.get('location') == candidate.get('location') and action.get('topic') == candidate.get('topic') and age_days < 14:
            return True
    return False


def global_weekly_full(config: dict, state: dict, now: dt.datetime) -> bool:
    cap = int((config.get('global') or {}).get('max_comments_per_week', 3))
    count = 0
    for action in state.get('actions', []):
        at = parse_time(action.get('at', ''), now.tzinfo)
        if at:
            at = at.astimezone(now.tzinfo) if now.tzinfo else at.replace(tzinfo=None)
        if at and action.get('status') == 'published' and 0 <= (now - at).total_seconds() < 7 * 86400:
            count += 1
    return count >= cap


def choose_candidate(config: dict, state: dict, discovered: list[dict], now: dt.datetime, exclusions: dict[str, set[str]]) -> tuple[dict | None, dict]:
    rejected = Counter()
    accepted = []
    global_config = config.get('global') or {}
    for item in discovered:
        if is_excluded_broker(str(item.get('author') or ''), str(item.get('author_url') or ''), exclusions):
            rejected['selected_broker'] += 1
            continue
        scored = score_candidate(item, now=now, global_config=global_config)
        if not scored['eligible']:
            rejected.update(scored['reasons'] or ['below_score'])
            continue
        if candidate_already_used(scored, state, now):
            rejected['dedupe_or_cooldown'] += 1
            continue
        try:
            build_deal_link(scored, config)
        except ValueError:
            rejected['outside_enabled_seed_wards'] += 1
            continue
        accepted.append(scored)
    accepted.sort(key=lambda x: (x['score'], x['engagement']['comments'], x['engagement']['total']), reverse=True)
    return (accepted[0] if accepted else None), {'inspected': len(discovered), 'eligible': len(accepted), 'rejected': dict(rejected)}


def slugify(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', normalize_text(value))
    ascii_text = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+', '-', ascii_text.casefold()).strip('-') or 'binh-duong'


def deal_location(candidate: dict, config: dict) -> tuple[str, str]:
    location = normalize_text(candidate.get('location') or '')
    coverage = config.get('deal_coverage') or {}
    for city, wards in coverage.items():
        city_name = normalize_text(city)
        if normalize_name(location) == normalize_name(city_name):
            return city_name, ''
        for ward in wards if isinstance(wards, list) else []:
            ward_name = normalize_text(ward)
            if normalize_name(location) == normalize_name(ward_name):
                return city_name, ward_name
    return '', ''


def build_deal_link(candidate: dict, config: dict) -> str:
    location = normalize_text(candidate.get('location') or '')
    topic = normalize_text(candidate.get('topic') or 'market_discussion')
    city, ward = deal_location(candidate, config)
    if not city or not ward:
        raise ValueError('Comment seeding is limited to explicitly enabled wards')
    params: list[tuple[str, str]] = [
        ('tab', 'signals'),
        ('city', city),
        ('ward', ward),
        ('date_range', '3m'),
        ('mos_min', '10'),
        ('utm_source', 'facebook'),
        ('utm_medium', 'comment'),
        ('utm_campaign', 'public_post_seeding'),
        ('utm_content', f'{slugify(location)}-{slugify(topic)}'),
    ]
    return 'https://radarbds.vn/?' + urllib.parse.urlencode(params)


def article_campaign(config: dict, slug: str) -> dict:
    for row in config.get('article_redistribution') or []:
        if normalize_text(row.get('slug') or '') == normalize_text(slug):
            locations = [normalize_text(x) for x in row.get('locations') or [] if normalize_text(x)]
            queries = [normalize_text(x) for x in row.get('queries') or [] if normalize_text(x)]
            if not locations or not queries:
                raise ValueError('Article redistribution requires locations and queries')
            return {**row, 'locations': locations, 'queries': queries}
    raise ValueError('Article slug is not allowlisted for comment redistribution')


def article_already_distributed(slug: str, state: dict) -> bool:
    return any(
        action.get('article_slug') == slug and action.get('status') not in ('failed', 'skipped')
        for action in state.get('actions', [])
    )


def campaign_discovery_config(config: dict, campaign: dict) -> dict:
    scoped = json.loads(json.dumps(config))
    scoped['queries'] = list(campaign['queries'])
    for key in ('target_groups', 'target_pages'):
        for target in scoped.get(key) or []:
            if target.get('enabled'):
                target['queries'] = list(campaign['queries'])
    return scoped


def build_article_link(candidate: dict, campaign: dict) -> str:
    location = normalize_text(candidate.get('location') or '')
    if location not in campaign['locations']:
        raise ValueError('Candidate location does not match the article campaign')
    slug = normalize_text(campaign.get('slug') or '')
    params = [
        ('utm_source', 'facebook'),
        ('utm_medium', 'comment'),
        ('utm_campaign', 'article_redistribution'),
        ('utm_content', f'{slug}-{slugify(location)}'),
    ]
    return f'https://radarbds.vn/tin-tuc/{slug}?' + urllib.parse.urlencode(params)


def build_article_comment(candidate: dict, campaign: dict) -> str:
    location = normalize_text(candidate.get('location') or '')
    link = build_article_link(candidate, campaign)
    text = (
        f'Nếu đang so khu {location}, bài này có bảng dữ liệu theo phường/loại hình để đối chiếu thêm: {link}. '
        'Số liệu là giá rao dùng để lọc ban đầu; vẫn nên kiểm tra ngày đăng, vị trí, quy hoạch, pháp lý và giá thực tế.'
    )
    if text.count('https://') != 1 or len(text) > 500:
        raise ValueError('Article comment must contain one contextual link and stay within 500 characters')
    return text


def article_url_healthy(url: str) -> bool:
    try:
        request = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'RadarBDS-Social-Guard/1.0'})
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status == 200
    except Exception:
        return False


def fetch_public_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={'User-Agent': 'RadarBDS-Social-Guard/1.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f'Radar counts endpoint returned HTTP {response.status}')
        data = json.load(response)
    if not isinstance(data, dict):
        raise RuntimeError('Radar counts endpoint returned invalid JSON')
    return data


def landing_has_deals(link: str, fetcher=None) -> bool:
    try:
        parsed = urllib.parse.urlparse(link)
        query = urllib.parse.parse_qs(parsed.query)
        city = (query.get('city') or [''])[0]
        ward = (query.get('ward') or [''])[0]
        if not city or not ward:
            return False
        api_params: list[tuple[str, str]] = [
            ('date_range', (query.get('date_range') or ['3m'])[0]),
            ('city', city),
            ('ward', ward),
            ('prop_type', 'dat_nen'),
            ('prop_type', 'nha_dat'),
            ('prop_type', 'chung_cu'),
            ('prop_type', 'nha_tro'),
            ('mos_min', (query.get('mos_min') or ['10'])[0]),
        ]
        endpoint = 'https://radarbds.vn/api/counts?' + urllib.parse.urlencode(api_params)
        data = (fetcher or fetch_public_json)(endpoint)
        stats = data.get('stats') or {}
        return int(stats.get('hot') or 0) >= 1
    except Exception:
        return False


def build_comment(candidate: dict, config: dict) -> str:
    location = candidate.get('location') or 'Bình Dương'
    topic = candidate.get('topic')
    link = build_deal_link(candidate, config)
    if topic == 'price_compare':
        text = (
            f'Có thể xem các tin đang rao và tín hiệu giá ở {location} tại {link}. '
            'Nên lọc cùng loại hình/diện tích và so giá/m²; đồng thời kiểm tra ngày đăng, vị trí, '
            'quy hoạch, pháp lý và giá thực tế trước khi đi xem.'
        )
    elif topic == 'planning':
        text = (
            f'Có thể đối chiếu tin và tín hiệu thị trường ở {location} tại {link}. '
            'Thông tin quy hoạch cần tách phần đã có quyết định khỏi đề xuất; với lô cụ thể vẫn phải kiểm tra '
            'thửa đất, lộ giới, văn bản và hiện trạng thực tế.'
        )
    elif topic == 'legal':
        text = (
            f'Có thể lọc các tin đang rao ở {location} tại {link}. '
            'Trước khi đặt cọc nên kiểm tra người đứng tên, mục đích sử dụng, phần thổ cư, quy hoạch/lộ giới, '
            'thế chấp, ngày đăng và giá thực tế.'
        )
    else:
        text = (
            f'Có thể tham khảo các tin và tín hiệu giá ở {location} tại {link}. '
            'Nên tách đúng loại hình, diện tích và so giá/m²; sau đó kiểm tra ngày đăng, vị trí, '
            'pháp lý và giá thực tế trước khi quyết định.'
        )
    if text.count('https://') != 1 or len(text) > 500:
        raise ValueError('Tiny Sudo comment must contain one contextual Radar link and stay within 500 characters')
    return text


def cdp_ready() -> bool:
    try:
        with urllib.request.urlopen(CDP + '/json/version', timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def ensure_browser() -> None:
    if cdp_ready():
        return
    subprocess.Popen([str(START_BROWSER)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(30):
        time.sleep(1)
        if cdp_ready():
            return
    raise RuntimeError('Radar Social Chrome CDP unavailable')


def restore_radar_identity() -> None:
    program = r"""
import json,time
goto_url('https://www.facebook.com/'); wait_for_load(); time.sleep(3)
opened=js("(() => {const e=[...document.querySelectorAll('[role=button]')].find(x=>(x.getAttribute('aria-label')||'')==='Your profile');if(!e)return false;e.click();return true})()")
if not opened: raise RuntimeError('Your profile button not found')
time.sleep(2)
already=js("(() => [...document.querySelectorAll('[role=button]')].some(x=>(x.getAttribute('aria-label')||'').includes('Switch to Tiny Sudo')))()")
if not already:
    clicked=js("(() => {const e=[...document.querySelectorAll('[role=button]')].find(x=>(x.getAttribute('aria-label')||'').includes('Switch to Radar BDS'));if(!e)return false;e.click();return true})()")
    if not clicked: raise RuntimeError('Switch to Radar BDS not found')
    time.sleep(7)
else:
    press_key('ESC'); time.sleep(1)
opened=js("(() => {const e=[...document.querySelectorAll('[role=button]')].find(x=>(x.getAttribute('aria-label')||'')==='Your profile');if(!e)return false;e.click();return true})()")
time.sleep(2)
verified=js("(() => [...document.querySelectorAll('[role=button]')].some(x=>(x.getAttribute('aria-label')||'').includes('Switch to Tiny Sudo')))()")
press_key('ESC')
print(json.dumps({'ok':bool(opened and verified)}))
if not (opened and verified): raise RuntimeError('Radar BDS restore verification failed')
"""
    env = dict(**os.environ)
    env['BU_CDP_URL'] = CDP
    proc = subprocess.run([str(BROWSER_USE)], input=program, text=True, capture_output=True, env=env, timeout=75, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            'Could not restore Radar BDS identity after discovery failure\n'
            + proc.stdout[-2000:] + '\n' + proc.stderr[-2000:]
        )


def _rotating_slice(items: list[str], limit: int, now: dt.datetime, *, salt: int = 0) -> list[str]:
    if not items:
        return []
    limit = max(1, min(limit, len(items)))
    if len(items) <= limit:
        return items
    start = (now.toordinal() + salt) % len(items)
    return [items[(start + i) % len(items)] for i in range(limit)]


def selected_queries(config: dict, now: dt.datetime) -> list[str]:
    queries = [normalize_text(x) for x in config.get('queries', []) if normalize_text(x)]
    limit = max(1, int((config.get('global') or {}).get('max_queries_per_run', 2)))
    return _rotating_slice(queries, limit, now)


def discover_posts(config: dict, now: dt.datetime | None = None) -> list[dict]:
    now = now or dt.datetime.now().astimezone()
    queries = selected_queries(config, now)
    cfg = config.get('global') or {}
    per_target_limit = max(1, int(cfg.get('max_queries_per_target', 1)))
    target_groups = [g for g in config.get('target_groups', []) if g.get('enabled') and g.get('url')]
    group_scans = []
    for idx, group in enumerate(target_groups):
        group_query_pool = [normalize_text(x) for x in group.get('queries', []) if normalize_text(x)] or queries
        group_queries = _rotating_slice(group_query_pool, per_target_limit, now, salt=idx)
        group_scans.append({
            'name': normalize_text(group.get('name') or ''),
            'url': normalize_text(group.get('url') or '').rstrip('/') + '/',
            'queries': group_queries,
        })
    target_pages = [p for p in config.get('target_pages', []) if p.get('enabled') and p.get('url')]
    page_scans = []
    for idx, page in enumerate(target_pages):
        page_query_pool = [normalize_text(x) for x in page.get('queries', []) if normalize_text(x)] or queries
        page_queries = _rotating_slice(page_query_pool, per_target_limit, now, salt=idx + len(group_scans))
        page_scans.append({
            'name': normalize_text(page.get('name') or ''),
            'url': normalize_text(page.get('url') or '').rstrip('/') + '/',
            'queries': page_queries,
        })
    if not queries and not group_scans and not page_scans:
        return []
    identity = str(cfg.get('identity') or '')
    restore_identity = str(cfg.get('restore_identity') or '')
    max_results = max(1, int(cfg.get('max_results_per_query', 5)))
    if identity != 'Tiny Sudo' or restore_identity != 'Radar BDS':
        raise RuntimeError('Refusing discovery: Tiny Sudo/Radar BDS identity configuration mismatch')
    program = f"""
import json,time,urllib.parse
queries={queries!r}
group_scans={group_scans!r}
page_scans={page_scans!r}
identity={identity!r}
restore_identity={restore_identity!r}
max_results={max_results!r}
results=[]
restored=False

def visible(e): return bool(e.offsetWidth or e.offsetHeight or e.getClientRects().length)
def body_text(): return js("document.body.innerText || ''") or ''
def stop_guard(stage):
    low=body_text().casefold()
    bad=['checkpoint','captcha','temporarily blocked','tạm thời bị chặn','account restricted','tài khoản bị hạn chế','we limit how often','chúng tôi giới hạn tần suất','identity confirmation','xác nhận danh tính']
    hits=[x for x in bad if x in low]
    if hits: raise RuntimeError('STOP_GUARD '+stage+': '+','.join(hits))
def switch_identity(target, other):
    goto_url('https://www.facebook.com/'); wait_for_load(); time.sleep(3); stop_guard('identity_home')
    opened=js("(() => {{const e=[...document.querySelectorAll('[role=button]')].find(x=>(x.getAttribute('aria-label')||'')==='Your profile');if(!e)return false;e.click();return true}})()")
    if not opened: raise RuntimeError('Your profile button not found')
    time.sleep(2)
    already=js("(() => {{const label=%s;return [...document.querySelectorAll('[role=button]')].some(x=>(x.getAttribute('aria-label')||'').includes(label))}})()" % json.dumps('Switch to '+other))
    if already:
        press_key('ESC'); time.sleep(1); return True
    clicked=js("(() => {{const label=%s;const e=[...document.querySelectorAll('[role=button]')].find(x=>(x.getAttribute('aria-label')||'').includes(label));if(!e)return false;e.click();return true}})()" % json.dumps('Switch to '+target))
    if clicked: time.sleep(7)
    else: press_key('ESC'); time.sleep(1)
    opened=js("(() => {{const e=[...document.querySelectorAll('[role=button]')].find(x=>(x.getAttribute('aria-label')||'')==='Your profile');if(!e)return false;e.click();return true}})()")
    time.sleep(2)
    verified=js("(() => {{const label=%s;return [...document.querySelectorAll('[role=button]')].some(x=>(x.getAttribute('aria-label')||'').includes(label))}})()" % json.dumps('Switch to '+other))
    press_key('ESC'); time.sleep(1)
    if not opened or not verified: raise RuntimeError('Could not verify active identity '+target)
    return True

def parse_count(v):
    s=str(v or '').strip().replace(',','').casefold()
    if not s: return 0
    m=__import__('re').search(r'(\\d+(?:\\.\\d+)?)\\s*([km]?)',s)
    if not m: return 0
    n=float(m.group(1)); unit=m.group(2)
    return int(n*(1000 if unit=='k' else 1000000 if unit=='m' else 1))
def snapshot(index):
    return js('''(() => {{
      const arts=[...document.querySelectorAll('[role=article]')].filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
      const a=arts[%d]; if(!a)return null;
      const links=[...a.querySelectorAll('a[href]')];
      const profile=links.find(x=>{{const h=x.href||'';return h.includes('facebook.com/')&&!h.includes('/search/')&&!h.includes('/groups/')&&!h.includes('/posts/')&&!h.includes('/reel/')&&!h.includes('/videos/')&&!h.includes('story_fbid=')}});
      const direct=links.find(x=>{{const p=new URL(x.href,location.href).pathname.toLowerCase().replace(new RegExp('/+','g'),'/');return new RegExp('^/groups/[^/]+/(posts|permalink)/[^/]+/?$').test(p)||new RegExp('^/[^/]+/posts/[^/]+/?$').test(p)||new RegExp('^/reel/[^/]+/?$').test(p)||new RegExp('^/[^/]+/videos/[^/]+/?$').test(p);}});
      const buttons=[...a.querySelectorAll('[role=button]')];
      const num=(labels)=>{{const e=buttons.find(x=>labels.includes((x.getAttribute('aria-label')||'').trim())&&/\\\\d/.test((x.innerText||'')));return e?(e.innerText||'').trim():''}};
      const stamp=links.find(x=>(x.href||'').includes('__cft__')&&(x.href||'').includes('#?'));
      const stampAttrs=stamp?[stamp.getAttribute('title'),stamp.getAttribute('aria-label'),...[...stamp.querySelectorAll('[title],[aria-label],[data-utime]')].flatMap(x=>[x.getAttribute('title'),x.getAttribute('aria-label'),x.getAttribute('data-utime')])].filter(Boolean):[];
      return {{
        text:(a.innerText||'').slice(0,5000),
        author:(profile?((profile.innerText||'').trim()||profile.getAttribute('aria-label')||''):'').slice(0,160),
        author_url:profile?(profile.href||''):'',
        group_surface:links.some(x=>(x.href||'').includes('/groups/')),
        direct_post_url:direct?(direct.href||''):'',
        reactions:num(['Like','Thích']),
        comments:num(['Leave a comment','Bình luận']),
        shares:num(['Send this to friends or post it on your profile.','Chia sẻ']),
        stamp_attrs:stampAttrs,
      }};
    }})()''' % index)
def embed_code(index):
    ok=js('''(() => {{const arts=[...document.querySelectorAll('[role=article]')].filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length));const a=arts[%d];if(!a)return false;const b=[...a.querySelectorAll('[role=button]')].find(x=>['Actions for this post','Hành động cho bài viết này'].includes((x.getAttribute('aria-label')||'').trim()));if(!b)return false;b.click();return true}})()''' % index)
    if not ok: return ''
    time.sleep(1)
    embedded=js("(() => {{const e=[...document.querySelectorAll('[role=menuitem]')].find(x=>['Embed','Nhúng'].includes((x.innerText||'').trim()));if(!e)return false;e.click();return true}})()")
    if not embedded: press_key('ESC'); return ''
    time.sleep(3)
    code=js('''(() => {{const dialogs=[...document.querySelectorAll('[role=dialog]')].filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length));const d=dialogs.find(x=>/Embed|Nhúng/i.test(x.innerText||'')&&x.querySelector('input[value*="facebook.com/plugins/"]'));if(!d)return '';const i=d.querySelector('input[value*="facebook.com/plugins/"]');return i?i.value:''}})()''') or ''
    js('''(() => {{const dialogs=[...document.querySelectorAll('[role=dialog]')];const d=dialogs.find(x=>/Embed|Nhúng/i.test(x.innerText||'')&&x.querySelector('input[value*="facebook.com/plugins/"]'));if(!d)return false;const b=[...d.querySelectorAll('[role=button]')].find(x=>['Close','Đóng'].includes((x.getAttribute('aria-label')||'').trim()));if(!b)return false;b.click();return true}})()''')
    time.sleep(1)
    return code

try:
    switch_identity(identity,restore_identity)
    scan_urls=[]
    for query in queries:
        scan_urls.append({{'query': query, 'url': 'https://www.facebook.com/search/posts/?q='+urllib.parse.quote(query), 'forced_group': '', 'kind': 'global'}})
    for group in group_scans:
        for query in group.get('queries') or []:
            scan_urls.append({{'query': query, 'url': group['url'].rstrip('/') + '/search/?q=' + urllib.parse.quote(query), 'forced_group': group.get('name') or group['url'], 'kind': 'group'}})
    for page in page_scans:
        for query in page.get('queries') or []:
            scan_urls.append({{'query': query, 'url': page['url'], 'forced_group': '', 'forced_page': page.get('name') or page['url'], 'kind': 'page'}})
    seen=set()
    for scan in scan_urls:
        query=scan['query']
        if scan.get('kind') == 'page':
            goto_url(scan['url']); wait_for_load(); time.sleep(5); stop_guard('page')
            clicked=js("(() => {{const btn=[...document.querySelectorAll('[role=button],button,a[role=button]')].find(e=>((e.getAttribute('aria-label')||'').startsWith('Search ') || /Search this Page|Tìm kiếm/.test(e.innerText||'')) && !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)); if(!btn)return false; btn.click(); return true;}})()")
            if not clicked: continue
            time.sleep(1); type_text(query); press_key('ENTER'); time.sleep(5); stop_guard('page_search')
        else:
            goto_url(scan['url']); wait_for_load(); time.sleep(5); stop_guard('search')
        for _ in range(3): js("window.scrollBy(0,900)"); time.sleep(2)
        count=js("[...document.querySelectorAll('[role=article]')].filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)).length") or 0
        for index in range(min(int(count),max_results)):
            snap=snapshot(index)
            if not snap: continue
            low=(snap.get('text') or '').casefold()
            if any(x in low for x in ['sponsored','được tài trợ','send message','why am i seeing this ad','report ad']): continue
            code=embed_code(index)
            direct=snap.get('direct_post_url') or ''
            if not code and not direct: continue
            key=direct or code
            if key in seen: continue
            seen.add(key)
            snap.update({{'query':query,'surface':'group_post' if (scan.get('forced_group') or snap.get('group_surface')) else 'public_post','embed_code':code,'target_group':scan.get('forced_group') or '','target_page':scan.get('forced_page') or ''}})
            snap['engagement']={{'reactions':parse_count(snap.pop('reactions','')),'comments':parse_count(snap.pop('comments','')),'shares':parse_count(snap.pop('shares',''))}}
            results.append(snap)
finally:
    restored=switch_identity(restore_identity,identity)
print(json.dumps({{'ok':True,'restored':restored,'results':results}},ensure_ascii=False))
"""
    ensure_browser()
    env = dict(**os.environ)
    env['BU_CDP_URL'] = CDP
    discovery_timeout = int(os.environ.get('RB_COMMENT_DISCOVERY_TIMEOUT') or cfg.get('browser_timeout_seconds') or 150)
    try:
        proc = subprocess.run(
            [str(BROWSER_USE)],
            input=program,
            text=True,
            capture_output=True,
            env=env,
            timeout=max(45, min(discovery_timeout, 540)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        # A killed browser harness cannot run its generated finally block, so restore explicitly.
        restore_radar_identity()
        return []
    if proc.returncode != 0:
        combined = (proc.stdout or '') + '\n' + (proc.stderr or '')
        restore_radar_identity()
        hard_stop = re.search(
            r'STOP_GUARD|checkpoint|captcha|temporarily blocked|tạm thời bị chặn|account restricted|'
            r'tài khoản bị hạn chế|identity confirmation|xác nhận danh tính',
            combined,
            flags=re.I,
        )
        if hard_stop:
            raise RuntimeError('Facebook public-post discovery hit a hard stop\n' + combined[-4000:])
        return []
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    raw = json.loads(lines[-1])
    if not raw.get('restored'):
        raise RuntimeError('Facebook discovery did not restore Radar BDS identity')
    discovered = []
    for item in raw.get('results') or []:
        direct_url = str(item.pop('direct_post_url', '') or '')
        post_url = canonical_post_url(direct_url) if is_public_post_url(direct_url) else ''
        if not post_url:
            post_url = extract_facebook_post_url(str(item.pop('embed_code', '') or ''))
        else:
            item.pop('embed_code', None)
        if not post_url:
            continue
        item['post_url'] = post_url
        attrs = [normalize_text(x) for x in item.pop('stamp_attrs', []) if normalize_text(x)]
        item['timestamp_evidence'] = attrs
        # ISO/epoch evidence is preferred. Human labels remain in text for is_recent().
        for value in attrs:
            if value.isdigit() and len(value) >= 9:
                item['posted_at'] = dt.datetime.fromtimestamp(int(value), tz=now.tzinfo).isoformat()
                break
            parsed = parse_time(value, now.tzinfo)
            if parsed:
                item['posted_at'] = parsed.isoformat()
                break
        if attrs:
            item['text'] = str(item.get('text') or '') + '\n' + '\n'.join(attrs)
        discovered.append(item)
    unique = {}
    for item in discovered:
        unique[canonical_post_url(item['post_url'])] = item
    return list(unique.values())


def write_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(STATE)


def parse_executor_result(stdout: str) -> tuple[dict, dict]:
    record = json.loads(stdout)
    inner = [line for line in str(record.get('stdout', '')).splitlines() if line.strip()]
    return record, json.loads(inner[-1])


def valid_comment_permalink(value: str) -> bool:
    value = str(value or '')
    return value.startswith('https://www.facebook.com/') and ('comment_id=' in value or 'reply_comment_id=' in value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--article-slug')
    args = parser.parse_args()
    now = dt.datetime.now().astimezone()
    config = load_json(CONFIG)
    broker_data = load_json(BROKER_PROFILES)
    exclusions = load_broker_exclusions(broker_data)
    post_state = load_json(POST_STATE, {'actions': []}, missing_ok=True)
    state = load_json(STATE, {'schema': 'radar_public_post_comment_state.v1', 'actions': []}, missing_ok=True)
    campaign = article_campaign(config, args.article_slug) if args.article_slug else None
    if campaign and article_already_distributed(args.article_slug, state):
        if args.dry_run:
            print(json.dumps({'ok': True, 'skip': 'article_already_distributed', 'article_slug': args.article_slug}, ensure_ascii=False))
        return 0
    if daily_comment_cap_full(config, state, now):
        if args.dry_run:
            print(json.dumps({'ok': True, 'skip': 'daily_comment_cap', 'count': daily_comment_count(now, state)}, ensure_ascii=False))
        return 0
    if global_weekly_full(config, state, now):
        if args.dry_run:
            print(json.dumps({'ok': True, 'skip': 'global_weekly_comment_cap'}, ensure_ascii=False))
        return 0
    discovery_config = campaign_discovery_config(config, campaign) if campaign else config
    discovered = discover_posts(discovery_config, now=now)
    if campaign:
        allowed = set(campaign['locations'])
        discovered = [item for item in discovered if detect_location(str(item.get('text') or '')) in allowed]
    candidate, report = choose_candidate(config, state, discovered, now, exclusions)
    if not candidate:
        if args.dry_run:
            print(json.dumps({'ok': True, 'skip': 'no_eligible_public_post', 'discovery': report}, ensure_ascii=False, indent=2))
        return 0
    link = build_deal_link(candidate, config)
    if not landing_has_deals(link):
        if args.dry_run:
            print(json.dumps({'ok': True, 'skip': 'no_active_deal_signal_for_enabled_ward', 'candidate': candidate, 'link': link, 'discovery': report}, ensure_ascii=False, indent=2))
        return 0
    content_link = build_article_link(candidate, campaign) if campaign else link
    if campaign and not article_url_healthy(content_link):
        if args.dry_run:
            print(json.dumps({'ok': True, 'skip': 'article_url_unhealthy', 'article_slug': args.article_slug}, ensure_ascii=False))
        return 0
    comment = build_article_comment(candidate, campaign) if campaign else build_comment(candidate, config)
    queue = {
        'schema': 'radar_public_post_comment_queue.v1',
        'created_at': now.isoformat(timespec='seconds'),
        'target': {'platform': 'facebook', 'surface': 'facebook_comment', 'identity': 'Tiny Sudo'},
        'source': {
            'post_url': candidate['post_url'],
            'post_needle': candidate['post_needle'],
            'author': candidate['author'],
            'author_url': candidate.get('author_url') or '',
            'topic': candidate['topic'],
            'location': candidate['location'],
            'query': candidate['query'],
            'engagement': candidate['engagement'],
            'article_slug': args.article_slug or '',
        },
        'content': {
            'comment': comment,
            'link': content_link,
            'deal_signal_link': link,
            'link_policy': 'single_contextual_radar_link',
        },
        'guards': {
            'relevance_gate_passed': True,
            'broker_exclusion_passed': True,
            'relevance_score': candidate['score'],
            'min_reactions': int((config.get('global') or {}).get('min_reactions', 10)),
            'min_comments': int((config.get('global') or {}).get('min_comments', 3)),
            'same_author_cooldown_days': 30,
            'same_topic_cooldown_days': 14,
        },
        'evidence': {'post_text': candidate['post_text'][:3000], 'reasons': candidate['reasons']},
    }
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    post_id = re.sub(r'[^a-zA-Z0-9_-]+', '-', urllib.parse.urlparse(candidate['post_url']).path.strip('/'))[-100:]
    qpath = QUEUE_DIR / f'{now.date()}-{post_id}.json'
    qpath.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.dry_run or not args.publish:
        print(json.dumps({'ok': True, 'status': 'selected_for_review', 'queue': str(qpath), 'candidate': candidate, 'comment': comment, 'discovery': report}, ensure_ascii=False, indent=2))
        return 0
    proc = subprocess.run([str(EXECUTOR), '--queue', str(qpath), '--mode', 'publish', '--yes'], text=True, capture_output=True, timeout=480, check=False)
    if proc.returncode != 0:
        raise SystemExit('Comment publish failed\n' + proc.stdout[-5000:] + '\n' + proc.stderr[-5000:])
    record, result = parse_executor_result(proc.stdout)
    if result.get('status') != 'published':
        raise SystemExit('Unsupported executor result: ' + json.dumps(result, ensure_ascii=False))
    result_permalink = result.get('comment_permalink') or ''
    if not valid_comment_permalink(result_permalink):
        raise SystemExit('Publish verification failed: missing comment_id/reply_comment_id permalink')
    state_action = record.get('state_action') or {}
    if state_action.get('status') != 'published' or state_action.get('comment_permalink') != result_permalink:
        raise SystemExit('Executor state verification failed: published action was not recorded exactly once')
    if canonical_post_url(state_action.get('post_url') or '') != canonical_post_url(candidate['post_url']):
        raise SystemExit('Executor state verification failed: recorded post mismatch')
    print('@rb PUBLIC POST COMMENT SEEDING OK')
    print('Identity: Tiny Sudo')
    print(f'Bài đích: {candidate["post_url"]}')
    print(f'Comment: {comment}')
    print(f'Permalink: {result_permalink}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

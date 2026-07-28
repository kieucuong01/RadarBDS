#!/usr/bin/env python3
"""Prepare or publish one fail-closed Tiny Sudo comment on a Facebook post.

The legacy filename is retained for scheduler compatibility. Public posts and verified visible
group posts are eligible; private/inaccessible targets still fail closed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

BROWSER_USE = Path('/home/hermesops/radar-browser-use/.venv/bin/browser-use')
BROWSER_USE_CWD = Path('/home/hermesops/radar-browser-use')
DEFAULT_CDP_URL = 'http://127.0.0.1:9224'
DEFAULT_CONFIG = Path('/opt/radar-bds/current/config/social_group_comment_targets.json')
DEFAULT_BROKERS = Path('/opt/radar-bds/current/data/facebook_profiles.json')
DEFAULT_ARTIFACT_DIR = Path('/home/hermesops/radar-browser-use/artifacts/public-post-comment-seeding')
DEFAULT_RUN_DIR = Path('/opt/radar-bds/var/browser_use_runs/public-post-comment-seeding')
DEFAULT_POST_STATE = Path('/opt/radar-bds/var/social_queue/group-autopost/state.json')
DEFAULT_STATE = Path('/opt/radar-bds/var/social_queue/public-post-comment/state.json')


def load_json(path: Path, default=None, *, missing_ok: bool = False) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        if missing_ok:
            return default if default is not None else {}
        raise SystemExit(f'Refusing: unreadable or corrupt JSON {path}: file is missing')
    except Exception as exc:
        raise SystemExit(f'Refusing: unreadable or corrupt JSON {path}: {exc}')


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
    return 'https://www.facebook.com' + path.casefold() if path and path != '/' else ''


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


def extract_urls(text: str) -> list[str]:
    urls = re.findall(r'https?://[^\s<>"\']+', str(text or ''), flags=re.I)
    return [url.rstrip('.,;:!?)]}') for url in urls]


def contains_bare_domain(text: str) -> bool:
    without_urls = re.sub(r'https?://[^\s<>"\']+', ' ', str(text or ''), flags=re.I)
    label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    tld = r'(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})'
    domain = rf'(?:{label}\.)+{tld}'
    return bool(re.search(rf'\bwww\.\S+|\b{domain}\b(?:/\S*)?', without_urls, flags=re.I))


def validate_radar_link(value: str, config: dict) -> str:
    cfg = config.get('global') or {}
    try:
        parsed = urllib.parse.urlparse(str(value or ''))
    except Exception:
        raise SystemExit('Refusing: malformed comment link')
    allowed_host = str(cfg.get('allowed_link_host') or 'radarbds.vn').casefold()
    if parsed.scheme != 'https' or parsed.hostname != allowed_host or parsed.username or parsed.password or parsed.port:
        raise SystemExit('Refusing: comment link must use HTTPS on the exact allowlisted Radar host')
    query = urllib.parse.parse_qs(parsed.query)
    for key, expected in {'utm_source': 'facebook', 'utm_medium': 'comment'}.items():
        if query.get(key) != [expected]:
            raise SystemExit(f'Refusing: comment link requires {key}={expected}')
    if parsed.path.startswith('/tin-tuc/'):
        slug = parsed.path.removeprefix('/tin-tuc/').strip('/')
        campaign = next((row for row in config.get('article_redistribution') or [] if row.get('slug') == slug), None)
        if not campaign or parsed.path != f'/tin-tuc/{slug}':
            raise SystemExit('Refusing: article is not allowlisted for redistribution')
        if query.get('utm_campaign') != ['article_redistribution']:
            raise SystemExit('Refusing: article comment requires utm_campaign=article_redistribution')
        content = (query.get('utm_content') or [''])[0]
        if not content.startswith(slug + '-'):
            raise SystemExit('Refusing: article comment UTM content must identify the allowlisted slug')
        return str(value)
    for key, expected in {'date_range': '3m', 'mos_min': '10', 'utm_campaign': 'public_post_seeding'}.items():
        if query.get(key) != [expected]:
            raise SystemExit(f'Refusing: comment link requires {key}={expected}')
    if parsed.path != '/' or query.get('tab') != ['signals']:
        raise SystemExit('Refusing: unsupported Radar landing path')
    city = (query.get('city') or [''])[0]
    ward = (query.get('ward') or [''])[0]
    if not city or not ward:
        raise SystemExit('Refusing: enabled ward deal link requires both city and ward')
    coverage = config.get('deal_coverage') or {}
    enabled = any(
        city.casefold() == str(enabled_city).casefold()
        and any(ward.casefold() == str(enabled_ward).casefold() for enabled_ward in (wards if isinstance(wards, list) else []))
        for enabled_city, wards in coverage.items()
    )
    if not enabled:
        raise SystemExit('Refusing: city/ward is outside enabled comment-seeding coverage')
    return str(value)


def landing_has_deals(link: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(link)
        query = urllib.parse.parse_qs(parsed.query)
        params: list[tuple[str, str]] = [
            ('date_range', (query.get('date_range') or ['3m'])[0]),
            ('city', (query.get('city') or [''])[0]),
            ('ward', (query.get('ward') or [''])[0]),
            ('prop_type', 'dat_nen'),
            ('prop_type', 'nha_dat'),
            ('prop_type', 'chung_cu'),
            ('prop_type', 'nha_tro'),
            ('mos_min', (query.get('mos_min') or ['10'])[0]),
        ]
        endpoint = 'https://radarbds.vn/api/counts?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(endpoint, headers={'User-Agent': 'RadarBDS-Social-Guard/1.0'})
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 200:
                return False
            data = json.load(response)
        return int(((data or {}).get('stats') or {}).get('hot') or 0) >= 1
    except Exception:
        return False


def validate_config(config: dict) -> dict:
    cfg = config.get('global') or {}
    required = {
        'identity': 'Tiny Sudo',
        'editor_identity': 'Tiny',
        'restore_identity': 'Radar BDS',
        'automated_link_policy': 'single_contextual_radar_link',
    }
    for key, expected in required.items():
        if cfg.get(key) != expected:
            raise SystemExit(f'Refusing: config {key} must be {expected!r}')
    if not str(config.get('schema') or '').startswith('radar_social_public_post_comment.'):
        raise SystemExit('Refusing: Facebook comment schema is required')
    return cfg


def validate_comment(text: str, config: dict) -> str:
    validate_config(config)
    raw = str(text or '')
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise SystemExit('Refusing: comment contains newline, tab, or control characters')
    text = raw.strip()
    if not text:
        raise SystemExit('Refusing: empty comment')
    if len(text) > 500:
        raise SystemExit('Refusing: comment exceeds 500 characters')
    urls = extract_urls(text)
    if len(urls) != 1:
        raise SystemExit('Refusing: Tiny Sudo comment must contain exactly one HTTPS link')
    validate_radar_link(urls[0], config)
    if contains_bare_domain(text):
        raise SystemExit('Refusing: bare or additional domain is not allowed')
    forbidden = (
        'radar bds', 'cam kết lợi nhuận', 'giá thật 100%', 'pháp lý chuẩn 100%',
        'chốt nhanh', 'cơ hội vàng', 'deal ngon', 'lời chắc',
    )
    hits = [x for x in forbidden if x in text.casefold()]
    if hits:
        raise SystemExit('Refusing promotional or deceptive claim: ' + ', '.join(hits))
    return text


def validate_queue(queue: dict, config: dict) -> dict:
    cfg = validate_config(config)
    target = queue.get('target') or {}
    source = queue.get('source') or {}
    guards = queue.get('guards') or {}
    if target.get('surface') not in {'public_post_comment', 'facebook_comment'}:
        raise SystemExit('Refusing: queue target.surface must be facebook_comment')
    if target.get('identity') not in (None, 'Tiny Sudo'):
        raise SystemExit('Refusing: queue identity must be Tiny Sudo')
    post_url = str(source.get('post_url') or '')
    if not is_public_post_url(post_url):
        raise SystemExit('Refusing: source must be a direct Facebook post or group-post permalink')
    if not normalize_text(source.get('post_needle') or ''):
        raise SystemExit('Refusing: source.post_needle is required')
    if not normalize_text(source.get('author') or ''):
        raise SystemExit('Refusing: source.author is required')
    source_location = normalize_text(source.get('location') or '')
    if not source_location:
        raise SystemExit('Refusing: source.location is required')
    if not normalize_text(source.get('topic') or ''):
        raise SystemExit('Refusing: source.topic is required')
    if not guards.get('relevance_gate_passed'):
        raise SystemExit('Refusing: relevance gate evidence missing')
    if not guards.get('broker_exclusion_passed'):
        raise SystemExit('Refusing: broker exclusion evidence missing')
    engagement = source.get('engagement') or {}
    reactions = int(engagement.get('reactions') or 0)
    comments = int(engagement.get('comments') or 0)
    shares = int(engagement.get('shares') or 0)
    is_group_post = '/groups/' in post_url.casefold()
    min_reactions = int(cfg.get('group_post_min_reactions', 0) if is_group_post else cfg.get('min_reactions', 10))
    min_comments = int(cfg.get('group_post_min_comments', 0) if is_group_post else cfg.get('min_comments', 3))
    min_total = int(cfg.get('group_post_min_total_engagement', 0) if is_group_post else cfg.get('min_total_engagement', 15))
    if reactions < min_reactions:
        raise SystemExit('Refusing: source engagement is below min_reactions')
    if comments < min_comments:
        raise SystemExit('Refusing: source engagement is below min_comments')
    if reactions + comments + shares < min_total:
        raise SystemExit('Refusing: source engagement is below min_total_engagement')
    content = queue.get('content') or {}
    comment = validate_comment(content.get('comment') or '', config)
    urls = extract_urls(comment)
    if content.get('link_policy') != 'single_contextual_radar_link':
        raise SystemExit('Refusing: queue link policy mismatch')
    if content.get('link') != urls[0]:
        raise SystemExit('Refusing: queue link must exactly match the comment URL')
    link = validate_radar_link(str(content.get('link') or ''), config)
    parsed_link = urllib.parse.urlparse(link)
    link_query = urllib.parse.parse_qs(parsed_link.query)
    if parsed_link.path.startswith('/tin-tuc/'):
        article_slug = parsed_link.path.removeprefix('/tin-tuc/').strip('/')
        campaign = next((row for row in config.get('article_redistribution') or [] if row.get('slug') == article_slug), None)
        if source.get('article_slug') != article_slug or not campaign:
            raise SystemExit('Refusing: queue article slug does not match the allowlisted article link')
        if normalize_name(source_location) not in {normalize_name(x) for x in campaign.get('locations') or []}:
            raise SystemExit('Refusing: source location does not match the article campaign')
        signal_link = validate_radar_link(str(content.get('deal_signal_link') or ''), config)
        signal_query = urllib.parse.parse_qs(urllib.parse.urlparse(signal_link).query)
        if normalize_name(source_location) != normalize_name((signal_query.get('ward') or [''])[0]):
            raise SystemExit('Refusing: source.location must match the deal-signal guard ward')
    else:
        link_ward = (link_query.get('ward') or [''])[0]
        if normalize_name(source_location) != normalize_name(link_ward):
            raise SystemExit('Refusing: source.location must match the Radar link ward')
    return cfg


def validate_not_excluded(queue: dict, broker_data: dict) -> None:
    source = queue.get('source') or {}
    exclusions = load_broker_exclusions(broker_data)
    url = normalize_profile_url(source.get('author_url') or '')
    name = normalize_name(source.get('author') or '')
    if (url and url in exclusions['urls']) or (name and name in exclusions['names']):
        raise SystemExit('Refusing: target author is in data/facebook_profiles.json broker watchlist')


def parse_time(value: str, default_tz: dt.tzinfo | None = None) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz or dt.datetime.now().astimezone().tzinfo)
    return parsed


def canonical_post_url(value: str) -> str:
    raw = html.unescape(str(value or '').strip())
    if not is_public_post_url(raw):
        return ''
    parsed = urllib.parse.urlparse(raw)
    path = re.sub(r'/+', '/', parsed.path)
    return urllib.parse.urlunparse(('https', 'www.facebook.com', path.rstrip('/') + '/', '', '', ''))


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


def global_weekly_full(config: dict, state: dict, now: dt.datetime) -> bool:
    cap = int((config.get('global') or {}).get('max_comments_per_week', 3))
    count = 0
    for action in (state or {}).get('actions', []):
        at = parse_time(action.get('at', ''), now.tzinfo)
        if at:
            at = at.astimezone(now.tzinfo) if now.tzinfo else at.replace(tzinfo=None)
        if at and action.get('status') == 'published' and 0 <= (now - at).total_seconds() < 7 * 86400:
            count += 1
    return count >= cap


def source_cooldown_reason(source: dict, state: dict, now: dt.datetime, cfg: dict) -> str:
    post_url = canonical_post_url(source.get('post_url') or '')
    author_url = normalize_profile_url(source.get('author_url') or '')
    author_name = normalize_name(source.get('author') or '')
    location = normalize_name(source.get('location') or '')
    topic = normalize_name(source.get('topic') or '')
    article_slug = normalize_text(source.get('article_slug') or '')
    author_days = int(cfg.get('same_author_cooldown_days', 30))
    topic_days = int(cfg.get('same_topic_cooldown_days', 14))
    for action in (state or {}).get('actions', []):
        if action.get('status') in ('failed', 'skipped'):
            continue
        if article_slug and action.get('article_slug') == article_slug:
            return 'same_article'
        if post_url and canonical_post_url(action.get('post_url') or '') == post_url:
            return 'same_post'
        at = parse_time(action.get('at', ''), now.tzinfo)
        if not at:
            continue
        at = at.astimezone(now.tzinfo) if now.tzinfo else at.replace(tzinfo=None)
        age_days = (now - at).total_seconds() / 86400
        same_author = bool(
            (author_url and normalize_profile_url(action.get('author_url') or '') == author_url)
            or (author_name and normalize_name(action.get('author') or '') == author_name)
        )
        if same_author and age_days < author_days:
            return 'same_author_cooldown'
        if location and topic and normalize_name(action.get('location') or '') == location and normalize_name(action.get('topic') or '') == topic and age_days < topic_days:
            return 'same_topic_cooldown'
    return ''


def validate_executor_state_caps(queue: dict, config: dict, post_state: dict, comment_state: dict, now: dt.datetime | None = None) -> None:
    now = now or dt.datetime.now().astimezone()
    cfg = config.get('global') or {}
    if daily_comment_cap_full(config, comment_state, now):
        raise SystemExit('Refusing: daily public-post comment cap is already full')
    if global_weekly_full(config, comment_state, now):
        raise SystemExit('Refusing: global weekly public-post comment cap is already full')
    reason = source_cooldown_reason(queue.get('source') or {}, comment_state, now, cfg)
    if reason:
        raise SystemExit(f'Refusing: public-post comment dedupe/cooldown blocks this queue ({reason})')


def valid_comment_permalink(value: str) -> bool:
    value = str(value or '')
    return value.startswith('https://www.facebook.com/') and ('comment_id=' in value or 'reply_comment_id=' in value)


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def reserve_publish_action(state: dict, queue: dict, qpath: Path, now: dt.datetime) -> str:
    source = queue.get('source') or {}
    content = queue.get('content') or {}
    reservation_id = f'{now.isoformat(timespec="microseconds")}|{qpath}'
    action = {
        'reservation_id': reservation_id,
        'at': now.isoformat(timespec='seconds'),
        'identity': 'Tiny Sudo',
        'post_url': source.get('post_url') or '',
        'author': source.get('author') or '',
        'author_url': source.get('author_url') or '',
        'topic': source.get('topic') or '',
        'location': source.get('location') or '',
        'article_slug': source.get('article_slug') or '',
        'status': 'pending',
        'comment': content.get('comment') or '',
        'link': content.get('link') or '',
        'queue': str(qpath),
    }
    state.setdefault('actions', []).append(action)
    state['actions'] = state['actions'][-300:]
    return reservation_id


def finalize_publish_action(state: dict, reservation_id: str, status: str, *, result: dict | None = None, error: str = '') -> dict:
    matches = [a for a in state.get('actions', []) if a.get('reservation_id') == reservation_id]
    if len(matches) != 1:
        raise RuntimeError('Publish reservation is missing or ambiguous')
    action = matches[0]
    action['status'] = status
    if error:
        action['error'] = str(error)[-2000:]
    if result:
        action['comment_permalink'] = result.get('comment_permalink') or ''
        action['screenshot'] = result.get('screenshot') or ''
    return action


def parse_browser_result(stdout: str) -> dict:
    lines = [line for line in str(stdout or '').splitlines() if line.strip()]
    if not lines:
        raise RuntimeError('Browser executor returned no result')
    result = json.loads(lines[-1])
    if not isinstance(result, dict):
        raise RuntimeError('Browser executor returned invalid result')
    return result


def program(queue: dict, mode: str, screenshot: str, config: dict) -> str:
    cfg = validate_queue(queue, config)
    source = queue.get('source') or {}
    content = queue.get('content') or {}
    post_url = str(source.get('post_url') or '')
    post_needle = normalize_text(source.get('post_needle') or '')[:120]
    expected_author = normalize_text(source.get('author') or '')[:160]
    comment = validate_comment(content.get('comment') or '', config)
    comment_needle = comment[:90]
    identity = str(cfg['identity'])
    restore_identity = str(cfg['restore_identity'])
    editor_identity = str(cfg['editor_identity'])
    editor_label = 'Comment as ' + editor_identity
    permalink_expr = """(() => {
 const needle=%s;
 const anchors=[...document.querySelectorAll('a[href*="comment_id"],a[href*="reply_comment_id"]')];
 for(const a of anchors) { let p=a; for(let i=0;i<9&&p;i++,p=p.parentElement) { if((p.innerText||'').includes(needle)) return a.href; } }
 return '';
})()""" % json.dumps(comment_needle)

    return f"""
import json,time
post_url={post_url!r}
expected_author={expected_author!r}
post_needle={post_needle!r}
comment={comment!r}
comment_needle={comment_needle!r}
mode={mode!r}
screenshot={screenshot!r}
result=None
restored=False

def visible(e): return bool(e.offsetWidth or e.offsetHeight or e.getClientRects().length)
def body_text(): return js("document.body.innerText || ''") or ''
def stop_guard(stage):
    low=body_text().casefold()
    bad=['checkpoint','captcha','temporarily blocked','tạm thời bị chặn','account restricted','tài khoản bị hạn chế','we limit how often','chúng tôi giới hạn tần suất','identity confirmation','xác nhận danh tính']
    hits=[x for x in bad if x in low]
    if hits: raise RuntimeError('STOP_GUARD '+stage+': '+','.join(hits))
def switch_identity(target):
    other='Radar BDS' if target=='Tiny Sudo' else 'Tiny Sudo'
    goto_url('https://www.facebook.com/'); wait_for_load(); time.sleep(3); stop_guard('identity_home')
    opened=js("(() => {{const e=[...document.querySelectorAll('[role=button]')].find(x=>(x.getAttribute('aria-label')||'')==='Your profile');if(!e)return false;e.click();return true}})()")
    if not opened: raise RuntimeError('Your profile button not found')
    time.sleep(2)
    clicked=js("(() => {{const label=%s;const e=[...document.querySelectorAll('[role=button]')].find(x=>(x.getAttribute('aria-label')||'')===label);if(!e)return false;e.click();return true}})()" % json.dumps('Switch to '+target))
    if clicked: time.sleep(6)
    else: press_key('ESC'); time.sleep(1)
    opened=js("(() => {{const e=[...document.querySelectorAll('[role=button]')].find(x=>(x.getAttribute('aria-label')||'')==='Your profile');if(!e)return false;e.click();return true}})()")
    time.sleep(2)
    verified=js("(() => {{const label=%s;return [...document.querySelectorAll('[role=button]')].some(x=>(x.getAttribute('aria-label')||'')===label)}})()" % json.dumps('Switch to '+other))
    press_key('ESC'); time.sleep(1)
    if not opened or not verified: raise RuntimeError('Could not verify active identity '+target)
    return True

def editors():
    return js("[...document.querySelectorAll('[contenteditable=true][role=textbox]')].filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length) && ((e.getAttribute('aria-label')||'').startsWith(%s) || (e.getAttribute('aria-label')||'').startsWith(%s))).length" % (json.dumps({editor_label!r}),json.dumps({'Bình luận dưới tên ' + editor_identity!r})))
def focus_editor():
    return js("(() => {{const labels=[%s,%s];const es=[...document.querySelectorAll('[contenteditable=true][role=textbox]')].filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&labels.some(x=>(e.getAttribute('aria-label')||'').startsWith(x)));if(es.length!==1)return es.length;es[0].focus();return 1}})()" % (json.dumps({editor_label!r}),json.dumps({'Bình luận dưới tên ' + editor_identity!r})))
def rendered_comment_count():
    return js("(() => {{const needle=%s;return [...document.querySelectorAll('[role=article]')].filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&(e.innerText||'').includes(needle)).length}})()" % json.dumps(comment_needle))

try:
    switch_identity('Tiny Sudo')
    new_tab(post_url); wait_for_load(); time.sleep(6); stop_guard('post_load')
    text=body_text()
    if expected_author not in text: raise RuntimeError('Expected author not found on target post')
    if post_needle not in text: raise RuntimeError('Target post needle not found')
    low=text.casefold()
    if 'commenting has been turned off' in low or 'đã tắt tính năng bình luận' in low:
        raise RuntimeError('Commenting is turned off for target post')
    count=editors()
    if count != 1: raise RuntimeError('Expected exactly one visible {editor_label} editor, found '+str(count))
    if focus_editor() != 1: raise RuntimeError('Could not focus {editor_label} editor')
    before_comment_count=rendered_comment_count()
    type_text(comment); time.sleep(2); stop_guard('comment_prepared')
    capture_screenshot(path=screenshot,full=False,max_dim=1800)
    if mode=='prepare':
        press_key('a',modifiers=2); press_key('Backspace'); time.sleep(1)
        editor_after_clear=js("(() => {{const labels=[%s,%s];const es=[...document.querySelectorAll('[contenteditable=true][role=textbox]')].filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&labels.some(x=>(e.getAttribute('aria-label')||'').startsWith(x)));return es.length===1?(es[0].innerText||'').trim():'__EDITOR_COUNT_ERROR__'}})()" % (json.dumps({editor_label!r}),json.dumps({'Bình luận dưới tên ' + editor_identity!r})))
        if editor_after_clear: raise RuntimeError('Prepare cleanup failed: editor is not empty')
        result={{'ok':True,'status':'prepared_and_cleared','identity':'Tiny Sudo','post_url':post_url,'comment':comment,'screenshot':screenshot}}
    elif mode=='publish':
        sent=js("(() => {{const labels=[%s,%s];const es=[...document.querySelectorAll('[contenteditable=true][role=textbox]')].filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&labels.some(x=>(e.getAttribute('aria-label')||'').startsWith(x)));if(es.length!==1)return false;let p=es[0];for(let depth=0;depth<8&&p;depth++,p=p.parentElement){{const btns=[...p.querySelectorAll('[role=button],[aria-label]')].filter(b=>!!(b.offsetWidth||b.offsetHeight||b.getClientRects().length));const send=btns.find(b=>/^(Comment|Bình luận|Post|Đăng|Send|Gửi)$/i.test((b.getAttribute('aria-label')||'').trim())&&!b.getAttribute('aria-disabled'));if(send){{send.click();return true;}}}}return false;}})()" % (json.dumps({editor_label!r}),json.dumps({'Bình luận dưới tên ' + editor_identity!r})))
        if not sent: press_key('ENTER')
        time.sleep(7); stop_guard('after_comment')
        editor_text=js("(() => {{const labels=[%s,%s];const es=[...document.querySelectorAll('[contenteditable=true][role=textbox]')].filter(e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&labels.some(x=>(e.getAttribute('aria-label')||'').startsWith(x)));return es.length===1?(es[0].innerText||'').trim():''}})()" % (json.dumps({editor_label!r}),json.dumps({'Bình luận dưới tên ' + editor_identity!r})))
        text=body_text(); after_comment_count=rendered_comment_count()
        if comment_needle not in text or comment_needle in (editor_text or '') or after_comment_count <= before_comment_count:
            raise RuntimeError('Comment submit attempted but a new persistent rendered Tiny comment was not verified')
        permalink=js({permalink_expr!r})
        if not permalink or ('comment_id=' not in permalink and 'reply_comment_id=' not in permalink):
            raise RuntimeError('Comment submit verified but no comment_id/reply_comment_id permalink was found')
        capture_screenshot(path=screenshot,full=False,max_dim=1800)
        result={{'ok':True,'status':'published','identity':'Tiny Sudo','post_url':post_url,'comment_permalink':permalink,'comment':comment,'screenshot':screenshot}}
    else:
        raise RuntimeError('Unsupported mode')
finally:
    restored=switch_identity('Radar BDS')
if not restored: raise RuntimeError('Radar BDS identity restore failed')
print(json.dumps(result,ensure_ascii=False))
"""


def run(args: argparse.Namespace) -> dict:
    qpath = Path(args.queue).resolve()
    queue = load_json(qpath)
    config = load_json(Path(args.targets))
    broker_data = load_json(Path(args.brokers))
    validate_queue(queue, config)
    validate_not_excluded(queue, broker_data)
    post_state = load_json(Path(args.post_state), {'actions': []}, missing_ok=True)
    comment_state = load_json(Path(args.state), {'schema': 'radar_public_post_comment_state.v1', 'actions': []}, missing_ok=True)
    validate_executor_state_caps(queue, config, post_state, comment_state)
    content = queue.get('content') or {}
    if not landing_has_deals(str(content.get('deal_signal_link') or content.get('link') or '')):
        raise SystemExit('Refusing: linked ward currently has no active Radar deal signal')
    if args.mode == 'publish' and not args.yes:
        raise SystemExit('Refusing publish without --yes')
    now = dt.datetime.now().astimezone()
    stamp = now.strftime('%Y%m%d-%H%M%S')
    state_path = Path(args.state)
    reservation_id = ''
    if args.mode == 'publish':
        reservation_id = reserve_publish_action(comment_state, queue, qpath, now)
        write_state(state_path, comment_state)
    artifact_dir = Path(args.artifact_dir)
    run_dir = Path(args.run_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshot = str(artifact_dir / f'{stamp}-tiny-sudo-{args.mode}.png')
    env = os.environ.copy()
    env['BU_CDP_URL'] = args.cdp_url
    proc = subprocess.run(
        [str(BROWSER_USE)],
        input=program(queue, args.mode, screenshot, config),
        text=True,
        capture_output=True,
        env=env,
        cwd=str(BROWSER_USE_CWD),
        timeout=args.timeout,
        check=False,
    )
    record = {
        'queue': str(qpath),
        'mode': args.mode,
        'identity': 'Tiny Sudo',
        'post_url': (queue.get('source') or {}).get('post_url'),
        'returncode': proc.returncode,
        'stdout': proc.stdout[-6000:],
        'stderr': proc.stderr[-6000:],
        'screenshot': screenshot,
    }
    log = run_dir / f'{stamp}-tiny-sudo-{args.mode}.json'
    if proc.returncode != 0:
        if reservation_id:
            finalize_publish_action(comment_state, reservation_id, 'failed', error=proc.stderr or proc.stdout)
            write_state(state_path, comment_state)
        log.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(record, ensure_ascii=False, indent=2))
        raise SystemExit(proc.returncode)
    result = parse_browser_result(proc.stdout)
    record['result'] = result
    if args.mode == 'publish':
        if result.get('status') != 'published' or not valid_comment_permalink(result.get('comment_permalink') or ''):
            finalize_publish_action(comment_state, reservation_id, 'failed', error='Browser result lacked verified published permalink')
            write_state(state_path, comment_state)
            raise SystemExit('Publish verification failed: missing persistent comment permalink')
        action = finalize_publish_action(comment_state, reservation_id, 'published', result=result)
        write_state(state_path, comment_state)
        record['state_action'] = action
    elif result.get('status') != 'prepared_and_cleared':
        raise SystemExit('Prepare verification failed: unsupported browser result')
    log.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--queue', required=True)
    p.add_argument('--mode', choices=['prepare', 'publish'], default='prepare')
    p.add_argument('--yes', action='store_true')
    p.add_argument('--targets', default=str(DEFAULT_CONFIG))
    p.add_argument('--brokers', default=str(DEFAULT_BROKERS))
    p.add_argument('--post-state', default=str(DEFAULT_POST_STATE))
    p.add_argument('--state', default=str(DEFAULT_STATE))
    p.add_argument('--cdp-url', default=DEFAULT_CDP_URL)
    p.add_argument('--artifact-dir', default=str(DEFAULT_ARTIFACT_DIR))
    p.add_argument('--run-dir', default=str(DEFAULT_RUN_DIR))
    p.add_argument('--timeout', type=int, default=420)
    run(p.parse_args())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

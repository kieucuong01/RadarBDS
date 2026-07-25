#!/usr/bin/env python3
"""Discover and safely seed value-first comments in allowlisted Facebook groups."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path('/opt/radar-bds/current')
CONFIG = REPO / 'config/social_group_comment_targets.json'
EXECUTOR = REPO / 'scripts/browser_use_group_comment.py'
START_BROWSER = Path('/home/hermesops/radar-browser-use/start-radar-social-browser.sh')
BROWSER_USE = Path('/home/hermesops/radar-browser-use/.venv/bin/browser-use')
CDP = 'http://127.0.0.1:9224'
POST_STATE = Path('/opt/radar-bds/var/social_queue/group-autopost/state.json')
STATE = Path('/opt/radar-bds/var/social_queue/group-comment/state.json')
QUEUE_DIR = Path('/opt/radar-bds/var/social_queue/group-comment/queue')

LOCATIONS = [
    'Phú Mỹ', 'Phú Lợi', 'Phú Hòa', 'Phú Tân', 'Phú Cường', 'Tân An', 'Hiệp An',
    'Hiệp Thành', 'Định Hòa', 'Chánh Mỹ', 'Chánh Nghĩa', 'Hòa Phú', 'Tương Bình Hiệp',
    'Dĩ An', 'Đông Hòa', 'Tân Đông Hiệp', 'Bình An', 'An Bình', 'Thuận An', 'Lái Thiêu',
    'Bình Chuẩn', 'Thuận Giao', 'An Phú', 'Phú An', 'An Tây', 'An Điền', 'Mỹ Phước',
    'Tân Định', 'Thới Hòa', 'Hòa Lợi', 'Chánh Phú Hòa', 'Bến Cát', 'Bình Dương',
]


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


def facebook_group_id_from_url(value: str) -> str:
    match = re.search(r'https://www\.facebook\.com/groups/([^/?#]+)/', norm_url(value), flags=re.I)
    return match.group(1) if match else ''


def norm_url(value: str) -> str:
    return str(value or '').split('?', 1)[0].rstrip('/') + '/'


def contains_link(text: str) -> bool:
    label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    tld = r'(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})'
    domain = rf'(?:{label}\.)+{tld}'
    return bool(re.search(rf'https?://\S+|\bwww\.\S+|\b{domain}\b(?:/\S*)?', str(text or ''), flags=re.I))


def normalize_text(value: str) -> str:
    return re.sub(r'\s+', ' ', str(value or '').replace('\ufeff', ' ')).strip()


def is_recent(text: str, now: dt.datetime, max_age_hours: int = 72) -> bool:
    low = text.casefold()
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
    if re.search(r'\b(?:a|an|about an?)\s+minute\s+ago\b', low):
        return max_age_hours >= 1 / 60
    if re.search(r'\b(?:a|an|about an?)\s+hour\s+ago\b', low):
        return max_age_hours >= 1
    if re.search(r'\ba day\s+ago\b|\b(?:yesterday|hôm qua)\b', low):
        return max_age_hours >= 24
    if re.search(r'\b(?:just now|vừa xong)\b', low):
        return True
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
                return 0 <= age_days and age_days * 24 < max_age_hours
            except ValueError:
                return False
    return False


def extract_author(text: str) -> str:
    skip = {'search results', 'filters', 'recent posts', 'posts you\'ve seen'}
    for line in str(text or '').splitlines():
        value = normalize_text(line)
        if value and value.casefold() not in skip:
            return value[:120]
    return ''


def detect_location(text: str) -> str:
    low = text.casefold()
    for location in LOCATIONS:
        if location.casefold() in low:
            return location
    return ''


def detect_topic(text: str) -> str:
    low = text.casefold()
    if any(x in low for x in ('giá', 'bao nhiêu', 'giá/m²', 'giá/m2', 'so giá', 'tỷ', 'triệu/m')):
        return 'price_compare'
    if any(x in low for x in ('pháp lý', 'quy hoạch', 'sổ hồng', 'sổ đỏ', 'thổ cư', 'đặt cọc')):
        return 'legal'
    if any(x in low for x in ('có nên mua', 'mua được không', 'nên kiểm tra gì', 'kinh nghiệm mua')):
        return 'buying_check'
    return 'other'


def post_needle(text: str) -> str:
    ignored = ('comment as radar bds', 'see more', 'see translation', 'like', 'reply', 'share')
    lines = []
    for raw in str(text or '').splitlines()[1:]:
        line = normalize_text(raw)
        low = line.casefold()
        if not line or any(low == x or low.startswith(x) for x in ignored):
            continue
        if re.fullmatch(r'[·\s]+|\d+|\d+\s+(?:hours?|days?|minutes?)\s+ago', low):
            continue
        lines.append(line)
    return max(lines, key=len, default='')[:120]


def score_candidate(text: str, now: dt.datetime | None = None, max_age_hours: int = 72) -> dict:
    now = now or dt.datetime.now().astimezone()
    text = str(text or '')
    low = text.casefold()
    reasons: list[str] = []
    author = extract_author(text)
    topic = detect_topic(text)
    location = detect_location(text)
    recent = is_recent(text, now, max_age_hours=max_age_hours)
    comments_off = 'commenting has been turned off' in low or 'đã tắt tính năng bình luận' in low
    self_ask_patterns = [
        r'cho\s+(?:em|mình|tôi|anh|chị)\s+hỏi',
        r'xin(?:\s+mọi\s+người)?\s+tư\s+vấn',
        r'nhờ(?:\s+mọi\s+người)?\s+tư\s+vấn',
        r'(?:em|mình|tôi)\s+đang\s+(?:xem|tìm|mua|phân vân)',
    ]
    self_ask = any(re.search(p, low) for p in self_ask_patterns)
    sales_patterns = [r'\b0\d{8,10}\b', r'\bliên hệ\b', r'\bsđt\b', r'\bbán gấp\b', r'\bgiá chỉ\b', r'\bchốt ngay\b', r'\binbox\b', r'\bký gửi\b']
    sales_heavy = any(re.search(p, low) for p in sales_patterns)
    score = 0
    if self_ask:
        score += 4
    else:
        reasons.append('no_explicit_self_question')
    if '?' in text:
        score += 1
    if topic != 'other':
        score += 2
    else:
        reasons.append('unsupported_topic')
    if location:
        score += 2
    if recent:
        score += 1
    else:
        reasons.append('not_recent')
    if comments_off:
        reasons.append('comments_off')
    if sales_heavy:
        reasons.append('sales_heavy')
        score -= 4
    eligible = score >= 7 and not any(x in reasons for x in ('comments_off', 'sales_heavy', 'not_recent', 'no_explicit_self_question', 'unsupported_topic'))
    return {
        'eligible': eligible,
        'score': score,
        'reasons': reasons,
        'author': author,
        'topic': topic,
        'location': location,
        'post_needle': post_needle(text),
        'post_text': text[:5000],
    }


def daily_action_taken(now: dt.datetime, post_state: dict, comment_state: dict) -> bool:
    tz = now.tzinfo or dt.datetime.now().astimezone().tzinfo
    for state in (post_state, comment_state):
        for action in state.get('actions', []):
            at = parse_time(action.get('at', ''), tz)
            if not at:
                continue
            if at.astimezone(tz).date() == now.date() and action.get('status') not in ('failed', 'skipped'):
                return True
    return False


def candidate_already_used(candidate: dict, state: dict, now: dt.datetime) -> bool:
    for action in state.get('actions', []):
        at = parse_time(action.get('at', ''), now.tzinfo)
        if action.get('post_url') == candidate.get('post_url'):
            return True
        if not at:
            continue
        at = at.astimezone(now.tzinfo) if now.tzinfo else at.replace(tzinfo=None)
        age_days = (now - at).total_seconds() / 86400
        if action.get('author') and action.get('author') == candidate.get('author') and age_days < 30:
            return True
        if action.get('target_id') == candidate.get('target_id') and action.get('topic') == candidate.get('topic') and age_days < 14:
            return True
    return False


def target_weekly_full(target: dict, state: dict, now: dt.datetime) -> bool:
    count = 0
    for action in state.get('actions', []):
        at = parse_time(action.get('at', ''), now.tzinfo)
        if at:
            at = at.astimezone(now.tzinfo) if now.tzinfo else at.replace(tzinfo=None)
        if at and action.get('target_id') == target.get('id') and action.get('status') == 'published' and (now - at).total_seconds() < 7 * 86400:
            count += 1
    return count >= int(target.get('max_comments_per_week', 1))


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


def build_comment(candidate: dict, target: dict) -> str:
    location = candidate.get('location') or 'khu vực này'
    topic = candidate.get('topic')
    if topic == 'price_compare':
        text = (
            f'Radar BDS góp một cách kiểm tra ở {location}: trước hết tách đúng loại hình BĐS, '
            'lấy giá rao chia cho diện tích trên sổ để ra giá/m², rồi so với 5–10 tin cùng phường '
            'có cùng loại hình. Đừng kết luận chỉ từ giá tổng vì đất nền và nhà đất không nên gộp chung. '
            'Bên mình là trang tổng hợp dữ liệu giá rao, nên đây chỉ là bước lọc ban đầu; vẫn cần kiểm tra '
            'thực tế, quy hoạch và giấy tờ.'
        )
    elif topic == 'legal':
        text = (
            f'Radar BDS góp một checklist cho trường hợp ở {location}: đối chiếu người đứng tên trên sổ, '
            'mục đích sử dụng đất, phần diện tích thổ cư, thông tin quy hoạch/lộ giới và tình trạng thế chấp '
            'trước khi đặt cọc. Bên mình chỉ tổng hợp dữ liệu giá rao để lọc ban đầu, không thay việc xác minh '
            'hồ sơ tại cơ quan có thẩm quyền.'
        )
    else:
        text = (
            f'Radar BDS góp một góc kiểm tra ở {location}: hãy so ít nhất 5–10 tin cùng loại hình, cùng phường; '
            'quy đổi về giá/m²; sau đó kiểm tra đường vào, hiện trạng, quy hoạch và giấy tờ trước khi đi xem. '
            'Bên mình là trang tổng hợp dữ liệu giá rao, nên không xem một tin rẻ hơn là đủ để kết luận nên mua.'
        )
    if contains_link(text):
        raise ValueError('Automated comment must not contain a link')
    return text[:700]


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


def discover_posts(config: dict) -> list[dict]:
    requests = []
    for target in config.get('targets', []):
        if not target.get('comment_enabled'):
            continue
        for query in target.get('queries', []):
            group_id = str(target.get('group_id') or '').strip()
            if not group_id:
                raise RuntimeError(f'Comment target missing explicit group_id: {target.get("id")}')
            url = str(target['url']).rstrip('/') + '/search/?q=' + urllib.parse.quote(str(query))
            requests.append({'target_id': target['id'], 'group': target['name'], 'group_id': group_id, 'url': url, 'query': query})
    if not requests:
        return []
    article_expr = """(() => [...document.querySelectorAll('[role=article]')].slice(0,12).map(a => ({text:(a.innerText||'').slice(0,5000),links:[...a.querySelectorAll('a[href]')].map(x=>x.href).filter(h=>h.includes('/groups/')&&h.includes('/posts/')).slice(0,3)})))()"""
    program = f"""
import json,time
requests={requests!r}
out=[]
def body_text(): return js("document.body.innerText || ''") or ''
for req in requests:
    goto_url(req['url']); time.sleep(5)
    body=body_text(); low=body.casefold()
    bad=['checkpoint','captcha','temporarily blocked','tạm thời bị chặn','account restricted','tài khoản bị hạn chế','we limit how often','chúng tôi giới hạn tần suất']
    hits=[x for x in bad if x in low]
    if hits: raise RuntimeError('STOP_GUARD discovery: '+','.join(hits))
    if req['group'] not in body: raise RuntimeError('Expected group name missing in search results')
    identity_ok='Comment as Radar BDS' in body or 'Bình luận dưới tên Radar BDS' in body
    articles=js({article_expr!r})
    out.append({{'request':req,'identity_ok':identity_ok,'articles':articles}})
print(json.dumps(out,ensure_ascii=False))
"""
    ensure_browser()
    env = dict(**__import__('os').environ)
    env['BU_CDP_URL'] = CDP
    proc = subprocess.run([str(BROWSER_USE)], input=program, text=True, capture_output=True, env=env, timeout=360, check=False)
    if proc.returncode != 0:
        raise RuntimeError('Facebook discovery failed\n' + proc.stdout[-3000:] + '\n' + proc.stderr[-3000:])
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    raw = json.loads(lines[-1])
    discovered: list[dict] = []
    for batch in raw:
        if not batch.get('identity_ok'):
            continue
        req = batch['request']
        for article in batch.get('articles') or []:
            links = article.get('links') or []
            if not links:
                continue
            post_url = str(links[0]).split('?', 1)[0].rstrip('/') + '/'
            if facebook_group_id_from_url(post_url) != req['group_id']:
                continue
            discovered.append({
                'target_id': req['target_id'],
                'group': req['group'],
                'query': req['query'],
                'post_url': post_url,
                'text': article.get('text') or '',
            })
    unique = {}
    for item in discovered:
        unique[(item['target_id'], item['post_url'])] = item
    return list(unique.values())


def choose_candidate(config: dict, state: dict, discovered: list[dict], now: dt.datetime) -> tuple[dict | None, dict]:
    targets = {x['id']: x for x in config.get('targets', []) if x.get('comment_enabled')}
    max_age_hours = int((config.get('global') or {}).get('max_comment_age_hours', 72))
    rejected = Counter()
    accepted = []
    for item in discovered:
        target = targets.get(item.get('target_id'))
        if not target:
            rejected['target_disabled'] += 1
            continue
        if target_weekly_full(target, state, now):
            rejected['weekly_target_cap'] += 1
            continue
        scored = score_candidate(item.get('text') or '', now=now, max_age_hours=max_age_hours)
        candidate = dict(item, **scored)
        if not scored['eligible']:
            rejected.update(scored['reasons'] or ['below_score'])
            continue
        if candidate_already_used(candidate, state, now):
            rejected['dedupe_or_cooldown'] += 1
            continue
        accepted.append(candidate)
    accepted.sort(key=lambda x: (x['score'], len(x.get('post_text') or '')), reverse=True)
    return (accepted[0] if accepted else None), {'inspected': len(discovered), 'eligible': len(accepted), 'rejected': dict(rejected)}


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
    args = parser.parse_args()
    now = dt.datetime.now().astimezone()
    config = load_json(CONFIG)
    post_state = load_json(POST_STATE, {'actions': []}, missing_ok=True)
    state = load_json(STATE, {'schema': 'radar_group_comment_state.v1', 'actions': []}, missing_ok=True)
    if daily_action_taken(now, post_state, state):
        if args.dry_run:
            print(json.dumps({'ok': True, 'skip': 'shared_daily_group_action_cap'}, ensure_ascii=False))
        return 0
    if global_weekly_full(config, state, now):
        if args.dry_run:
            print(json.dumps({'ok': True, 'skip': 'global_weekly_comment_cap'}, ensure_ascii=False))
        return 0
    discovered = discover_posts(config)
    candidate, report = choose_candidate(config, state, discovered, now)
    if not candidate:
        if args.dry_run:
            print(json.dumps({'ok': True, 'skip': 'no_eligible_post', 'discovery': report}, ensure_ascii=False, indent=2))
        return 0
    target = next(x for x in config['targets'] if x['id'] == candidate['target_id'])
    comment = build_comment(candidate, target)
    queue = {
        'schema': 'radar_group_comment_queue.v1',
        'created_at': now.isoformat(timespec='seconds'),
        'target': {'platform': 'facebook', 'surface': 'group_comment', 'page_url': target['url'], 'name': target['name'], 'group_id': target.get('group_id')},
        'source': {
            'post_url': candidate['post_url'],
            'target_group_id': target.get('group_id'),
            'post_needle': candidate['post_needle'],
            'author': candidate['author'],
            'topic': candidate['topic'],
            'location': candidate['location'],
            'query': candidate['query'],
        },
        'content': {'comment': comment, 'link_policy': 'no_link'},
        'guards': {
            'relevance_gate_passed': True,
            'relevance_score': candidate['score'],
            'transparent_identity': True,
            'shared_daily_cap': 1,
            'same_author_cooldown_days': 30,
            'same_topic_cooldown_days': 14,
        },
        'evidence': {'post_text': candidate['post_text'][:3000], 'reasons': candidate['reasons']},
    }
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    post_id = candidate['post_url'].rstrip('/').rsplit('/', 1)[-1]
    qpath = QUEUE_DIR / f'{now.date()}-{target["id"]}-{post_id}.json'
    qpath.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.dry_run or not args.publish:
        print(json.dumps({'ok': True, 'status': 'selected_for_review', 'queue': str(qpath), 'candidate': candidate, 'comment': comment, 'discovery': report}, ensure_ascii=False, indent=2))
        return 0
    proc = subprocess.run([str(EXECUTOR), '--queue', str(qpath), '--mode', 'publish', '--yes'], text=True, capture_output=True, timeout=360, check=False)
    if proc.returncode != 0:
        raise SystemExit('Comment publish failed\n' + proc.stdout[-5000:] + '\n' + proc.stderr[-5000:])
    record, result = parse_executor_result(proc.stdout)
    if result.get('status') != 'published':
        raise SystemExit('Unsupported executor result: ' + json.dumps(result, ensure_ascii=False))
    result_permalink = result.get('comment_permalink') or ''
    if not valid_comment_permalink(result_permalink):
        raise SystemExit('Publish verification failed: missing comment_id/reply_comment_id permalink')
    action = {
        'at': now.isoformat(timespec='seconds'),
        'target_id': target['id'],
        'group': target['name'],
        'post_url': candidate['post_url'],
        'author': candidate['author'],
        'topic': candidate['topic'],
        'location': candidate['location'],
        'status': 'published',
        'comment': comment,
        'comment_permalink': result_permalink,
        'queue': str(qpath),
        'screenshot': result.get('screenshot') or record.get('screenshot') or '',
        'relevance_score': candidate['score'],
    }
    state.setdefault('actions', []).append(action)
    state['actions'] = state['actions'][-300:]
    write_state(state)
    print('@rb GROUP COMMENT SEEDING OK')
    print(f'Group: {target["name"]}')
    print(f'Bài đích: {candidate["post_url"]}')
    print(f'Comment: {comment}')
    print(f'Permalink: {action["comment_permalink"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

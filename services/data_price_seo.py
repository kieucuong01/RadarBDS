"""Read-only asking-price cohorts and immutable shared facts; never changes visibility.

Registered wards share a named parent. Runtime JSON is NOT tracked. Frozen
registry versions stay readable; price history events are not an observation panel.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import tempfile
from zoneinfo import ZoneInfo

from config.seo_locations import TDM_LIVE_WARDS
from services.signal_quality import ACTIONABLE_SUPPRESS_FLAGS, split_quality_flags

TZ = ZoneInfo('Asia/Ho_Chi_Minh')
CONTRACT = 'asking-price-observed-mtd-v1'
SOURCES = ('facebook', 'guland')
SCOPES = {
    'phu-loi': {'name':'Phú Lợi', 'wards':('Phú Lợi',), 'parent':'thu-dau-mot'},
    'hiep-thanh': {'name':'Hiệp Thành', 'wards':('Hiệp Thành',), 'parent':'thu-dau-mot'},
    'phu-my': {'name':'Phú Mỹ', 'wards':('Phú Mỹ',), 'parent':'thu-dau-mot'},
    'tan-an': {'name':'Tân An', 'wards':('Tân An',), 'parent':'thu-dau-mot'},
    'phu-hoa': {'name':'Phú Hòa', 'wards':('Phú Hòa',), 'parent':'thu-dau-mot'},
    'dinh-hoa': {'name':'Định Hòa', 'wards':('Định Hòa',), 'parent':'thu-dau-mot'},
    'phu-tan': {'name':'Phú Tân', 'wards':('Phú Tân',), 'parent':'thu-dau-mot'},
    'hiep-an': {'name':'Hiệp An', 'wards':('Hiệp An',), 'parent':'thu-dau-mot'},
    'tuong-binh-hiep': {'name':'Tương Bình Hiệp', 'wards':('Tương Bình Hiệp',), 'parent':'thu-dau-mot'},
    'chanh-nghia': {'name':'Chánh Nghĩa', 'wards':('Chánh Nghĩa',), 'parent':'thu-dau-mot'},
    'thu-dau-mot': {'name':'Thủ Dầu Một', 'wards':tuple(TDM_LIVE_WARDS.values()), 'parent':None},
}
SCOPE_REGISTRY_VERSION = 4
# V1 has no version member. Never infer its coverage from the current registry.
SCOPE_REGISTRIES = {
    1: frozenset(('phu-loi', 'thu-dau-mot')),
    2: frozenset(('phu-loi', 'hiep-thanh', 'phu-my', 'tan-an', 'thu-dau-mot')),
    3: frozenset(('phu-loi', 'hiep-thanh', 'phu-my', 'tan-an', 'phu-hoa', 'dinh-hoa', 'phu-tan', 'thu-dau-mot')),
    4: frozenset(SCOPES),
}
POLICY = {
    'sources':list(SOURCES), 'property_type':'dat_nen', 'tx_type':'ban',
    'sample_identity':'listing_id_after_current_known_duplicate_exclusions',
    'time_basis':'latest_known_price_of_records_last_seen_in_current_month',
    'active_basis':'is_active=1_within_qualified_monthly_cohort',
    'history_basis':'frozen_observed_mtd_snapshots_only_not_price_history_events',
    'min_samples':15, 'price_consistency_relative_tolerance':0.01,
    'excluded_flags':sorted(ACTIONABLE_SUPPRESS_FLAGS),
    'excluded_states':['blacklisted','review_hidden','known_duplicate','possibly_duplicate',
                       'outlier','bait','probably_sold','inactive_source','invalid_measurements'],
}


def snapshot_root():
    return Path('/opt/radar-bds/current/reports/data-seo')


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def observed_date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ).date()
    except (ValueError, TypeError):
        return None


def select_cohort(rows, slug, as_of):
    wards = SCOPES[slug]['wards']
    result = {}
    for row in rows:
        if row.get('source') not in SOURCES or row.get('ward') not in wards:
            continue
        if row.get('property_type') != 'dat_nen' or row.get('tx_type') != 'ban':
            continue
        if row.get('duplicate_of_id') is not None or row.get('source_status') == 'inactive':
            continue
        if any(row.get(k) for k in ('possibly_duplicate','is_blacklisted','review_hidden','is_outlier',
                                    'valuation_is_outlier','suspicious_bait','probably_sold')):
            continue
        flags = split_quality_flags(row.get('extraction_quality_flags')) | split_quality_flags(row.get('source_quality_flags'))
        if flags & ACTIONABLE_SUPPRESS_FLAGS:
            continue
        seen = observed_date(row.get('last_seen_at'))
        if seen is None or not as_of.replace(day=1) <= seen <= as_of:
            continue
        try:
            price, area, ppm = (float(row.get(k)) for k in ('price_ty','area_m2','price_per_m2'))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(v) and v > 0 for v in (price,area,ppm)):
            continue
        # price_ty is billion VND; price_per_m2 is million VND/m².
        expected = price * 1000 / area
        if abs(ppm-expected) > max(0.001, expected * POLICY['price_consistency_relative_tolerance']):
            continue
        if type(row.get('id')) is not int or row['id'] <= 0:
            continue
        result.setdefault(row['id'], row)
    return [result[k] for k in sorted(result)]


def display_price(value):
    return 'Chưa đủ mẫu' if value is None else f'{value:.2f}'.replace('.', ',')


def month_keys(as_of):
    current = as_of.replace(day=1)
    keys = []
    for _ in range(6):
        keys.append(current.isoformat()[:7])
        current = (current-timedelta(days=1)).replace(day=1)
    return list(reversed(keys))


def build_snapshot(rows, *, as_of, generated_at, source_commit, previous=()):
    if not re.fullmatch(r'[0-9a-f]{40}', source_commit):
        raise ValueError('invalid source commit')
    if observed_date(generated_at) != as_of:
        raise ValueError('as_of must match actual generation date; no historical reconstruction')
    previous = list(previous)
    for old in previous:
        validate_snapshot(old)
        if old['contract_version'] != CONTRACT or old['data_as_of'] >= as_of.isoformat():
            raise ValueError('historical packet must precede current date and match contract')
    snapshot = dict(schema_version=1, scope_registry_version=SCOPE_REGISTRY_VERSION,
                    contract_version=CONTRACT, generated_at=generated_at,
                    data_as_of=as_of.isoformat(), timezone=str(TZ), source_commit=source_commit,
                    period_start=as_of.replace(day=1).isoformat(), period_end=as_of.isoformat(),
                    period_kind='MTD', policy=POLICY, scopes={},
                    history_warning='No reconstructed historical observations; absent snapshots stay null.',
                    publication_references=[f'https://radarbds.vn/gia-dat/{s}' for s in SCOPES])
    for slug, definition in SCOPES.items():
        cohort = select_cohort(rows, slug, as_of)
        values = [float(r['price_per_m2']) for r in cohort]
        n = len(values)
        eligible = n >= 15
        nums = dict(mean=statistics.mean(values), median=statistics.median(values), min=min(values), max=max(values)) if eligible else dict.fromkeys(('mean','median','min','max'))
        facts = {key:dict(fact_id=f'{slug}.dat_nen.{key}', scope=slug, property_type='dat_nen',
                          period_start=snapshot['period_start'],period_end=snapshot['period_end'],
                          source_basis=list(SOURCES), contract_version=CONTRACT,
                          sample_count=n, unit='trieu_vnd_per_m2',
                          value=round(v,6) if v is not None else None,
                          display=display_price(v)) for key,v in nums.items()}
        counts = Counter(r['source'] for r in cohort)
        histogram = []
        if eligible:
            edges = (0,10,20,30,50,100,math.inf)
            for lo,hi in zip(edges,edges[1:]):
                count = sum(lo <= v < hi for v in values)
                histogram.append(dict(lower=lo,upper=hi if math.isfinite(hi) else None,
                                      count=count,label=f'{lo}–<{hi}' if math.isfinite(hi) else f'≥{lo}'))
        history = []
        for month in month_keys(as_of):
            choices = [p for p in previous if p['data_as_of'][:7] == month and slug in p['scopes']]
            if choices:
                chosen = max(choices,key=lambda p:p['generated_at'])
                old_scope = chosen['scopes'][slug]
                point = dict(month=month, median=old_scope['facts']['median']['value'],
                             sample_count=old_scope['sample_count'],period_end=chosen['period_end'],
                             snapshot_sha256=chosen['sha256'])
            else:
                point = dict(month=month,median=None,sample_count=None,period_end=None,snapshot_sha256=None)
            if month == as_of.isoformat()[:7]:
                point.update(median=facts['median']['value'],sample_count=n,period_end=as_of.isoformat(),snapshot_sha256=None)
            history.append(point)
        prev_month = (as_of.replace(day=1)-timedelta(days=1)).isoformat()[:7]
        comparable = [p for p in previous if p['data_as_of'][:7]==prev_month and
                      int(p['period_end'][-2:]) == as_of.day and slug in p['scopes'] and p['scopes'][slug]['eligible']]
        change = None
        if eligible and comparable:
            old = max(comparable,key=lambda p:p['generated_at'])
            baseline = old['scopes'][slug]['facts']['median']['value']
            change = round((facts['median']['value']/baseline-1)*100,2)
        snapshot['scopes'][slug] = dict(name=definition['name'],wards=list(definition['wards']),
            parent=definition['parent'],eligible=eligible,sample_count=n,
            active_count=sum(r.get('is_active') == 1 for r in cohort),
            source_counts={s:counts[s] for s in SOURCES},facts=facts,histogram=histogram,history=history,
            change_mtd_pct=change,change_reason='matched_elapsed_mtd' if change is not None else 'no_comparable_snapshot')
    snapshot['snapshot_id'] = f'{as_of.isoformat()}-{digest(snapshot)[:16]}'
    snapshot['sha256'] = digest(snapshot)
    return snapshot


def validate_snapshot(snapshot):
    if snapshot.get('contract_version') != CONTRACT or snapshot.get('schema_version') != 1:
        raise ValueError('unsupported data contract')
    body = {k:v for k,v in snapshot.items() if k != 'sha256'}
    if digest(body) != snapshot.get('sha256'):
        raise ValueError('snapshot hash mismatch')
    version = snapshot.get('scope_registry_version', 1)
    registered = SCOPE_REGISTRIES.get(version) if type(version) is int else None
    if snapshot.get('policy') != POLICY or registered is None or set(snapshot.get('scopes',{})) != registered:
        raise ValueError('source or scope policy mismatch')
    return snapshot


def validate_claims(snapshot, expected_sha256, claims):
    validate_snapshot(snapshot)
    if snapshot['sha256'] != expected_sha256:
        raise ValueError('wrong snapshot binding')
    facts = {f['fact_id']:f for s in snapshot['scopes'].values() for f in s['facts'].values()}
    for claim in claims:
        fact = facts.get(claim.get('fact_id'))
        if fact is None or canonical_bytes(claim) != canonical_bytes(fact) or fact['value'] is None:
            raise ValueError('fact mismatch or suppressed fact')
    return True


def freeze_snapshot(snapshot, root):
    """Create once; atomically update only latest pointer. Never overwrite a packet."""
    validate_snapshot(snapshot)
    root = Path(root)
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    path = root / (snapshot['snapshot_id']+'.json')
    data = canonical_bytes(snapshot)+b'\n'
    try:
        with path.open('xb') as f:
            os.chmod(path,0o600)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError('immutable snapshot collision')
    fd, temp = tempfile.mkstemp(prefix='.latest-',dir=root)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(canonical_bytes(dict(file=path.name,sha256=snapshot['sha256']))+b'\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp,root/'latest.json')
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return path


def load_latest(root=None):
    root = Path(root) if root is not None else snapshot_root()
    pointer = json.loads((root/'latest.json').read_text())
    name = pointer['file']
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{16}\.json',name):
        raise ValueError('invalid snapshot filename')
    snapshot = validate_snapshot(json.loads((root/name).read_text()))
    if snapshot['sha256'] != pointer['sha256']:
        raise ValueError('latest pointer hash mismatch')
    return snapshot


def page_snapshots(root=None):
    """Select per-scope facts without rewriting packets or relabeling partial MTD.

    Only an actually captured previous calendar month-end can bridge a small
    new-month cohort. An absent endpoint cannot be reconstructed from today's
    prices or a partial prior-month snapshot. Current eligible facts win.
    """
    root = Path(root) if root is not None else snapshot_root()
    current = load_latest(root)
    selected = {slug:current for slug in current['scopes']}
    pending = {slug for slug,scope in current['scopes'].items() if not scope['eligible']}
    if not pending:
        return current, selected
    endpoint = date.fromisoformat(current['period_start']) - timedelta(days=1)
    previous = []
    for path in root.glob(endpoint.isoformat()+'-*.json'):
        old = validate_snapshot(json.loads(path.read_text()))
        if (old['data_as_of'] == endpoint.isoformat() == old['period_end'] and
                old['period_start'] == endpoint.replace(day=1).isoformat() and
                observed_date(old['generated_at']) == endpoint):
            previous.append(old)
    # Deterministic latest capture on the real endpoint; only own eligible
    # cohorts qualify. Never borrow a neighbor/parent's sample count or price.
    for old in sorted(previous,key=lambda p:(p['generated_at'],p['snapshot_id']),reverse=True):
        for slug in list(pending):
            if old['scopes'].get(slug,{}).get('eligible'):
                selected[slug] = old
                pending.remove(slug)
    return current, selected


def sitemap_entries(root=None):
    try:
        _, selected = page_snapshots(root)
    except (OSError,ValueError,KeyError,TypeError):
        return []
    return [dict(path=f'/gia-dat/{slug}',updated_at=snapshot['data_as_of'])
            for slug,snapshot in selected.items() if snapshot['scopes'][slug]['eligible']]


def load_public_cards(slug):
    from services.market_data import load_signals
    from db.connection import get_conn
    payload = load_signals(None, sources=['facebook'],wards=list(SCOPES[slug]['wards']),
                           prop_types=['dat_nen'],tier='guest',limit=5,include_total=False,sort='mos_desc',date_range='1m')
    candidates = [r for r in payload['signals'] if r.get('source') == 'facebook'
                  and r.get('ward') in SCOPES[slug]['wards'] and type(r.get('id')) is int][:5]
    if not candidates:
        return []
    # The shared compact feed has no transaction type and can contain rentals.
    # Recheck only these bounded primary keys; do not change the shared model.
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM listings WHERE id=ANY(?) AND tx_type='ban' "
                            "AND property_type='dat_nen' AND source='facebook'",
                            ([r['id'] for r in candidates],)).fetchall()
    sale_ids = {r['id'] for r in rows}
    # No raw title, description, contact, source URL or internal source metadata.
    return [{key:r.get(key) for key in ('id','ward','area_m2','price_ty')}
            for r in candidates if r['id'] in sale_ids]


def read_current_rows(database_url, as_of):
    """One bounded, repeatable read-only transaction; no app startup/schema helpers."""
    import psycopg
    from psycopg.rows import dict_row
    wards = sorted({w for s in SCOPES.values() for w in s['wards']})
    start = (as_of.replace(day=1)-timedelta(days=1)).isoformat()
    end = (as_of+timedelta(days=1)).isoformat()
    with psycopg.connect(database_url,options='-c default_transaction_read_only=on -c statement_timeout=15000',row_factory=dict_row) as conn:
        with conn.cursor() as q:
            q.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            q.execute('SHOW transaction_read_only')
            if q.fetchone()['transaction_read_only'] != 'on':
                raise RuntimeError('read-only transaction not verified')
            q.execute('''SELECT l.id,l.source,l.ward,l.property_type,l.tx_type,
                       l.price_ty,l.price_per_m2,l.area_m2,l.last_seen_at,l.is_active,
                       l.duplicate_of_id,l.possibly_duplicate,l.is_blacklisted,l.review_hidden,
                       l.is_outlier,l.suspicious_bait,l.probably_sold,l.source_status,
                       l.extraction_quality_flags,v.source_quality_flags,
                       v.is_outlier AS valuation_is_outlier
                FROM listings l
                LEFT JOIN LATERAL (
                    SELECT vr.source_quality_flags,vr.is_outlier FROM valuation_results vr
                    WHERE vr.listing_id=l.id ORDER BY vr.computed_at DESC,vr.id DESC LIMIT 1
                ) v ON TRUE
                WHERE l.source=ANY(%s) AND l.ward=ANY(%s)
                  AND l.property_type='dat_nen' AND l.tx_type='ban'
                  AND LEFT(l.last_seen_at,10)>=%s AND LEFT(l.last_seen_at,10)<=%s
                ORDER BY l.id LIMIT 10001''',(list(SOURCES),wards,start,end))
            rows = q.fetchall()
        conn.rollback()
    if len(rows)>10000:
        raise RuntimeError('cohort bound exceeded; no partial publish')
    return rows

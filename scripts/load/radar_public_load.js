import http from 'k6/http';
import { check, fail, sleep } from 'k6';
import { Counter } from 'k6/metrics';

const BASE_URL = String(__ENV.BASE_URL || '').replace(/\/+$/, '');
const SCENARIO = String(__ENV.SCENARIO || 'default').toLowerCase();
const VUS = Math.max(1, Math.min(5000, Number.parseInt(__ENV.VUS || '100', 10)));
const DURATION = String(__ENV.DURATION || '2m');
const RUN_ID = String(__ENV.RUN_ID || 'manual')
  .replace(/[^a-zA-Z0-9._-]/g, '-')
  .slice(0, 64);

if (!['default', 'mixed'].includes(SCENARIO)) {
  throw new Error(`Unsupported SCENARIO: ${SCENARIO}`);
}

const edgeHit = new Counter('radar_edge_hit');
const edgeMiss = new Counter('radar_edge_miss');
const edgeStale = new Counter('radar_edge_stale');
const edgeBypass = new Counter('radar_edge_bypass');
const edgeUnknown = new Counter('radar_edge_unknown');

export const options = {
  vus: VUS,
  duration: DURATION,
  thresholds: {
    http_req_failed: ['rate<0.005'],
    http_req_duration: SCENARIO === 'mixed'
      ? ['p(95)<1500', 'p(99)<2000']
      : ['p(95)<1000', 'p(99)<2000'],
    checks: ['rate>0.995'],
  },
};

const REQUEST_PARAMS = Object.freeze({
  headers: { Accept: 'text/html,application/json;q=0.9,*/*;q=0.8' },
  tags: { radar_scenario: SCENARIO },
});

function formEncode(value) {
  return encodeURIComponent(String(value)).replace(/%20/g, '+');
}

function canonicalQuery(input) {
  const parts = [];
  for (const key of Object.keys(input).sort()) {
    const rawValues = Array.isArray(input[key]) ? input[key] : [input[key]];
    const values = Array.from(new Set(rawValues.map((value) => String(value).trim()).filter(Boolean)))
      .sort((left, right) => left.localeCompare(right));
    for (const value of values) parts.push(`${formEncode(key)}=${formEncode(value)}`);
  }
  return parts.join('&');
}

const MIXED_WARDS = Object.freeze([
  'Chánh Mỹ', 'Chánh Nghĩa', 'Định Hòa', 'Hiệp An', 'Hiệp Thành',
  'Hòa Phú', 'Phú Cường', 'Phú Hòa', 'Phú Lợi', 'Phú Mỹ',
]);
const MIXED_VARIANTS = Object.freeze([
  { source: ['facebook'], prop_type: ['dat_nen'], mos_min: '10' },
  { source: ['facebook'], prop_type: ['nha_dat'], mos_min: '15' },
  { source: ['guland'], prop_type: ['dat_nen'], mos_min: '20' },
  { source: ['facebook', 'guland'], prop_type: ['dat_nen', 'nha_dat'], mos_min: '25' },
  { source: ['facebook'], prop_type: ['chung_cu'], mos_min: '10' },
]);

const MIXED_CORPUS = Object.freeze(MIXED_WARDS.flatMap((ward) => (
  MIXED_VARIANTS.map((variant) => {
    const base = {
      load_run: RUN_ID,
      mos_min: variant.mos_min,
      prop_type: variant.prop_type,
      source: variant.source,
      ward: [ward],
    };
    return Object.freeze({
      signals: canonicalQuery({ ...base, include_total: '0', limit: '20', page: '1', sort: 'newest' }),
      counts: canonicalQuery(base),
    });
  })
)));

if (MIXED_CORPUS.length !== 50) throw new Error('Mixed corpus must contain exactly 50 keys');

function edgeStatus(response) {
  return String(response.headers['X-Radar-Edge-Cache'] || '').toUpperCase();
}

function recordEdge(response) {
  const status = edgeStatus(response);
  if (status === 'HIT') edgeHit.add(1);
  else if (status === 'MISS') edgeMiss.add(1);
  else if (status === 'STALE' || status === 'UPDATING') edgeStale.add(1);
  else if (status === 'BYPASS') edgeBypass.add(1);
  else edgeUnknown.add(1);
  return status;
}

function mixedUrls(item) {
  return [
    `${BASE_URL}/api/signals?${item.signals}`,
    `${BASE_URL}/api/counts?${item.counts}`,
  ];
}

function requestPair(urls) {
  return http.batch([
    ['GET', urls[0], null, REQUEST_PARAMS],
    ['GET', urls[1], null, REQUEST_PARAMS],
  ]);
}

export function setup() {
  if (!BASE_URL) fail('BASE_URL is required');
  if (SCENARIO !== 'mixed') return { corpusSize: MIXED_CORPUS.length };

  for (const item of MIXED_CORPUS) {
    const urls = mixedUrls(item);
    const first = requestPair(urls);
    if (!first.every((response) => response.status === 200)) {
      fail(`Mixed prewarm failed for ${item.signals}`);
    }
    const second = requestPair(urls);
    if (!second.every((response) => response.status === 200 && edgeStatus(response) === 'HIT')) {
      fail(`Mixed prewarm did not produce HIT for ${item.signals}`);
    }
  }
  return { corpusSize: MIXED_CORPUS.length };
}

function runDefault() {
  const responses = http.batch([
    ['GET', `${BASE_URL}/?load_run=${formEncode(RUN_ID)}`, null, REQUEST_PARAMS],
    ['GET', `${BASE_URL}/api/signals?page=1&limit=20&load_run=${formEncode(RUN_ID)}`, null, REQUEST_PARAMS],
  ]);
  const homeEdge = recordEdge(responses[0]);
  const signalEdge = recordEdge(responses[1]);
  check(responses[0], {
    'homepage status is 200': (response) => response.status === 200,
    'homepage is edge classified': () => Boolean(homeEdge),
    'homepage body has Radar BDS': (response) => String(response.body || '').includes('Radar BDS'),
  });
  check(responses[1], {
    'signals status is 200': (response) => response.status === 200,
    'signals are edge classified': () => Boolean(signalEdge),
    'signals body has array field': (response) => /"signals"\s*:\s*\[/.test(String(response.body || '')),
  });
}

function runMixed() {
  const item = MIXED_CORPUS[(__VU + __ITER) % MIXED_CORPUS.length];
  const responses = requestPair(mixedUrls(item));
  const signalEdge = recordEdge(responses[0]);
  const countsEdge = recordEdge(responses[1]);
  check(responses[0], {
    'mixed signals status is 200': (response) => response.status === 200,
    'mixed signals are edge classified': () => Boolean(signalEdge),
    'mixed signals body shape is valid': (response) => /"signals"\s*:\s*\[/.test(String(response.body || '')),
  });
  check(responses[1], {
    'mixed counts status is 200': (response) => response.status === 200,
    'mixed counts are edge classified': () => Boolean(countsEdge),
    'mixed counts body shape is valid': (response) => /"stats"\s*:\s*\{/.test(String(response.body || '')),
  });
}

export default function radarPublicLoad() {
  if (SCENARIO === 'mixed') runMixed();
  else runDefault();
  sleep(1);
}

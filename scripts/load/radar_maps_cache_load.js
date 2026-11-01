// Warm public Maps delivery gate, not a full browser/cold-region capacity claim.
import http from 'k6/http';
import { check, sleep, fail } from 'k6';
import exec from 'k6/execution';
import { Rate, Trend } from 'k6/metrics';

const BASE = 'https://radarbds.vn';
const VUS = Number(__ENV.VUS || 25);
const DURATION = __ENV.DURATION || '30s';
const HEADERS = { 'Accept-Encoding': 'gzip' };
if (![25, 100, 250, 1000].includes(VUS)) throw new Error('Use staged 25/100/250/1000 VUs');
if (VUS > 25 && __ENV.CONFIRM !== 'radarbds.vn') throw new Error('Explicit production confirmation required');
if (!['30s', '1m'].includes(DURATION)) throw new Error('Bounded 30s or 1m gate only');

// Only the already verified Tan An snapshot and one cached GIS image. No live
// cadastral endpoints, planning lookups, listings or arbitrary/cold regions.
const paths = [
  '/api/planning/parcel-cells/a58ff8deda83ba61/snapshot/104354/61498.json',
  '/api/planning/parcel-cells/a58ff8deda83ba61/snapshot/104353/61497.json',
  '/api/planning/gis-tiles/partition/17/104354/61498.png',
  '/api/map-labels/osm/14/13044/7687.mvt',
];
const readMs = new Trend('maps_read_ms', true);
const panMs = new Trend('maps_pan_delivery_ms', true);
const connectionMs = new Trend('maps_connection_ms', true);
const okay = new Rate('maps_delivery_ok');
const cdnHit = new Rate('maps_cdn_hit');
let connected = false;

export const options = {
  scenarios: { maps: { executor: 'constant-vus', vus: VUS, duration: DURATION, gracefulStop: '10s' } },
  setupTimeout: '1m', summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max'],
  discardResponseBodies: true, batchPerHost: 2,
  thresholds: {
    maps_delivery_ok: [{ threshold: 'rate>0.995', abortOnFail: true, delayAbortEval: '10s' }],
    maps_cdn_hit: [{ threshold: 'rate>0.98', abortOnFail: true, delayAbortEval: '10s' }],
    maps_read_ms: ['p(95)<1000', 'p(99)<2000'],
    maps_pan_delivery_ms: ['p(95)<2000', 'p(99)<3000'],
  },
};

function header(response, name) {
  const key = Object.keys(response.headers).find(k => k.toLowerCase() === name.toLowerCase());
  return key ? String(response.headers[key]) : '';
}

export function setup() {
  for (const path of paths) {
    let warm = false;
    for (let attempt = 0; attempt < 3; attempt++) {
      const response = http.get(BASE + path, { headers: HEADERS, timeout: '15s', tags: { phase: 'prewarm' } });
      if (response.status === 200 && header(response, 'cf-cache-status') === 'HIT') { warm = true; break; }
      sleep(.5);
    }
    if (!warm) fail('CDN prewarm gate failed; no VU load started');
  }
}

export default function () {
  if (!connected) {
    // Maps is opened from a loaded dashboard on this same origin. Record this
    // connection warmup separately; do not hide it inside a tile latency claim.
    const response = http.head(BASE + '/static/js/main/planning_parcel_cells.js?v=parcel-cells-20261101',
      { headers: HEADERS, timeout: '15s', tags: { phase: 'connection' } });
    connectionMs.add(response.timings.duration + response.timings.blocked);
    if (response.status !== 200) exec.test.abort('Dashboard connection warmup failed');
    connected = true;
    sleep(Math.random());
  }
  const started = Date.now();
  const responses = http.batch(paths.map(path => ['GET', BASE + path, null,
    { headers: HEADERS, timeout: '15s', tags: { phase: 'map-read' } }]));
  panMs.add(Date.now() - started);
  for (const response of responses) {
    const cache = header(response, 'cf-cache-status');
    const valid = response.status === 200 && header(response, 'cache-control').includes('public')
      && !header(response, 'set-cookie') && /application\/json|image\/png|application\/vnd.mapbox-vector-tile/.test(header(response, 'content-type'))
      && (!header(response, 'content-type').includes('application/json') || header(response, 'content-encoding').includes('gzip'));
    okay.add(valid); cdnHit.add(cache === 'HIT'); readMs.add(response.timings.duration);
    check(response, { 'public Maps response': () => valid });
    if (!valid || !['HIT', 'MISS', 'UPDATING', 'STALE', 'REVALIDATED'].includes(cache)) {
      exec.test.abort('Maps cache contract failed; do not increase origin load');
    }
  }
  sleep(5 + Math.random());
}

export function handleSummary(data) {
  return { [__ENV.SUMMARY_FILE || '.local/maps-cache-verification/k6-summary.json']: JSON.stringify({
    scope: 'Gzip warm delivery of 2 snapshot cells + 1 cached GIS image + 1 OSM MVT on existing dashboard connections; not full Maps/browser/cold-region proof',
    vus: VUS, duration: DURATION, metrics: data.metrics,
  }, null, 2) };
}

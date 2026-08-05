import http from 'k6/http';
import { check, fail } from 'k6';
import exec from 'k6/execution';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = String(__ENV.BASE_URL || 'http://127.0.0.1:5000').replace(/\/+$/, '');
const DURATION = String(__ENV.DURATION || '30s');
const VUS_PER_SCENARIO = Math.max(1, Math.min(20, Number.parseInt(__ENV.VUS_PER_SCENARIO || '20', 10)));
const RUN_ID = String(__ENV.RUN_ID || 'radar-ask-local')
  .replace(/[^a-zA-Z0-9._-]/g, '-')
  .slice(0, 48);
const PUBLIC_BASELINE_P95_MS = Number(__ENV.PUBLIC_BASELINE_P95_MS || 0);
const PUBLIC_LIMIT_MS = PUBLIC_BASELINE_P95_MS * 1.2;
const QA_CAPABILITY_PATH = '/api/radar-ask/qa-capabilities';
const AUTHENTICATED_SCENARIOS = Object.freeze([
  'fast',
  'standard_fake',
  'deep_enqueue',
  'history',
  'poll',
]);

let testUsers;
try {
  testUsers = JSON.parse(String(__ENV.RADAR_ASK_TEST_USERS_JSON || '[]'));
} catch (_error) {
  throw new Error('RADAR_ASK_TEST_USERS_JSON must be valid JSON');
}

const fastDuration = new Trend('radar_ask_fast_duration', true);
const standardDuration = new Trend('radar_ask_standard_duration', true);
const deepEnqueueDuration = new Trend('radar_ask_deep_enqueue_duration', true);
const historyDuration = new Trend('radar_ask_history_duration', true);
const pollDuration = new Trend('radar_ask_poll_duration', true);
const publicDuration = new Trend('radar_ask_public_duration', true);
const assistantErrors = new Rate('radar_ask_errors');
const publicErrors = new Rate('radar_ask_public_errors');
const statementTimeouts = new Rate('radar_ask_statement_timeouts');

export const options = {
  scenarios: {
    fast: scenario('runFast'),
    standard_fake: scenario('runStandard'),
    deep_enqueue: scenario('runDeepEnqueue'),
    history: scenario('runHistory'),
    poll: scenario('runPoll'),
    public_isolation: scenario('runPublicIsolation'),
  },
  thresholds: {
    radar_ask_fast_duration: ['p(95)<=800'],
    radar_ask_standard_duration: ['p(95)<=6000'],
    radar_ask_deep_enqueue_duration: ['p(95)<=500'],
    radar_ask_history_duration: ['p(95)<=500'],
    radar_ask_poll_duration: ['p(95)<=500'],
    radar_ask_public_duration: [`p(95)<=${PUBLIC_LIMIT_MS}`],
    radar_ask_errors: ['rate<0.01'],
    radar_ask_public_errors: ['rate<0.01'],
    radar_ask_statement_timeouts: ['rate==0'],
    checks: ['rate>0.99'],
  },
};

function scenario(exec) {
  return {
    executor: 'per-vu-iterations',
    exec,
    vus: VUS_PER_SCENARIO,
    iterations: 1,
    maxDuration: DURATION,
    gracefulStop: '5s',
  };
}

function assertLocalTarget() {
  let target;
  try {
    target = new URL(BASE_URL);
  } catch (_error) {
    fail('BASE_URL must be a valid URL');
  }
  if (!['http:', 'https:'].includes(target.protocol)) fail('BASE_URL must use HTTP(S)');
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname)) {
    fail('Radar Ask load is local/test-only; BASE_URL must be loopback');
  }
}

function validSeed(user) {
  return user
    && typeof user.identifier === 'string'
    && typeof user.password === 'string'
    && typeof user.session_id === 'string'
    && typeof user.run_id === 'string';
}

export function setup() {
  assertLocalTarget();
  if (String(__ENV.RADAR_ASK_FAKE_PROVIDER || '') !== '1') {
    fail('RADAR_ASK_FAKE_PROVIDER=1 is required; live providers are forbidden');
  }
  if (!Array.isArray(testUsers) || testUsers.length === 0 || !testUsers.every(validSeed)) {
    fail('RADAR_ASK_TEST_USERS_JSON requires seeded identifier/password/session_id/run_id objects');
  }
  const requiredUsers = AUTHENTICATED_SCENARIOS.length * VUS_PER_SCENARIO;
  if (testUsers.length < requiredUsers) {
    fail(`RADAR_ASK_TEST_USERS_JSON needs at least ${requiredUsers} distinct users to avoid quota/burst distortion`);
  }
  if (!Number.isFinite(PUBLIC_BASELINE_P95_MS) || PUBLIC_BASELINE_P95_MS <= 0) {
    fail('PUBLIC_BASELINE_P95_MS from the immediately preceding public baseline is required');
  }
  const capability = http.get(`${BASE_URL}${QA_CAPABILITY_PATH}`, {
    headers: { Accept: 'application/json' },
    tags: { radar_ask_operation: 'qa_capability' },
  });
  const capabilityBody = jsonBody(capability);
  const capabilityOk = capability.status === 200
    && privateHeaders(capability)
    && String(capability.headers['X-Radar-Ask-QA-Provider'] || '').toLowerCase() === 'fake'
    && capabilityBody
    && capabilityBody.mode === 'radar_ask_test'
    && capabilityBody.provider === 'fake'
    && capabilityBody.database === 'radar_bds_test'
    && capabilityBody.backend_pipeline === 'real'
    && capabilityBody.live_provider_allowed === false;
  if (!capabilityOk) {
    fail('Server did not prove fake-provider/radar_bds_test isolation; no credentials or questions were sent');
  }
  return { userCount: testUsers.length, requiredUsers, publicLimitMs: PUBLIC_LIMIT_MS };
}

let authenticated = false;

function userForVu() {
  const scenarioIndex = AUTHENTICATED_SCENARIOS.indexOf(exec.scenario.name);
  if (scenarioIndex < 0) fail('Authenticated user requested outside an authenticated scenario');
  const iterationIndex = Number(exec.scenario.iterationInInstance || 0) % VUS_PER_SCENARIO;
  return testUsers[(scenarioIndex * VUS_PER_SCENARIO) + iterationIndex];
}

function jsonBody(response) {
  try {
    return response.json();
  } catch (_error) {
    return null;
  }
}

function privateHeaders(response) {
  const cacheControl = String(response.headers['Cache-Control'] || '').toLowerCase();
  return cacheControl.includes('private')
    && cacheControl.includes('no-store')
    && !response.headers['X-Radar-Public-Cache'];
}

function ensureLogin() {
  if (authenticated) return userForVu();
  const user = userForVu();
  const response = http.post(
    `${BASE_URL}/api/auth/login`,
    JSON.stringify({ identifier: user.identifier, password: user.password }),
    {
      headers: {
        'Content-Type': 'application/json',
        Origin: BASE_URL,
      },
      tags: { radar_ask_operation: 'login_setup' },
    },
  );
  if (!check(response, { 'seeded login succeeds': (item) => item.status === 200 })) {
    fail('Seeded Radar Ask test login failed');
  }
  authenticated = true;
  return user;
}

function questionParams(operation) {
  return {
    headers: {
      'Content-Type': 'application/json',
      Origin: BASE_URL,
      'Idempotency-Key': `${RUN_ID}-${operation}-${__VU}-${__ITER}`,
    },
    tags: { radar_ask_operation: operation },
  };
}

function recordAssistant(response, trend, expectedStatuses, expectedRunStatuses) {
  const body = jsonBody(response);
  const ok = expectedStatuses.includes(response.status)
    && body
    && expectedRunStatuses.includes(String(body.status || ''))
    && privateHeaders(response)
    && response.body.length <= 128 * 1024;
  trend.add(response.timings.duration);
  assistantErrors.add(!ok);
  const errorCode = String(body && body.error && body.error.code || '');
  statementTimeouts.add(errorCode.includes('timeout'));
  check(response, {
    'assistant response is bounded and private': () => Boolean(ok),
  });
  return body;
}

export function runFast() {
  ensureLogin();
  const response = http.post(
    `${BASE_URL}/api/radar-ask/questions`,
    JSON.stringify({
      question: 'Hôm nay khu vực nào có nhiều tin giảm giá?',
      requested_depth: 'fast',
    }),
    questionParams('fast'),
  );
  recordAssistant(response, fastDuration, [200], ['completed', 'insufficient', 'clarifying']);
}

export function runStandard() {
  ensureLogin();
  const response = http.post(
    `${BASE_URL}/api/radar-ask/questions`,
    JSON.stringify({
      question: 'Phân tích một công cụ và tóm tắt khu Phú Mỹ bằng dữ liệu giả kiểm thử.',
      requested_depth: 'standard',
    }),
    questionParams('standard_fake'),
  );
  recordAssistant(response, standardDuration, [200], ['completed', 'insufficient', 'clarifying']);
}

export function runDeepEnqueue() {
  ensureLogin();
  const response = http.post(
    `${BASE_URL}/api/radar-ask/questions`,
    JSON.stringify({
      question: 'Nghiên cứu sâu lô 123 bằng dữ liệu giả kiểm thử.',
      requested_depth: 'deep',
    }),
    questionParams('deep_enqueue'),
  );
  recordAssistant(response, deepEnqueueDuration, [202], ['queued', 'created', 'running']);
}

export function runHistory() {
  const user = ensureLogin();
  const list = http.get(
    `${BASE_URL}/api/radar-ask/sessions?limit=50`,
    { tags: { radar_ask_operation: 'history_list' } },
  );
  const detail = http.get(
    `${BASE_URL}/api/radar-ask/sessions/${encodeURIComponent(user.session_id)}?message_limit=100`,
    { tags: { radar_ask_operation: 'history_detail' } },
  );
  const listBody = jsonBody(list);
  const detailBody = jsonBody(detail);
  const ok = list.status === 200
    && detail.status === 200
    && privateHeaders(list)
    && privateHeaders(detail)
    && Array.isArray(listBody && listBody.sessions)
    && listBody.sessions.length <= 50
    && Array.isArray(detailBody && detailBody.messages)
    && detailBody.messages.length <= 100
    && list.body.length <= 128 * 1024
    && detail.body.length <= 128 * 1024;
  historyDuration.add(Math.max(list.timings.duration, detail.timings.duration));
  assistantErrors.add(!ok);
  statementTimeouts.add(false);
  check(detail, { 'history is paginated bounded and private': () => Boolean(ok) });
}

export function runPoll() {
  const user = ensureLogin();
  const response = http.get(
    `${BASE_URL}/api/radar-ask/runs/${encodeURIComponent(user.run_id)}`,
    { tags: { radar_ask_operation: 'poll' } },
  );
  recordAssistant(
    response,
    pollDuration,
    [200],
    ['created', 'queued', 'running', 'completed', 'insufficient', 'clarifying', 'failed', 'cancelled'],
  );
}

const PUBLIC_PATHS = Object.freeze([
  ['/api/signals?page=1&limit=20&include_total=0', 'signals'],
  ['/api/listings?page=1&limit=20', 'listings'],
  ['/api/counts', 'stats'],
  ['/api/dashboard', 'stats'],
]);

export function runPublicIsolation() {
  const publicIndex = Number(exec.scenario.iterationInInstance || 0) % PUBLIC_PATHS.length;
  const [path, requiredKey] = PUBLIC_PATHS[publicIndex];
  const response = http.get(`${BASE_URL}${path}`, {
    headers: { Accept: 'application/json', 'Accept-Encoding': 'gzip' },
    tags: { radar_ask_operation: 'public_isolation', public_path: path.split('?')[0] },
  });
  const body = jsonBody(response);
  const ok = response.status === 200
    && body
    && Object.prototype.hasOwnProperty.call(body, requiredKey);
  publicDuration.add(response.timings.duration);
  publicErrors.add(!ok);
  check(response, { 'public API contract remains available': () => Boolean(ok) });
}

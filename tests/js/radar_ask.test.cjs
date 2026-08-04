const test = require('node:test');
const assert = require('node:assert/strict');

const {
  POLL_DELAYS_MS,
  createController,
  handleComposerKey,
  pollRun,
  quotaLabel,
  renderAnswer,
  safeHref,
} = require('../../static/js/radar_ask.js');

class FakeElement {
  constructor(tagName, ownerDocument) {
    this.tagName = String(tagName).toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.hidden = false;
    this.className = '';
    this._text = '';
  }

  set textContent(value) {
    this._text = String(value ?? '');
    this.children = [];
  }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join('');
  }

  append(...children) {
    children.forEach((child) => {
      if (child !== null && child !== undefined) {
        this.children.push(child);
        child.parentNode = this;
      }
    });
  }

  appendChild(child) {
    this.append(child);
    return child;
  }

  replaceChildren(...children) {
    this.children = [];
    this._text = '';
    this.append(...children);
  }

  setAttribute(name, value) {
    const normalized = String(value);
    this.attributes.set(name, normalized);
    if (name === 'class') this.className = normalized;
    if (name.startsWith('data-')) {
      const key = name.slice(5).replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase());
      this.dataset[key] = normalized;
    }
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  matches(selector) {
    if (selector.startsWith('#')) return this.getAttribute('id') === selector.slice(1);
    if (selector.startsWith('.')) return this.className.split(/\s+/).includes(selector.slice(1));
    const attribute = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
    if (attribute) {
      if (!this.attributes.has(attribute[1])) return false;
      return attribute[2] === undefined || this.getAttribute(attribute[1]) === attribute[2];
    }
    return this.tagName.toLowerCase() === selector.toLowerCase();
  }

  querySelectorAll(selector) {
    const matches = [];
    const visit = (node) => {
      node.children.forEach((child) => {
        if (child.matches(selector)) matches.push(child);
        visit(child);
      });
    };
    visit(this);
    return matches;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}

class FakeDocument {
  createElement(tagName) {
    return new FakeElement(tagName, this);
  }
}

function fakeRoot() {
  const document = new FakeDocument();
  return document.createElement('div');
}

function completedAnswer(overrides = {}) {
  return {
    answered: true,
    depth: 'fast',
    verdict: 'dang_xem',
    direct_answer: 'Phú Mỹ phù hợp hơn với ngân sách này.',
    claims: [],
    key_metrics: [
      { label: 'Giá trung vị', value: 19.5, unit: 'triệu/m²', evidence_ids: ['market.1'] },
      { label: 'Cỡ mẫu', value: 42, unit: 'tin', evidence_ids: ['market.1'] },
      { label: 'Biên giá', value: '18–22', unit: 'triệu/m²', evidence_ids: ['market.1'] },
      { label: 'Độ mới', value: 7, unit: 'ngày', evidence_ids: ['market.1'] },
      { label: 'Không được hiện ở Fast', value: 99, unit: null, evidence_ids: [] },
    ],
    favorable_thesis: 'Mặt bằng giá còn phù hợp.',
    counter_thesis: 'Thanh khoản cần kiểm tra thêm.',
    risks: ['Pháp lý từng lô có thể khác nhau.'],
    confidence: 0.72,
    confidence_reasons: ['Cỡ mẫu đủ dùng.'],
    next_checks: ['Kiểm tra sổ và lộ giới.'],
    source_cards: [
      {
        evidence_id: 'market.1',
        title: 'Radar BDS · Giá rao bán 90 ngày',
        source_kind: 'market_stat',
        as_of: '2026-08-05T04:00:00Z',
      },
    ],
    suggested_followups: ['So sánh thêm với Định Hòa'],
    as_of: '2026-08-05T04:00:00Z',
    dataset_version: 'signals:12',
    ...overrides,
  };
}

function fakeView() {
  const calls = [];
  return {
    calls,
    setPending: (value) => calls.push(['pending', value]),
    setQuota: (quota, cost) => calls.push(['quota', quota, cost]),
    showRun: (run) => calls.push(['run', run]),
    showError: (error) => calls.push(['error', error]),
    showSessions: (sessions) => calls.push(['sessions', sessions]),
    showSession: (session) => calls.push(['session', session]),
    removeSession: (id) => calls.push(['remove', id]),
    showFeedback: (id, rating) => calls.push(['feedback', id, rating]),
  };
}

test('quota label reports tier cap without inventing remaining quota', () => {
  assert.equal(quotaLabel({ tier: 'free' }), 'Free · 5 câu/ngày');
  assert.equal(quotaLabel({ tier: 'vip' }), 'VIP · 20 câu/ngày');
  assert.equal(quotaLabel({ tier: 'admin' }), 'Admin · 100 câu/ngày');
  assert.equal(quotaLabel({ tier: 'free', remaining: 3 }), 'Free · còn 3/5 câu hôm nay');
});
test('Enter submits while Shift+Enter preserves a newline', () => {
  let submits = 0;
  const enter = { key: 'Enter', shiftKey: false, preventDefault() { this.prevented = true; } };
  const shifted = { key: 'Enter', shiftKey: true, preventDefault() { this.prevented = true; } };

  assert.equal(handleComposerKey(enter, () => { submits += 1; }), true);
  assert.equal(enter.prevented, true);
  assert.equal(handleComposerKey(shifted, () => { submits += 1; }), false);
  assert.equal(shifted.prevented, undefined);
  assert.equal(submits, 1);
});

test('renders model text as text, never executable HTML', () => {
  const root = fakeRoot();
  renderAnswer(root, completedAnswer({ direct_answer: '<img src=x onerror=alert(1)>' }));
  assert.equal(root.querySelector('[data-direct-answer]').textContent, '<img src=x onerror=alert(1)>');
  assert.equal(root.querySelectorAll('img').length, 0);
});

test('fast answer stays compact and keeps deep sections collapsed', () => {
  const root = fakeRoot();
  renderAnswer(root, completedAnswer());
  assert.equal(root.querySelector('[data-deep-details]').hidden, true);
  assert.equal(root.querySelectorAll('[data-key-metric]').length, 4);
  assert.equal(root.querySelectorAll('[data-source-card]').length, 1);
});

test('deep answer progressively discloses thesis, risk, confidence and checks', () => {
  const root = fakeRoot();
  renderAnswer(root, completedAnswer({ depth: 'deep' }));
  const details = root.querySelector('[data-deep-details]');
  assert.equal(details.hidden, false);
  assert.match(details.textContent, /Mặt bằng giá còn phù hợp/);
  assert.match(details.textContent, /Thanh khoản cần kiểm tra thêm/);
  assert.match(details.textContent, /Pháp lý từng lô/);
  assert.match(details.textContent, /Kiểm tra sổ và lộ giới/);
});

test('insufficient answer receives an explicit user-facing state', () => {
  const root = fakeRoot();
  renderAnswer(root, completedAnswer({ answered: false, verdict: 'khong_du_du_lieu' }));
  assert.match(root.querySelector('[data-insufficient]').textContent, /chưa đủ dữ liệu/i);
});

test('safeHref accepts only same-origin paths and HTTPS links', () => {
  assert.equal(safeHref('/listing/123'), '/listing/123');
  assert.equal(safeHref('https://example.com/source'), 'https://example.com/source');
  assert.equal(safeHref('javascript:alert(1)'), null);
  assert.equal(safeHref('//evil.example/path'), null);
  assert.equal(safeHref('/\\evil'), null);
});

test('queued run polls at 1, 2, 3, then 5 seconds until completed', async () => {
  const waits = [];
  const statuses = ['queued', 'running', 'running', 'completed'];
  const result = await pollRun({
    runId: 'run-1',
    fetchRun: async () => ({ run_id: 'run-1', status: statuses.shift() }),
    wait: async (milliseconds) => waits.push(milliseconds),
  });
  assert.deepEqual(waits, [1000, 2000, 3000, 5000]);
  assert.equal(result.status, 'completed');
  assert.deepEqual(POLL_DELAYS_MS, [1000, 2000, 3000, 5000]);
});

test('polling stops after 120 seconds and exposes manual refresh state', async () => {
  const waits = [];
  const result = await pollRun({
    runId: 'run-slow',
    fetchRun: async () => ({ run_id: 'run-slow', status: 'running' }),
    wait: async (milliseconds) => waits.push(milliseconds),
    timeoutMs: 120000,
  });
  assert.equal(result.status, 'poll_timeout');
  assert.equal(result.run_id, 'run-slow');
  assert.ok(waits.reduce((total, delay) => total + delay, 0) <= 120000);
});

test('controller allows one pending submit and renders immediate 200 answer', async () => {
  let resolvePost;
  let posts = 0;
  const api = {
    postQuestion: () => {
      posts += 1;
      return new Promise((resolve) => { resolvePost = resolve; });
    },
  };
  const view = fakeView();
  const controller = createController({ api, view });

  const first = controller.submit('Giá Phú Mỹ?', 'fast');
  const second = await controller.submit('Câu hỏi trùng', 'fast');
  assert.equal(second.ignored, true);
  assert.equal(posts, 1);

  resolvePost({
    run_id: 'run-200', session_id: 'session-1', status: 'completed',
    answer: completedAnswer(), quota: { tier: 'free' }, cost_state: { state: 'normal' },
  });
  const result = await first;
  assert.equal(result.status, 'completed');
  assert.deepEqual(view.calls.filter(([name]) => name === 'pending'), [['pending', true], ['pending', false]]);
  assert.equal(view.calls.some(([name, run]) => name === 'run' && run.answer.direct_answer.includes('Phú Mỹ')), true);
});

test('controller follows a 202 run and manual refresh never resubmits', async () => {
  let posts = 0;
  let gets = 0;
  const api = {
    postQuestion: async () => {
      posts += 1;
      return { run_id: 'run-202', session_id: 'session-2', status: 'queued', quota: { tier: 'vip' }, cost_state: { state: 'normal' } };
    },
    getRun: async () => {
      gets += 1;
      return { run_id: 'run-202', session_id: 'session-2', status: 'completed', answer: completedAnswer({ depth: 'deep' }), quota: { tier: 'vip' }, cost_state: { state: 'normal' } };
    },
  };
  const view = fakeView();
  const controller = createController({
    api,
    view,
    poller: ({ fetchRun }) => fetchRun(),
  });

  await controller.submit('Phân tích sâu', 'deep');
  await controller.refreshRun();
  assert.equal(posts, 1);
  assert.equal(gets, 2);
});

test('controller distinguishes retryable and monthly hard-stop errors', async () => {
  const view = fakeView();
  const retryableApi = { postQuestion: async () => { throw { code: 'provider_unavailable', message: 'Thử lại sau.' }; } };
  await createController({ api: retryableApi, view }).submit('Câu hỏi', 'fast');
  const retryable = view.calls.find(([name]) => name === 'error')[1];
  assert.equal(retryable.retryable, true);

  const lockedView = fakeView();
  const lockedApi = { postQuestion: async () => { throw { code: 'monthly_budget_hard_stop', message: 'Tạm dừng.' }; } };
  const locked = createController({ api: lockedApi, view: lockedView });
  await locked.submit('Câu hỏi', 'fast');
  assert.equal(locked.state.costState, 'locked');
  assert.equal(lockedView.calls.find(([name]) => name === 'error')[1].retryable, false);
});

test('controller supports history navigation, confirmation delete and feedback', async () => {
  const calls = [];
  const api = {
    listSessions: async () => ({ sessions: [{ id: 'session-1', title: 'Phú Mỹ' }] }),
    getSession: async (id) => ({ session: { id, title: 'Phú Mỹ' }, messages: [] }),
    deleteSession: async (id) => calls.push(['delete', id]),
    feedback: async (id, rating) => calls.push(['feedback', id, rating]),
  };
  const view = fakeView();
  const controller = createController({ api, view, confirm: async () => true });

  await controller.loadSessions();
  await controller.openSession('session-1');
  await controller.deleteSession('session-1');
  await controller.giveFeedback('message-1', 'helpful');

  assert.deepEqual(calls, [['delete', 'session-1'], ['feedback', 'message-1', 'helpful']]);
  assert.equal(controller.state.currentSessionId, null);
  assert.equal(view.calls.some(([name]) => name === 'sessions'), true);
  assert.equal(view.calls.some(([name]) => name === 'session'), true);
});

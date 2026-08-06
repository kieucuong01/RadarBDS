(function radarAskModule(globalScope, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') {
    window.RadarAsk = Object.assign(window.RadarAsk || {}, api);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function buildRadarAsk() {
  'use strict';

  const POLL_DELAYS_MS = Object.freeze([1000, 2000, 3000, 5000]);
  const HANDOFF_STORAGE_KEY = 'radarAsk:handoff:v1';
  const PENDING_STATUSES = new Set(['created', 'queued', 'running']);
  const ANSWER_STATUSES = new Set(['completed', 'clarifying', 'insufficient']);
  const TERMINAL_STATUSES = new Set([...ANSWER_STATUSES, 'failed', 'cancelled']);
  const RETRYABLE_CODES = new Set([
    'provider_unavailable',
    'service_unavailable',
    'worker_unavailable',
    'burst_limit_exceeded',
  ]);
  const TIER_CAPS = Object.freeze({
    free: { label: 'Free', cap: 5, capLabel: 'Free · 5 câu/ngày' },
    vip: { label: 'VIP', cap: 20, capLabel: 'VIP · 20 câu/ngày' },
    admin: { label: 'Admin', cap: null, capLabel: 'Admin · không giới hạn hôm nay' },
  });
  const DEPTH_LABELS = Object.freeze({ fast: 'Nhanh', auto: 'Tự động', standard: 'Phân tích', deep: 'Chuyên sâu' });
  const VERDICT_LABELS = Object.freeze({
    dang_xem: 'Đáng xem',
    can_kiem_tra_them: 'Cần kiểm tra thêm',
    rui_ro_cao: 'Rủi ro cao',
    khong_du_du_lieu: 'Chưa đủ dữ liệu',
  });

  function classifyRunStatus(status) {
    if (PENDING_STATUSES.has(status)) return 'pending';
    if (ANSWER_STATUSES.has(status)) return 'answer';
    if (status === 'cancelled') return 'cancelled';
    return 'failed';
  }

  function quotaLabel(quota) {
    const tier = String(quota && quota.tier || 'free').toLowerCase();
    const policy = TIER_CAPS[tier] || TIER_CAPS.free;
    if (tier === 'admin' || quota && quota.admin_unlimited === true) {
      return policy.capLabel;
    }
    const cap = Number.isInteger(quota && quota.daily_limit) && quota.daily_limit >= 0
      ? quota.daily_limit : policy.cap;
    if (Number.isInteger(quota && quota.remaining) && quota.remaining >= 0) {
      return `${policy.label} · còn ${quota.remaining}/${cap} câu hôm nay`;
    }
    return `${policy.label} · ${cap} câu/ngày`;
  }

  function handleComposerKey(event, submit) {
    if (!event || event.key !== 'Enter' || event.shiftKey || event.isComposing) return false;
    event.preventDefault();
    submit();
    return true;
  }

  function safeHref(value) {
    if (typeof value !== 'string') return null;
    const candidate = value.trim();
    if (candidate.startsWith('/') && !candidate.startsWith('//') && !candidate.includes('\\')) {
      return candidate;
    }
    try {
      const parsed = new URL(candidate);
      if (parsed.protocol !== 'https:' || !parsed.hostname || parsed.username || parsed.password) return null;
      return parsed.href;
    } catch (_error) {
      return null;
    }
  }

  function sanitizeOpenOptions(options) {
    const source = options && typeof options === 'object' ? options : {};
    const sanitized = {};
    if (typeof source.question === 'string' && source.question.trim()) {
      sanitized.question = source.question.trim().slice(0, 2000);
    }
    const listingId = Number(source.listing_id);
    if (Number.isInteger(listingId) && listingId > 0) sanitized.listing_id = listingId;
    if (typeof source.ward === 'string' && source.ward.trim()) sanitized.ward = source.ward.trim().slice(0, 120);
    if (typeof source.road === 'string' && source.road.trim()) sanitized.road = source.road.trim().slice(0, 180);
    return sanitized;
  }

  function questionFromOpenOptions(options) {
    const payload = sanitizeOpenOptions(options);
    if (payload.question) return payload.question;
    const location = [payload.road, payload.ward].filter(Boolean).join(', ');
    if (payload.listing_id && location) return `Phân tích lô #${payload.listing_id} tại ${location}`;
    if (payload.listing_id) return `Phân tích lô #${payload.listing_id}`;
    if (location) return `Phân tích bất động sản tại ${location}`;
    return '';
  }

  function pageContextFromOpenOptions(options) {
    const payload = sanitizeOpenOptions(options);
    const context = {};
    if (payload.listing_id) context.listing_id = payload.listing_id;
    if (payload.ward) context.ward = payload.ward;
    if (payload.road) context.road = payload.road;
    return context;
  }

  function consumeHandoff(storage) {
    if (!storage) return null;
    let raw = null;
    try {
      raw = storage.getItem(HANDOFF_STORAGE_KEY);
    } catch (_error) {
      return null;
    } finally {
      try { storage.removeItem(HANDOFF_STORAGE_KEY); } catch (_error) { /* one-time cleanup is best effort */ }
    }
    if (!raw) return null;
    try {
      const parsed = sanitizeOpenOptions(JSON.parse(raw));
      return Object.keys(parsed).length ? parsed : null;
    } catch (_error) {
      return null;
    }
  }

  function openWithHandoff(options, { storage, navigate, workspace = null }) {
    const payload = sanitizeOpenOptions(options);
    if (workspace) {
      if (Object.keys(payload).length) workspace.setContext(payload);
      workspace.focusComposer();
      return true;
    }
    if (storage && Object.keys(payload).length) {
      try { storage.setItem(HANDOFF_STORAGE_KEY, JSON.stringify(payload)); } catch (_error) { /* navigate without private context */ }
    }
    navigate('/hoi-radar-bds');
    return true;
  }

  function makeElement(documentRef, tagName, className, text) {
    const element = documentRef.createElement(tagName);
    if (className) element.setAttribute('class', className);
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function setData(element, name, value) {
    element.setAttribute(`data-${name}`, value === undefined ? '' : String(value));
    return element;
  }

  function formatMetricValue(value) {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'object') {
      try {
        return JSON.stringify(value);
      } catch (_error) {
        return '—';
      }
    }
    return String(value);
  }

  function formatDate(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }

  function appendTextList(documentRef, parent, items, className) {
    if (!Array.isArray(items) || items.length === 0) return;
    const list = makeElement(documentRef, 'ul', className);
    items.forEach((item) => list.append(makeElement(documentRef, 'li', '', item)));
    parent.append(list);
  }

  function appendDisclosure(documentRef, parent, title, content, listItems) {
    if (!content && (!Array.isArray(listItems) || listItems.length === 0)) return;
    const details = makeElement(documentRef, 'details', 'radar-ask-disclosure');
    details.append(makeElement(documentRef, 'summary', '', title));
    if (content) details.append(makeElement(documentRef, 'p', '', content));
    appendTextList(documentRef, details, listItems, 'radar-ask-answer-list');
    parent.append(details);
  }

  function renderSourceCards(documentRef, cards, compact) {
    const section = makeElement(documentRef, 'section', compact ? 'radar-ask-sources is-compact' : 'radar-ask-sources');
    setData(section, 'source-list');
    const title = makeElement(documentRef, 'h3', '', compact ? 'Nguồn tham chiếu' : 'Nguồn & cách tính');
    section.append(title);
    (Array.isArray(cards) ? cards : []).forEach((card, index) => {
      const source = makeElement(documentRef, 'article', 'radar-ask-source-card');
      setData(source, 'source-card', card && card.evidence_id || index + 1);
      const heading = makeElement(documentRef, 'h4', 'radar-ask-source-title');
      heading.append(makeElement(documentRef, 'span', 'radar-ask-source-index', String(index + 1)));
      const href = safeHref(card && card.href);
      if (href) {
        const link = makeElement(documentRef, 'a', '', card && card.title || 'Nguồn dữ liệu');
        link.setAttribute('href', href);
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener noreferrer');
        heading.append(link);
      } else {
        heading.append(makeElement(documentRef, 'span', '', card && card.title || 'Nguồn dữ liệu'));
      }
      source.append(heading);
      const meta = makeElement(documentRef, 'p', 'radar-ask-source-meta');
      const kind = card && card.source_kind ? String(card.source_kind).replaceAll('_', ' ') : 'Radar BDS';
      const stamp = formatDate(card && card.as_of);
      meta.textContent = stamp ? `${kind} · Cập nhật ${stamp}` : kind;
      source.append(meta);
      section.append(source);
    });
    return section;
  }

  function renderAnswer(root, answer) {
    if (!root || !root.ownerDocument) throw new TypeError('A DOM root is required');
    const documentRef = root.ownerDocument;
    const payload = answer && typeof answer === 'object' ? answer : {};
    const article = makeElement(documentRef, 'article', 'radar-ask-answer');
    setData(article, 'answer');
    article.setAttribute('aria-label', 'Câu trả lời từ Radar BDS');

    const heading = makeElement(documentRef, 'div', 'radar-ask-answer-heading');
    heading.append(makeElement(documentRef, 'strong', '', `Radar BDS · ${DEPTH_LABELS[payload.depth] || 'Phân tích'}`));
    if (payload.verdict) {
      const verdict = makeElement(documentRef, 'span', `radar-ask-verdict is-${payload.verdict}`, VERDICT_LABELS[payload.verdict] || payload.verdict);
      setData(verdict, 'verdict', payload.verdict);
      heading.append(verdict);
    }
    article.append(heading);

    const directAnswer = makeElement(documentRef, 'p', 'radar-ask-direct-answer', payload.direct_answer || 'Chưa có nội dung trả lời.');
    setData(directAnswer, 'direct-answer');
    article.append(directAnswer);

    if (payload.answered === false || payload.verdict === 'khong_du_du_lieu') {
      const insufficient = makeElement(
        documentRef,
        'div',
        'radar-ask-insufficient',
        'Chưa đủ dữ liệu đáng tin cậy để kết luận. Hãy bổ sung khu vực, khoảng giá hoặc thông tin lô đất cụ thể.',
      );
      setData(insufficient, 'insufficient');
      insufficient.setAttribute('role', 'note');
      article.append(insufficient);
    }

    const metricLimit = payload.depth === 'fast' ? 4 : 12;
    const metrics = Array.isArray(payload.key_metrics) ? payload.key_metrics.slice(0, metricLimit) : [];
    if (metrics.length) {
      const grid = makeElement(documentRef, 'dl', 'radar-ask-metrics');
      metrics.forEach((metric) => {
        const item = makeElement(documentRef, 'div', 'radar-ask-metric');
        setData(item, 'key-metric');
        item.append(makeElement(documentRef, 'dt', '', metric && metric.label || 'Chỉ số'));
        const value = makeElement(documentRef, 'dd', '', formatMetricValue(metric && metric.value));
        if (metric && metric.unit) value.append(makeElement(documentRef, 'small', '', ` ${metric.unit}`));
        item.append(value);
        grid.append(item);
      });
      article.append(grid);
    }

    const claims = Array.isArray(payload.claims) ? payload.claims : [];
    if (claims.length && payload.depth !== 'fast') {
      const claimList = makeElement(documentRef, 'ul', 'radar-ask-claims');
      claims.forEach((claim) => {
        const item = makeElement(documentRef, 'li', '', claim && claim.text || '');
        (Array.isArray(claim && claim.evidence_ids) ? claim.evidence_ids : []).forEach((evidenceId) => {
          const citation = makeElement(documentRef, 'span', 'radar-ask-citation', evidenceId);
          setData(citation, 'citation', evidenceId);
          item.append(citation);
        });
        claimList.append(item);
      });
      article.append(claimList);
    }

    const deepDetails = makeElement(documentRef, 'div', 'radar-ask-deep-details');
    setData(deepDetails, 'deep-details');
    deepDetails.hidden = payload.depth === 'fast';
    appendDisclosure(documentRef, deepDetails, 'Luận điểm thuận', payload.favorable_thesis);
    appendDisclosure(documentRef, deepDetails, 'Phản biện', payload.counter_thesis);
    appendDisclosure(documentRef, deepDetails, 'Rủi ro cần lưu ý', null, payload.risks);
    const confidenceText = typeof payload.confidence === 'number'
      ? `Mức tin cậy ${(payload.confidence * 100).toFixed(0)}%`
      : null;
    appendDisclosure(documentRef, deepDetails, 'Độ tin cậy', confidenceText, payload.confidence_reasons);
    appendDisclosure(documentRef, deepDetails, 'Việc nên kiểm tra tiếp', null, payload.next_checks);
    article.append(deepDetails);

    const sourceCards = Array.isArray(payload.source_cards) ? payload.source_cards : [];
    if (sourceCards.length) {
      article.append(renderSourceCards(documentRef, sourceCards, true));
      const openEvidence = makeElement(documentRef, 'button', 'radar-ask-open-evidence', 'Nguồn & cách tính');
      openEvidence.setAttribute('type', 'button');
      setData(openEvidence, 'open-evidence');
      article.append(openEvidence);
    }

    if (payload.as_of) {
      const asOf = makeElement(documentRef, 'p', 'radar-ask-as-of', `Dữ liệu cập nhật đến ${formatDate(payload.as_of)}`);
      setData(asOf, 'as-of');
      article.append(asOf);
    }

    if (Array.isArray(payload.suggested_followups) && payload.suggested_followups.length) {
      const followups = makeElement(documentRef, 'div', 'radar-ask-followups');
      followups.append(makeElement(documentRef, 'span', '', 'Hỏi tiếp'));
      payload.suggested_followups.forEach((question) => {
        const button = makeElement(documentRef, 'button', 'radar-ask-followup', question);
        button.setAttribute('type', 'button');
        setData(button, 'suggested-question', question);
        followups.append(button);
      });
      article.append(followups);
    }

    root.replaceChildren(article);
    return article;
  }

  function renderRunState(root, run) {
    if (!root || !root.ownerDocument) throw new TypeError('A DOM root is required');
    const documentRef = root.ownerDocument;
    const payload = run && typeof run === 'object' ? run : {};

    if (payload.status === 'poll_timeout') {
      const timeout = makeElement(documentRef, 'div', 'radar-ask-run-state');
      timeout.append(makeElement(documentRef, 'p', '', 'Nghiên cứu vẫn đang chạy. Bạn có thể làm mới trạng thái mà không gửi lại câu hỏi.'));
      const refresh = makeElement(documentRef, 'button', 'radar-ask-secondary-button', 'Làm mới trạng thái');
      refresh.setAttribute('type', 'button');
      setData(refresh, 'manual-refresh');
      timeout.append(refresh);
      root.replaceChildren(timeout);
      return 'poll_timeout';
    }

    const statusKind = classifyRunStatus(payload.status);
    if (statusKind === 'answer') {
      renderAnswer(root, payload.answer || {});
    } else if (statusKind === 'failed') {
      root.replaceChildren(makeElement(documentRef, 'p', 'radar-ask-error', 'Không thể hoàn tất nghiên cứu này. Vui lòng thử lại.'));
    } else if (statusKind === 'cancelled') {
      root.replaceChildren(makeElement(documentRef, 'p', 'radar-ask-cancelled', 'Nghiên cứu này đã được hủy và sẽ không tiếp tục chạy.'));
    } else {
      const pending = makeElement(documentRef, 'div', 'radar-ask-run-state');
      pending.setAttribute('role', 'status');
      pending.append(makeElement(documentRef, 'span', 'radar-ask-progress-dots', '•••'));
      pending.append(makeElement(documentRef, 'p', '', payload.status === 'running' ? 'Đang phân tích chuyên sâu…' : 'Đã xếp hàng nghiên cứu chuyên sâu…'));
      root.replaceChildren(pending);
    }
    return statusKind;
  }

  async function pollRun({ runId, fetchRun, wait, timeoutMs = 120000 }) {
    let elapsed = 0;
    let attempt = 0;
    while (elapsed < timeoutMs) {
      const delay = POLL_DELAYS_MS[Math.min(attempt, POLL_DELAYS_MS.length - 1)];
      if (elapsed + delay > timeoutMs) break;
      await wait(delay);
      elapsed += delay;
      const run = await fetchRun(runId);
      if (run && TERMINAL_STATUSES.has(run.status)) return run;
      attempt += 1;
    }
    return { run_id: runId, status: 'poll_timeout', retryable: true };
  }

  function normalizeError(error) {
    const code = String(error && error.code || 'service_unavailable');
    return {
      code,
      message: String(error && error.message || 'Dịch vụ tạm thời chưa sẵn sàng.'),
      retryAfterSeconds: Number(error && error.retryAfterSeconds || 0) || null,
      retryable: RETRYABLE_CODES.has(code),
    };
  }

  function mergeUniqueById(existing, incoming, { prepend = false } = {}) {
    const current = Array.isArray(existing) ? existing : [];
    const page = Array.isArray(incoming) ? incoming : [];
    const seen = new Set();
    const merged = [];
    const ordered = prepend ? [...page, ...current] : [...current, ...page];
    ordered.forEach((item) => {
      const identifier = item && item.id;
      if (!identifier || seen.has(identifier)) return;
      seen.add(identifier);
      merged.push(item);
    });
    return merged;
  }

  function createController({ api, view = {}, poller = pollRun, confirm = async () => true }) {
    if (!api || typeof api !== 'object') throw new TypeError('Radar Ask API adapter is required');
    const state = {
      pending: false,
      currentRunId: null,
      currentSessionId: null,
      lastQuestion: '',
      lastDepth: 'auto',
      quota: null,
      costState: 'normal',
      sessions: [],
      nextSessionCursor: null,
      currentMessages: [],
      nextMessageCursor: null,
      currentSession: null,
      pageContext: null,
    };
    const notify = (name, ...args) => {
      if (typeof view[name] === 'function') view[name](...args);
    };
    const applyMeta = (payload) => {
      if (payload && payload.quota) state.quota = payload.quota;
      if (payload && payload.cost_state && payload.cost_state.state) state.costState = payload.cost_state.state;
      notify('setQuota', state.quota, state.costState);
    };
    const applyRun = (run) => {
      if (!run) return run;
      if (run.run_id) state.currentRunId = run.run_id;
      if (run.session_id) state.currentSessionId = run.session_id;
      applyMeta(run);
      notify('showRun', run);
      return run;
    };

    const controller = {
      state,
      setPageContext(context) {
        const bounded = pageContextFromOpenOptions(context);
        state.pageContext = Object.keys(bounded).length ? bounded : null;
        return state.pageContext;
      },
      async submit(question, depth = 'auto') {
        const normalized = String(question || '').trim();
        if (state.pending || state.costState === 'locked') return { ignored: true };
        if (!normalized) return { ignored: true, reason: 'empty_question' };
        state.pending = true;
        state.lastQuestion = normalized;
        state.lastDepth = DEPTH_LABELS[depth] ? depth : 'auto';
        notify('setPending', true);
        notify('showThinking', true, normalized);
        try {
          const request = { question: normalized };
          if (state.lastDepth !== 'auto') request.requested_depth = state.lastDepth;
          if (state.currentSessionId) request.session_id = state.currentSessionId;
          if (state.pageContext) request.page_context = { ...state.pageContext };
          let run = applyRun(await api.postQuestion(request));
          if (run && classifyRunStatus(run.status) === 'pending' && typeof api.getRun === 'function') {
            run = applyRun(await poller({
              runId: run.run_id,
              fetchRun: api.getRun,
              wait: (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
              timeoutMs: 120000,
            }));
          }
          return run;
        } catch (caught) {
          const error = normalizeError(caught);
          if (error.code === 'monthly_budget_hard_stop') state.costState = 'locked';
          notify('showError', error);
          notify('setQuota', state.quota, state.costState);
          return { status: 'failed', error };
        } finally {
          state.pending = false;
          notify('showThinking', false, null);
          notify('setPending', false);
        }
      },
      async refreshRun() {
        if (!state.currentRunId || typeof api.getRun !== 'function') return null;
        try {
          return applyRun(await api.getRun(state.currentRunId));
        } catch (caught) {
          notify('showError', normalizeError(caught));
          return null;
        }
      },
      async loadSessions({ append = false } = {}) {
        if (append && !state.nextSessionCursor) return { sessions: state.sessions, next_cursor: null };
        try {
          const payload = await api.listSessions(append ? state.nextSessionCursor : null);
          state.sessions = mergeUniqueById(append ? state.sessions : [], payload && payload.sessions || []);
          state.nextSessionCursor = payload && payload.next_cursor || null;
          notify('showSessions', state.sessions, { nextCursor: state.nextSessionCursor });
          return payload;
        } catch (caught) {
          notify('showError', normalizeError(caught));
          return null;
        }
      },
      loadMoreSessions() {
        return controller.loadSessions({ append: true });
      },
      async openSession(sessionId, { appendOlder = false } = {}) {
        if (appendOlder && (!state.currentSessionId || !state.nextMessageCursor)) {
          return { session: state.currentSession, messages: state.currentMessages, next_message_cursor: null };
        }
        try {
          const payload = await api.getSession(sessionId, appendOlder ? state.nextMessageCursor : null);
          state.currentSessionId = sessionId;
          state.currentRunId = null;
          state.currentSession = payload && payload.session || state.currentSession;
          state.currentMessages = mergeUniqueById(
            appendOlder ? state.currentMessages : [],
            payload && payload.messages || [],
            { prepend: appendOlder },
          );
          state.nextMessageCursor = payload && payload.next_message_cursor || null;
          notify('showSession', {
            ...payload,
            session: state.currentSession,
            messages: state.currentMessages,
          }, { nextCursor: state.nextMessageCursor, appendedOlder: appendOlder });
          return payload;
        } catch (caught) {
          notify('showError', normalizeError(caught));
          return null;
        }
      },
      loadMoreMessages() {
        if (!state.currentSessionId) return Promise.resolve(null);
        return controller.openSession(state.currentSessionId, { appendOlder: true });
      },
      async deleteSession(sessionId) {
        if (!await confirm(sessionId)) return { cancelled: true };
        try {
          await api.deleteSession(sessionId);
          if (state.currentSessionId === sessionId) {
            state.currentSessionId = null;
            state.currentRunId = null;
            state.currentSession = null;
            state.currentMessages = [];
            state.nextMessageCursor = null;
          }
          state.sessions = state.sessions.filter((session) => session.id !== sessionId);
          notify('removeSession', sessionId);
          return { deleted: true };
        } catch (caught) {
          notify('showError', normalizeError(caught));
          return { deleted: false };
        }
      },
      async giveFeedback(messageId, rating) {
        try {
          const payload = await api.feedback(messageId, rating);
          notify('showFeedback', messageId, rating, payload);
          return payload;
        } catch (caught) {
          notify('showError', normalizeError(caught));
          return null;
        }
      },
      newConversation() {
        state.currentSessionId = null;
        state.currentRunId = null;
        state.currentSession = null;
        state.currentMessages = [];
        state.nextMessageCursor = null;
        notify('showSession', null);
      },
    };
    return controller;
  }

  class RadarAskRequestError extends Error {
    constructor(code, message, retryAfterSeconds) {
      super(message);
      this.name = 'RadarAskRequestError';
      this.code = code;
      this.retryAfterSeconds = retryAfterSeconds || null;
    }
  }

  function createApi(fetchImpl) {
    const request = async (path, options = {}) => {
      const response = await fetchImpl(path, {
        credentials: 'same-origin',
        ...options,
        headers: { Accept: 'application/json', ...(options.headers || {}) },
      });
      if (response.status === 204) return null;
      let payload = null;
      try {
        payload = await response.json();
      } catch (_error) {
        payload = null;
      }
      if (!response.ok) {
        const failure = payload && payload.error || {};
        throw new RadarAskRequestError(
          failure.code || 'service_unavailable',
          failure.message || 'Dịch vụ tạm thời chưa sẵn sàng.',
          failure.retry_after_seconds,
        );
      }
      return payload;
    };
    const jsonOptions = (method, body) => ({
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const idempotencyKey = () => {
      if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
      return `radar-ask-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    };
    return {
      postQuestion(payload) {
        const options = jsonOptions('POST', payload);
        options.headers['Idempotency-Key'] = idempotencyKey();
        return request('/api/radar-ask/questions', options);
      },
      getRun(runId) {
        return request(`/api/radar-ask/runs/${encodeURIComponent(runId)}`);
      },
      listSessions(cursor = null) {
        const params = new URLSearchParams({ limit: '50' });
        if (cursor) params.set('cursor', cursor);
        return request(`/api/radar-ask/sessions?${params.toString()}`);
      },
      getSession(sessionId, cursor = null) {
        const params = new URLSearchParams({ message_limit: '100' });
        if (cursor) params.set('message_cursor', cursor);
        return request(`/api/radar-ask/sessions/${encodeURIComponent(sessionId)}?${params.toString()}`);
      },
      deleteSession(sessionId) {
        return request(`/api/radar-ask/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
      },
      deleteAllSessions() {
        return request('/api/radar-ask/sessions', { method: 'DELETE' });
      },
      feedback(messageId, rating) {
        return request(`/api/radar-ask/messages/${encodeURIComponent(messageId)}/feedback`, jsonOptions('POST', { rating }));
      },
    };
  }

  const SHEET_FOCUS_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'textarea:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');

  function syncSheetAccessibility(sheet, { modal, open }) {
    if (!sheet) return;
    if (!modal) {
      sheet.setAttribute('role', 'complementary');
      sheet.removeAttribute('aria-modal');
      sheet.setAttribute('aria-hidden', 'false');
      sheet.inert = false;
      sheet.removeAttribute('inert');
      sheet.classList.add('is-open');
      return;
    }
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-modal', 'true');
    sheet.setAttribute('aria-hidden', open ? 'false' : 'true');
    sheet.inert = !open;
    if (open) sheet.removeAttribute('inert');
    else sheet.setAttribute('inert', '');
    sheet.classList[open ? 'add' : 'remove']('is-open');
  }

  function focusableSheetItems(sheet) {
    if (!sheet || typeof sheet.querySelectorAll !== 'function') return [];
    return Array.from(sheet.querySelectorAll(SHEET_FOCUS_SELECTOR)).filter((element) => {
      if (element.disabled || element.inert || element.hidden) return false;
      return element.getAttribute ? element.getAttribute('aria-hidden') !== 'true' : true;
    });
  }

  function trapSheetFocus(event, sheet) {
    if (!event || event.key !== 'Tab') return false;
    const items = focusableSheetItems(sheet);
    if (!items.length) return false;
    const first = items[0];
    const last = items[items.length - 1];
    const active = sheet.ownerDocument && sheet.ownerDocument.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
      return true;
    }
    if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
      return true;
    }
    return false;
  }

  function focusFirstInSheet(sheet) {
    const first = focusableSheetItems(sheet)[0];
    if (first) first.focus();
  }

  function initializeWorkspace(documentRef, windowRef) {
    const root = documentRef.querySelector('[data-radar-ask-app]');
    if (!root) return null;
    const query = (selector) => root.querySelector(selector);
    const conversation = query('[data-conversation]');
    const welcome = query('[data-welcome]');
    const composer = query('[data-composer]');
    const submitButton = query('[data-submit]');
    const submitLabel = query('[data-submit-label]');
    const quotaNodes = root.querySelectorAll('[data-quota]');
    const liveStatus = query('[data-live-status]');
    const historyList = query('[data-history-list]');
    const loadMoreSessionsButton = query('[data-load-more-sessions]');
    const loadMoreMessagesButton = query('[data-load-more-messages]');
    const historySheet = query('[data-history-sheet]');
    const historyScrim = query('[data-history-scrim]');
    const evidenceSheet = query('[data-evidence-sheet]');
    const evidenceContent = query('[data-evidence-content]');
    const evidenceScrim = query('[data-evidence-scrim]');
    const deleteDialog = query('[data-delete-dialog]');
    const runNodes = new Map();
    let selectedDepth = 'auto';
    let pendingDeleteResolve = null;
    let historyReturnFocus = null;
    let evidenceReturnFocus = null;
    let thinkingMessage = null;

    const setStatus = (message) => {
      if (liveStatus) liveStatus.textContent = message;
    };
    const historyIsModal = () => windowRef.matchMedia('(max-width: 640px)').matches;
    const evidenceIsModal = () => windowRef.matchMedia('(max-width: 900px)').matches;
    const closeHistory = ({ restoreFocus = true } = {}) => {
      syncSheetAccessibility(historySheet, { modal: historyIsModal(), open: false });
      historyScrim.hidden = true;
      if (restoreFocus && historyReturnFocus && typeof historyReturnFocus.focus === 'function') historyReturnFocus.focus();
      historyReturnFocus = null;
    };
    const openHistory = (trigger) => {
      historyReturnFocus = trigger || documentRef.activeElement;
      const modal = historyIsModal();
      syncSheetAccessibility(historySheet, { modal, open: true });
      historyScrim.hidden = !modal;
      if (modal) focusFirstInSheet(historySheet);
    };
    const closeEvidence = ({ restoreFocus = true } = {}) => {
      syncSheetAccessibility(evidenceSheet, { modal: evidenceIsModal(), open: false });
      evidenceScrim.hidden = true;
      if (restoreFocus && evidenceReturnFocus && typeof evidenceReturnFocus.focus === 'function') evidenceReturnFocus.focus();
      evidenceReturnFocus = null;
    };
    const showEvidence = (answer, trigger) => {
      evidenceContent.replaceChildren(renderSourceCards(documentRef, answer && answer.source_cards || [], false));
      evidenceReturnFocus = trigger || documentRef.activeElement;
      const modal = evidenceIsModal();
      syncSheetAccessibility(evidenceSheet, { modal, open: true });
      evidenceScrim.hidden = !modal;
      if (modal) focusFirstInSheet(evidenceSheet);
    };
    const syncResponsiveSheets = () => {
      syncSheetAccessibility(historySheet, { modal: historyIsModal(), open: false });
      syncSheetAccessibility(evidenceSheet, { modal: evidenceIsModal(), open: !evidenceIsModal() });
      historyScrim.hidden = true;
      evidenceScrim.hidden = true;
      historyReturnFocus = null;
      evidenceReturnFocus = null;
    };
    const showWelcome = () => {
      if (thinkingMessage) {
        thinkingMessage.remove();
        thinkingMessage = null;
      }
      conversation.replaceChildren(welcome);
      welcome.hidden = false;
      runNodes.clear();
      setStatus('Sẵn sàng nhận câu hỏi.');
    };
    const makeMessage = (role, content, messageId) => {
      const wrapper = makeElement(documentRef, 'article', `radar-ask-message is-${role}`);
      if (messageId) setData(wrapper, 'message-id', messageId);
      const avatar = makeElement(documentRef, 'span', 'radar-ask-avatar', role === 'user' ? 'Bạn' : 'R');
      avatar.setAttribute('aria-hidden', 'true');
      const body = makeElement(documentRef, 'div', 'radar-ask-message-body');
      if (role === 'user') body.append(makeElement(documentRef, 'p', '', content));
      wrapper.append(avatar, body);
      return { wrapper, body };
    };
    const removeThinking = () => {
      if (!thinkingMessage) return;
      thinkingMessage.remove();
      thinkingMessage = null;
    };
    const showThinking = (question) => {
      removeThinking();
      welcome.hidden = true;
      const current = makeMessage('assistant', '');
      current.wrapper.className += ' is-thinking';
      current.wrapper.setAttribute('aria-live', 'polite');
      const label = makeElement(documentRef, 'div', 'radar-ask-thinking');
      label.setAttribute('role', 'status');
      label.append(makeElement(documentRef, 'span', 'radar-ask-thinking-text', 'Radar đang suy nghĩ'));
      const dots = makeElement(documentRef, 'span', 'radar-ask-thinking-dots');
      dots.setAttribute('aria-hidden', 'true');
      dots.append(
        makeElement(documentRef, 'i', ''),
        makeElement(documentRef, 'i', ''),
        makeElement(documentRef, 'i', ''),
      );
      label.append(dots);
      current.body.append(label);
      thinkingMessage = current.wrapper;
      conversation.append(thinkingMessage);
      thinkingMessage.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      setStatus(question ? 'Radar BDS đang soạn câu trả lời.' : 'Radar BDS đang xử lý.');
    };
    const attachAnswerActions = (node, answer, messageId) => {
      const sourceButton = node.querySelector('[data-open-evidence]');
      if (sourceButton) sourceButton.addEventListener('click', () => showEvidence(answer, sourceButton));
      node.querySelectorAll('[data-suggested-question]').forEach((button) => {
        button.addEventListener('click', () => {
          composer.value = button.getAttribute('data-suggested-question') || '';
          composer.focus();
        });
      });
      if (messageId) {
        const feedback = makeElement(documentRef, 'div', 'radar-ask-feedback');
        ['helpful', 'not_helpful'].forEach((rating) => {
          const label = rating === 'helpful' ? 'Hữu ích' : 'Chưa hữu ích';
          const button = makeElement(documentRef, 'button', 'radar-ask-feedback-button', label);
          button.setAttribute('type', 'button');
          button.setAttribute('aria-pressed', 'false');
          setData(button, 'feedback', rating);
          setData(button, 'message', messageId);
          feedback.append(button);
        });
        node.append(feedback);
      }
    };

    const view = {
      setPending(value) {
        submitButton.disabled = value || root.getAttribute('data-cost-state') === 'locked';
        composer.setAttribute('aria-busy', String(value));
        submitLabel.textContent = value ? 'Đang gửi…' : 'Gửi câu hỏi';
        if (value) setStatus('Đang gửi câu hỏi tới Radar BDS.');
      },
      showThinking(value, question) {
        if (value) showThinking(question);
        else removeThinking();
      },
      setQuota(quotaPayload, costState) {
        const label = quotaLabel(quotaPayload || { tier: root.getAttribute('data-tier') });
        quotaNodes.forEach((node) => { node.textContent = label; });
        root.setAttribute('data-cost-state', costState || 'normal');
        if (costState === 'locked') {
          composer.disabled = true;
          submitButton.disabled = true;
          setStatus('Radar Ask đang tạm dừng để bảo vệ ngân sách tháng.');
        }
      },
      showRun(run) {
        removeThinking();
        welcome.hidden = true;
        let current = runNodes.get(run.run_id);
        if (!current) {
          current = makeMessage('assistant', '');
          setData(current.wrapper, 'run-id', run.run_id || 'pending');
          conversation.append(current.wrapper);
          runNodes.set(run.run_id, current);
        }
        const statusKind = renderRunState(current.body, run);
        if (statusKind === 'answer') {
          attachAnswerActions(current.body, run.answer || {}, null);
          setStatus(run.status === 'clarifying' ? 'Radar BDS cần bạn làm rõ thêm.' : 'Radar BDS đã hoàn tất câu trả lời.');
        } else if (statusKind === 'failed') {
          setStatus('Nghiên cứu không hoàn tất.');
        } else if (statusKind === 'cancelled') {
          setStatus('Nghiên cứu đã được hủy.');
        } else if (statusKind === 'poll_timeout') {
          setStatus('Đã dừng tự động kiểm tra sau 2 phút.');
        } else {
          setStatus(run.status === 'running' ? 'Đang phân tích chuyên sâu.' : 'Đã xếp hàng nghiên cứu chuyên sâu.');
        }
        current.wrapper.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      },
      showError(error) {
        removeThinking();
        const block = makeElement(documentRef, 'div', 'radar-ask-error');
        block.setAttribute('role', 'alert');
        block.append(makeElement(documentRef, 'strong', '', error.code === 'monthly_budget_hard_stop' ? 'Radar Ask đang tạm dừng' : 'Chưa thể trả lời'));
        block.append(makeElement(documentRef, 'p', '', error.message));
        if (error.retryable) {
          const retry = makeElement(documentRef, 'button', 'radar-ask-secondary-button', 'Thử lại');
          retry.setAttribute('type', 'button');
          setData(retry, 'retry-submit');
          block.append(retry);
        }
        conversation.append(block);
        setStatus(error.message);
      },
      showSessions(sessions, { nextCursor = null } = {}) {
        historyList.replaceChildren();
        loadMoreSessionsButton.hidden = !nextCursor;
        loadMoreSessionsButton.disabled = false;
        if (!sessions.length) {
          historyList.append(makeElement(documentRef, 'p', 'radar-ask-history-empty', 'Chưa có cuộc trò chuyện.'));
          return;
        }
        sessions.forEach((session) => {
          const row = makeElement(documentRef, 'div', 'radar-ask-history-row');
          setData(row, 'session-row', session.id);
          const open = makeElement(documentRef, 'button', 'radar-ask-history-item');
          open.setAttribute('type', 'button');
          setData(open, 'open-session', session.id);
          open.append(makeElement(documentRef, 'strong', '', session.title || 'Cuộc trò chuyện'));
          open.append(makeElement(documentRef, 'time', '', formatDate(session.updated_at)));
          const remove = makeElement(documentRef, 'button', 'radar-ask-history-delete', 'Xóa');
          remove.setAttribute('type', 'button');
          remove.setAttribute('aria-label', `Xóa ${session.title || 'cuộc trò chuyện'}`);
          setData(remove, 'delete-session', session.id);
          row.append(open, remove);
          historyList.append(row);
        });
      },
      showSession(payload, { nextCursor = null, appendedOlder = false } = {}) {
        removeThinking();
        if (!payload) {
          showWelcome();
          composer.focus();
          return;
        }
        loadMoreMessagesButton.hidden = !nextCursor;
        loadMoreMessagesButton.disabled = false;
        conversation.replaceChildren(loadMoreMessagesButton);
        runNodes.clear();
        (payload.messages || []).forEach((message) => {
          const rendered = makeMessage(message.role, message.content || '', message.id);
          if (message.role === 'assistant' && message.answer) {
            renderAnswer(rendered.body, message.answer);
            attachAnswerActions(rendered.body, message.answer, message.id);
          }
          conversation.append(rendered.wrapper);
        });
        setStatus(`Đã mở ${payload.session && payload.session.title || 'cuộc trò chuyện'}.`);
        closeHistory();
        if (appendedOlder) {
          if (!loadMoreMessagesButton.hidden) loadMoreMessagesButton.focus();
          else conversation.focus({ preventScroll: true });
        } else {
          composer.focus();
        }
      },
      removeSession(sessionId) {
        const row = historyList.querySelector(`[data-session-row="${sessionId}"]`);
        if (row) row.remove();
        if (!controller.state.currentSessionId) showWelcome();
      },
      showFeedback(messageId, rating) {
        root.querySelectorAll(`[data-message="${messageId}"]`).forEach((button) => {
          button.setAttribute('aria-pressed', String(button.getAttribute('data-feedback') === rating));
        });
        setStatus('Cảm ơn bạn đã đánh giá câu trả lời.');
      },
    };

    const api = createApi(windowRef.fetch.bind(windowRef));
    const askForDelete = () => new Promise((resolve) => {
      pendingDeleteResolve = resolve;
      if (typeof deleteDialog.showModal === 'function') deleteDialog.showModal();
      else deleteDialog.setAttribute('open', '');
    });
    const controller = createController({ api, view, confirm: askForDelete });
    root._radarAskController = controller;

    const submit = async () => {
      const question = composer.value.trim();
      if (!question) {
        setStatus('Hãy nhập câu hỏi trước khi gửi.');
        composer.focus();
        return;
      }
      welcome.hidden = true;
      const userMessage = makeMessage('user', question);
      conversation.append(userMessage.wrapper);
      composer.value = '';
      const result = await controller.submit(question, selectedDepth);
      if (result && classifyRunStatus(result.status) === 'answer' && result.session_id) {
        await controller.openSession(result.session_id);
      }
      await controller.loadSessions();
      composer.focus();
    };

    query('[data-composer-form]').addEventListener('submit', (event) => {
      event.preventDefault();
      submit();
    });
    composer.addEventListener('keydown', (event) => handleComposerKey(event, submit));
    root.querySelectorAll('[data-depth]').forEach((button) => {
      button.addEventListener('click', () => {
        selectedDepth = button.getAttribute('data-depth');
        root.querySelectorAll('[data-depth]').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
        setStatus(`Đã chọn độ sâu ${DEPTH_LABELS[selectedDepth]}.`);
      });
    });
    root.querySelectorAll('[data-sample-question]').forEach((button) => {
      button.addEventListener('click', () => {
        composer.value = button.textContent.trim();
        composer.focus();
        setStatus('Đã đưa câu hỏi mẫu vào ô soạn thảo.');
      });
    });
    query('[data-new-conversation]').addEventListener('click', () => controller.newConversation());
    root.querySelectorAll('[data-history-open]').forEach((button) => button.addEventListener('click', () => openHistory(button)));
    query('[data-history-close]').addEventListener('click', closeHistory);
    historyScrim.addEventListener('click', closeHistory);
    query('[data-evidence-close]').addEventListener('click', closeEvidence);
    evidenceScrim.addEventListener('click', closeEvidence);
    historySheet.addEventListener('keydown', (event) => trapSheetFocus(event, historySheet));
    evidenceSheet.addEventListener('keydown', (event) => trapSheetFocus(event, evidenceSheet));
    documentRef.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      if (evidenceIsModal() && evidenceSheet.getAttribute('aria-hidden') === 'false') {
        event.preventDefault();
        closeEvidence();
      } else if (historyIsModal() && historySheet.getAttribute('aria-hidden') === 'false') {
        event.preventDefault();
        closeHistory();
      }
    });
    historyList.addEventListener('click', (event) => {
      const open = event.target.closest('[data-open-session]');
      const remove = event.target.closest('[data-delete-session]');
      if (open) controller.openSession(open.getAttribute('data-open-session'));
      if (remove) controller.deleteSession(remove.getAttribute('data-delete-session'));
    });
    loadMoreSessionsButton.addEventListener('click', async () => {
      loadMoreSessionsButton.disabled = true;
      try { await controller.loadMoreSessions(); } finally { loadMoreSessionsButton.disabled = false; }
    });
    loadMoreMessagesButton.addEventListener('click', async () => {
      loadMoreMessagesButton.disabled = true;
      try { await controller.loadMoreMessages(); } finally { loadMoreMessagesButton.disabled = false; }
    });
    conversation.addEventListener('click', (event) => {
      const feedback = event.target.closest('[data-feedback]');
      const refresh = event.target.closest('[data-manual-refresh]');
      const retry = event.target.closest('[data-retry-submit]');
      if (feedback) controller.giveFeedback(feedback.getAttribute('data-message'), feedback.getAttribute('data-feedback'));
      if (refresh) controller.refreshRun();
      if (retry) controller.submit(controller.state.lastQuestion, controller.state.lastDepth);
    });
    query('[data-delete-cancel]').addEventListener('click', () => {
      if (pendingDeleteResolve) pendingDeleteResolve(false);
      pendingDeleteResolve = null;
      deleteDialog.close();
    });
    query('[data-delete-confirm]').addEventListener('click', () => {
      if (pendingDeleteResolve) pendingDeleteResolve(true);
      pendingDeleteResolve = null;
      deleteDialog.close();
    });
    deleteDialog.addEventListener('cancel', (event) => {
      event.preventDefault();
      if (pendingDeleteResolve) pendingDeleteResolve(false);
      pendingDeleteResolve = null;
      deleteDialog.close();
    });
    query('[data-theme-toggle]').addEventListener('click', () => {
      const next = documentRef.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      documentRef.documentElement.setAttribute('data-theme', next);
      try { windowRef.localStorage.setItem('radar_theme', next); } catch (_error) { /* storage may be unavailable */ }
    });

    view.setQuota({ tier: root.getAttribute('data-tier') }, 'normal');
    syncResponsiveSheets();
    windowRef.addEventListener('resize', syncResponsiveSheets, { passive: true });
    controller.loadSessions();
    let handoff = null;
    try { handoff = consumeHandoff(windowRef.sessionStorage); } catch (_error) { handoff = null; }
    if (handoff) {
      controller.setPageContext(handoff);
      const suggestedQuestion = questionFromOpenOptions(handoff);
      if (suggestedQuestion) composer.value = suggestedQuestion;
    }
    setStatus('Sẵn sàng nhận câu hỏi.');
    return {
      controller,
      focusComposer: () => composer.focus(),
      setContext: (options) => {
        const payload = sanitizeOpenOptions(options);
        if (!Object.keys(payload).length) return false;
        controller.setPageContext(payload);
        const suggestedQuestion = questionFromOpenOptions(payload);
        if (suggestedQuestion) composer.value = suggestedQuestion;
        return true;
      },
    };
  }

  let browserWorkspace = null;

  function open(options = {}) {
    if (typeof window === 'undefined') return false;
    let storage = null;
    try { storage = window.sessionStorage; } catch (_error) { storage = null; }
    return openWithHandoff(options, {
      storage,
      workspace: browserWorkspace,
      navigate: (path) => window.location.assign(path),
    });
  }

  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    const boot = () => { browserWorkspace = initializeWorkspace(document, window); };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
    else boot();
  }

  return {
    POLL_DELAYS_MS,
    ANSWER_STATUSES,
    HANDOFF_STORAGE_KEY,
    PENDING_STATUSES,
    TERMINAL_STATUSES,
    TIER_CAPS,
    classifyRunStatus,
    consumeHandoff,
    createApi,
    createController,
    handleComposerKey,
    initializeWorkspace,
    normalizeError,
    open,
    openWithHandoff,
    pollRun,
    quotaLabel,
    renderAnswer,
    renderRunState,
    renderSourceCards,
    safeHref,
    sanitizeOpenOptions,
    syncSheetAccessibility,
    trapSheetFocus,
  };
});

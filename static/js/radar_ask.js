(function radarAskModule(globalScope, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') {
    window.RadarAsk = Object.assign(window.RadarAsk || {}, api);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function buildRadarAsk() {
  'use strict';

  const POLL_DELAYS_MS = Object.freeze([1000, 2000, 3000, 5000]);
  const TERMINAL_STATUSES = new Set(['completed', 'failed', 'insufficient', 'cancelled']);
  const RETRYABLE_CODES = new Set([
    'provider_unavailable',
    'service_unavailable',
    'worker_unavailable',
    'burst_limit_exceeded',
  ]);
  const TIER_CAPS = Object.freeze({
    free: { label: 'Free', cap: 5, capLabel: 'Free · 5 câu/ngày' },
    vip: { label: 'VIP', cap: 20, capLabel: 'VIP · 20 câu/ngày' },
    admin: { label: 'Admin', cap: 100, capLabel: 'Admin · 100 câu/ngày' },
  });
  const DEPTH_LABELS = Object.freeze({ fast: 'Nhanh', standard: 'Phân tích', deep: 'Chuyên sâu' });
  const VERDICT_LABELS = Object.freeze({
    dang_xem: 'Đáng xem',
    can_kiem_tra_them: 'Cần kiểm tra thêm',
    rui_ro_cao: 'Rủi ro cao',
    khong_du_du_lieu: 'Chưa đủ dữ liệu',
  });

  function quotaLabel(quota) {
    const tier = String(quota && quota.tier || 'free').toLowerCase();
    const policy = TIER_CAPS[tier] || TIER_CAPS.free;
    if (Number.isInteger(quota && quota.remaining) && quota.remaining >= 0) {
      return `${policy.label} · còn ${quota.remaining}/${policy.cap} câu hôm nay`;
    }
    return policy.capLabel;
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

  function createController({ api, view = {}, poller = pollRun, confirm = async () => true }) {
    if (!api || typeof api !== 'object') throw new TypeError('Radar Ask API adapter is required');
    const state = {
      pending: false,
      currentRunId: null,
      currentSessionId: null,
      lastQuestion: '',
      lastDepth: 'standard',
      quota: null,
      costState: 'normal',
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

    return {
      state,
      async submit(question, depth = 'standard') {
        const normalized = String(question || '').trim();
        if (state.pending || state.costState === 'locked') return { ignored: true };
        if (!normalized) return { ignored: true, reason: 'empty_question' };
        state.pending = true;
        state.lastQuestion = normalized;
        state.lastDepth = DEPTH_LABELS[depth] ? depth : 'standard';
        notify('setPending', true);
        try {
          const request = { question: normalized, requested_depth: state.lastDepth };
          if (state.currentSessionId) request.session_id = state.currentSessionId;
          let run = applyRun(await api.postQuestion(request));
          if (run && ['created', 'queued', 'running'].includes(run.status) && typeof api.getRun === 'function') {
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
      async loadSessions() {
        try {
          const payload = await api.listSessions();
          notify('showSessions', payload && payload.sessions || []);
          return payload;
        } catch (caught) {
          notify('showError', normalizeError(caught));
          return null;
        }
      },
      async openSession(sessionId) {
        try {
          const payload = await api.getSession(sessionId);
          state.currentSessionId = sessionId;
          state.currentRunId = null;
          notify('showSession', payload);
          return payload;
        } catch (caught) {
          notify('showError', normalizeError(caught));
          return null;
        }
      },
      async deleteSession(sessionId) {
        if (!await confirm(sessionId)) return { cancelled: true };
        try {
          await api.deleteSession(sessionId);
          if (state.currentSessionId === sessionId) {
            state.currentSessionId = null;
            state.currentRunId = null;
          }
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
        notify('showSession', null);
      },
    };
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
      listSessions() {
        return request('/api/radar-ask/sessions?limit=50');
      },
      getSession(sessionId) {
        return request(`/api/radar-ask/sessions/${encodeURIComponent(sessionId)}?message_limit=100`);
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

  function initializeWorkspace(documentRef, windowRef) {
    const root = documentRef.querySelector('[data-radar-ask-app]');
    if (!root) return null;
    const query = (selector) => root.querySelector(selector);
    const conversation = query('[data-conversation]');
    const welcome = query('[data-welcome]');
    const composer = query('[data-composer]');
    const submitButton = query('[data-submit]');
    const quotaNodes = root.querySelectorAll('[data-quota]');
    const liveStatus = query('[data-live-status]');
    const historyList = query('[data-history-list]');
    const historySheet = query('[data-history-sheet]');
    const historyScrim = query('[data-history-scrim]');
    const evidenceSheet = query('[data-evidence-sheet]');
    const evidenceContent = query('[data-evidence-content]');
    const evidenceScrim = query('[data-evidence-scrim]');
    const deleteDialog = query('[data-delete-dialog]');
    const runNodes = new Map();
    let selectedDepth = 'standard';
    let pendingDeleteResolve = null;

    const setStatus = (message) => {
      if (liveStatus) liveStatus.textContent = message;
    };
    const closeHistory = () => {
      historySheet.classList.remove('is-open');
      historySheet.setAttribute('aria-hidden', windowRef.matchMedia('(max-width: 640px)').matches ? 'true' : 'false');
      historyScrim.hidden = true;
    };
    const openHistory = () => {
      historySheet.classList.add('is-open');
      historySheet.setAttribute('aria-hidden', 'false');
      historyScrim.hidden = false;
      const close = query('[data-history-close]');
      if (close) close.focus();
    };
    const closeEvidence = () => {
      evidenceSheet.classList.remove('is-open');
      root.classList.add('is-evidence-closed');
      evidenceScrim.hidden = true;
    };
    const showEvidence = (answer) => {
      evidenceContent.replaceChildren(renderSourceCards(documentRef, answer && answer.source_cards || [], false));
      root.classList.remove('is-evidence-closed');
      evidenceSheet.classList.add('is-open');
      evidenceScrim.hidden = false;
      const close = query('[data-evidence-close]');
      if (windowRef.matchMedia('(max-width: 640px)').matches && close) close.focus();
    };
    const showWelcome = () => {
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
    const attachAnswerActions = (node, answer, messageId) => {
      const sourceButton = node.querySelector('[data-open-evidence]');
      if (sourceButton) sourceButton.addEventListener('click', () => showEvidence(answer));
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
        submitButton.textContent = value ? 'Đang gửi…' : 'Gửi câu hỏi';
        if (value) setStatus('Đang gửi câu hỏi tới Radar BDS.');
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
        welcome.hidden = true;
        let current = runNodes.get(run.run_id);
        if (!current) {
          current = makeMessage('assistant', '');
          setData(current.wrapper, 'run-id', run.run_id || 'pending');
          conversation.append(current.wrapper);
          runNodes.set(run.run_id, current);
        }
        if (run.status === 'completed' || run.status === 'insufficient') {
          renderAnswer(current.body, run.answer || {});
          attachAnswerActions(current.body, run.answer || {}, null);
          setStatus('Radar BDS đã hoàn tất câu trả lời.');
        } else if (run.status === 'failed') {
          current.body.replaceChildren(makeElement(documentRef, 'p', 'radar-ask-error', 'Không thể hoàn tất nghiên cứu này. Vui lòng thử lại.'));
          setStatus('Nghiên cứu không hoàn tất.');
        } else if (run.status === 'poll_timeout') {
          const timeout = makeElement(documentRef, 'div', 'radar-ask-run-state');
          timeout.append(makeElement(documentRef, 'p', '', 'Nghiên cứu vẫn đang chạy. Bạn có thể làm mới trạng thái mà không gửi lại câu hỏi.'));
          const refresh = makeElement(documentRef, 'button', 'radar-ask-secondary-button', 'Làm mới trạng thái');
          refresh.setAttribute('type', 'button');
          setData(refresh, 'manual-refresh');
          timeout.append(refresh);
          current.body.replaceChildren(timeout);
          setStatus('Đã dừng tự động kiểm tra sau 2 phút.');
        } else {
          const pending = makeElement(documentRef, 'div', 'radar-ask-run-state');
          pending.setAttribute('role', 'status');
          pending.append(makeElement(documentRef, 'span', 'radar-ask-progress-dots', '•••'));
          pending.append(makeElement(documentRef, 'p', '', run.status === 'running' ? 'Đang phân tích chuyên sâu…' : 'Đã xếp hàng nghiên cứu chuyên sâu…'));
          current.body.replaceChildren(pending);
          setStatus(run.status === 'running' ? 'Đang phân tích chuyên sâu.' : 'Đã xếp hàng nghiên cứu chuyên sâu.');
        }
        current.wrapper.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      },
      showError(error) {
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
      showSessions(sessions) {
        historyList.replaceChildren();
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
      showSession(payload) {
        if (!payload) {
          showWelcome();
          composer.focus();
          return;
        }
        conversation.replaceChildren();
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
        composer.focus();
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
      if (result && ['completed', 'insufficient'].includes(result.status) && result.session_id) {
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
    root.querySelectorAll('[data-history-open]').forEach((button) => button.addEventListener('click', openHistory));
    query('[data-history-close]').addEventListener('click', closeHistory);
    historyScrim.addEventListener('click', closeHistory);
    query('[data-evidence-close]').addEventListener('click', closeEvidence);
    evidenceScrim.addEventListener('click', closeEvidence);
    historyList.addEventListener('click', (event) => {
      const open = event.target.closest('[data-open-session]');
      const remove = event.target.closest('[data-delete-session]');
      if (open) controller.openSession(open.getAttribute('data-open-session'));
      if (remove) controller.deleteSession(remove.getAttribute('data-delete-session'));
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
    if (windowRef.matchMedia('(max-width: 640px)').matches) closeHistory();
    controller.loadSessions();
    const params = new URLSearchParams(windowRef.location.search);
    const initialQuestion = params.get('question');
    if (initialQuestion) composer.value = initialQuestion.slice(0, 2000);
    setStatus('Sẵn sàng nhận câu hỏi.');
    return { controller, focusComposer: () => composer.focus(), setQuestion: (value) => { composer.value = value; } };
  }

  let browserWorkspace = null;

  function open(options = {}) {
    const question = typeof options.question === 'string' ? options.question.slice(0, 2000) : '';
    if (browserWorkspace) {
      if (question) browserWorkspace.setQuestion(question);
      browserWorkspace.focusComposer();
      return true;
    }
    if (typeof window === 'undefined') return false;
    const url = new URL('/hoi-radar-bds', window.location.origin);
    if (question) url.searchParams.set('question', question);
    if (Number.isInteger(Number(options.listing_id)) && Number(options.listing_id) > 0) {
      url.searchParams.set('listing_id', String(Number(options.listing_id)));
    }
    ['ward', 'road'].forEach((key) => {
      if (typeof options[key] === 'string' && options[key].trim()) url.searchParams.set(key, options[key].trim().slice(0, 180));
    });
    window.location.assign(url.pathname + url.search);
    return true;
  }

  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    const boot = () => { browserWorkspace = initializeWorkspace(document, window); };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
    else boot();
  }

  return {
    POLL_DELAYS_MS,
    TERMINAL_STATUSES,
    TIER_CAPS,
    createApi,
    createController,
    handleComposerKey,
    initializeWorkspace,
    normalizeError,
    open,
    pollRun,
    quotaLabel,
    renderAnswer,
    renderSourceCards,
    safeHref,
  };
});

// Lead capture, chat widget, analytics tracking, and tier CTA flows.
const LEAD_CAPTURE = {
  listingId: null,
  listingUrl: '',
  sourceContext: 'signal',
  urgency: 'standard'
};

function captureLeadAndOpen(listingId, listingUrl, sourceContext = 'signal', urgency = 'standard') {
  LEAD_CAPTURE.listingId = listingId ? Number(listingId) : null;
  LEAD_CAPTURE.listingUrl = listingUrl || '';
  LEAD_CAPTURE.sourceContext = sourceContext || 'signal';
  LEAD_CAPTURE.urgency = urgency || 'standard';
  openGuestLeadForm(listingId, sourceContext, listingUrl);
}

function closeLeadCaptureModal() {
  const modal = document.getElementById('leadCaptureModal');
  const errorEl = document.getElementById('leadError');
  if (errorEl) errorEl.textContent = '';
  if (modal) modal.style.display = 'none';
}

function _openZaloDirect() {
  const zaloHref = 'https://zalo.me/0343216024';
  const w = window.open(zaloHref, '_blank', 'noopener,noreferrer');
  if (!w) window.location.href = zaloHref;
}

function _isLikelyPhone(v) {
  const digits = (v || '').replace(/\D/g, '');
  return digits.length >= 9;
}

async function submitLeadAndOpenZalo() {
  const input = document.getElementById('leadPhoneInput');
  const errorEl = document.getElementById('leadError');
  const raw = (input?.value || '').trim();

  if (!raw) {
    closeLeadCaptureModal();
    _openZaloDirect();
    return;
  }
  if (!_isLikelyPhone(raw)) {
    if (errorEl) errorEl.textContent = 'Số Zalo chưa hợp lệ, vui lòng kiểm tra lại.';
    return;
  }

  try {
    const res = await fetch('/api/leads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        listing_id: LEAD_CAPTURE.listingId,
        listing_url: LEAD_CAPTURE.listingUrl,
        zalo_phone: raw,
        source_context: LEAD_CAPTURE.sourceContext,
        urgency: LEAD_CAPTURE.urgency
      })
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      if (data && data.error === 'invalid_phone') {
        if (errorEl) errorEl.textContent = 'Số Zalo chưa hợp lệ, vui lòng nhập lại.';
        return;
      }
    }
  } catch (err) {
    console.warn('Lead capture failed:', err);
  } finally {
    closeLeadCaptureModal();
    _openZaloDirect();
  }
}

function skipLeadAndOpenZalo() {
  closeLeadCaptureModal();
  _openZaloDirect();
}

// Investor Assistant
let chatHistory = [];
let assistantSessionId = '';
try {
  assistantSessionId = localStorage.getItem('radarAssistantSessionId') || '';
} catch (err) {
  assistantSessionId = '';
}

function toggleChat() {
  const win = document.getElementById('chatWindow');
  win.style.display = win.style.display === 'flex' ? 'none' : 'flex';
  document.body.classList.toggle('chat-open', win.style.display === 'flex');
  if (win.style.display === 'flex') {
    document.getElementById('chatInput').focus();
  }
}

function assistantCheckedValues(selector) {
  return Array.from(document.querySelectorAll(selector))
    .filter((el) => el.checked)
    .map((el) => el.value);
}

function assistantInputValue(id) {
  const el = document.getElementById(id);
  return el ? (el.value || '').trim() : '';
}

function getAssistantCurrentFilters() {
  return {
    ward: assistantCheckedValues('#wardFilters input[name="ward"]'),
    property_type: assistantCheckedValues('#filterForm input[name="prop_type"]'),
    mos_min: assistantInputValue('mosSlider') || '0',
    only_drops: !!document.querySelector('input[name="only_drops"]')?.checked,
    price_min: assistantInputValue('priceMin'),
    price_max: assistantInputValue('priceMax'),
    area_min: assistantInputValue('areaMin'),
    area_max: assistantInputValue('areaMax'),
    q: typeof getKeywordSearchValue === 'function' ? getKeywordSearchValue() : ''
  };
}

function getAssistantPageContext() {
  return {
    tab: typeof activeTabId === 'function' ? activeTabId() : 'signals',
    path: window.location.pathname,
    tier: window.USER_TIER || 'guest'
  };
}

async function sendMessage(messageOverride = '') {
  const input = document.getElementById('chatInput');
  const msg = (messageOverride || input.value || '').trim();
  if (!msg) return;

  appendMessage('user', msg);
  if (input) input.value = '';

  const loadingId = 'loading-' + Date.now();
  const msgContainer = document.getElementById('chatMessages');
  const loadingDiv = document.createElement('div');
  loadingDiv.className = 'message bot';
  loadingDiv.id = loadingId;
  loadingDiv.innerText = 'Radar Assistant đang kiểm tra dữ liệu...';
  msgContainer.appendChild(loadingDiv);
  msgContainer.scrollTop = msgContainer.scrollHeight;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: msg,
        session_id: assistantSessionId,
        page_context: getAssistantPageContext(),
        current_filters: getAssistantCurrentFilters()
      })
    });
    const data = await res.json().catch(() => ({}));

    loadingDiv.remove();
    if (!res.ok || data.ok === false) {
      appendMessage('bot', data.error === 'rate_limited'
        ? 'Bạn hỏi hơi nhanh. Thử lại sau một chút nhé.'
        : 'Assistant đang bận dữ liệu, thử lại sau một chút.');
      return;
    }

    if (data.session_id) {
      assistantSessionId = data.session_id;
      try {
        localStorage.setItem('radarAssistantSessionId', assistantSessionId);
      } catch (err) { /* ignore storage failures */ }
    }
    appendAssistantResponse(data);

    chatHistory.push({ role: 'user', content: msg });
    chatHistory.push({ role: 'assistant', content: data.answer || '' });
    if (chatHistory.length > 10) chatHistory = chatHistory.slice(-10);

  } catch (err) {
    loadingDiv.innerText = 'Lỗi kết nối. Vui lòng thử lại.';
    console.error(err);
  }
}

function appendMessage(role, text) {
  const container = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.innerText = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function sendAssistantPrompt(text) {
  sendMessage(text || '');
}

function appendAssistantResponse(data) {
  const div = appendMessage('bot', data.answer || data.response || 'Mình chưa có câu trả lời phù hợp.');
  const cards = Array.isArray(data.cards) ? data.cards : [];
  if (cards.length) {
    const cardWrap = document.createElement('div');
    cardWrap.className = 'assistant-cards';
    cards.slice(0, 3).forEach((card) => {
      const item = document.createElement('article');
      item.className = 'assistant-card';
      const title = document.createElement('strong');
      title.textContent = card.title || `Tin #${card.listing_id || ''}`;
      const meta = document.createElement('span');
      const bits = [];
      if (card.ward) bits.push(card.ward);
      if (card.price_ty) bits.push(`${Number(card.price_ty).toFixed(2).replace(/\.00$/, '')} tỷ`);
      if (card.mos_pct !== undefined && card.mos_pct !== null) bits.push(`rẻ hơn ${Number(card.mos_pct).toFixed(1).replace(/\.0$/, '')}%`);
      if (card.price_dropped) bits.push('có giảm giá');
      meta.textContent = bits.join(' · ');
      item.appendChild(title);
      item.appendChild(meta);
      if (card.listing_id) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = 'Mở tin';
        btn.addEventListener('click', () => handleAssistantAction({ type: 'open_listing_memo', listing_id: card.listing_id }));
        item.appendChild(btn);
      }
      cardWrap.appendChild(item);
    });
    div.appendChild(cardWrap);
  }

  const actions = Array.isArray(data.actions) ? data.actions : [];
  if (actions.length) {
    const actionWrap = document.createElement('div');
    actionWrap.className = 'assistant-actions';
    actions.forEach((action) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'assistant-action-btn';
      btn.textContent = action.label || action.type || 'Thực hiện';
      btn.addEventListener('click', () => handleAssistantAction(action));
      actionWrap.appendChild(btn);
    });
    div.appendChild(actionWrap);
  }
}

function assistantFindCityForWard(ward) {
  const data = window.INITIAL_WARDS_BY_CITY || {};
  return Object.keys(data).find((city) => (data[city] || []).includes(ward)) || '';
}

function assistantSetValue(id, value) {
  const el = document.getElementById(id);
  if (!el || value === undefined || value === null) return;
  el.value = String(value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

function assistantSetCheckboxes(selector, selectedValues) {
  if (!Array.isArray(selectedValues) || !selectedValues.length) return;
  const selected = new Set(selectedValues.map(String));
  document.querySelectorAll(selector).forEach((el) => {
    el.checked = selected.has(String(el.value));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

function assistantFilterRequiresLogin(filter) {
  const tier = window.USER_TIER || 'guest';
  if (tier !== 'guest') return false;
  return Boolean(Number(filter?.mos_min || 0) > 0 || filter?.only_drops);
}

function applyAssistantFilter(filter) {
  const filt = filter || {};
  if (assistantFilterRequiresLogin(filt)) {
    if (window.RadarAuth && typeof RadarAuth.openAuthModal === 'function') {
      RadarAuth.openAuthModal('Đăng nhập miễn phí để dùng bộ lọc Rẻ hơn/Có giảm giá.');
    }
    return;
  }

  const wards = Array.isArray(filt.ward) ? filt.ward : (filt.ward ? [filt.ward] : []);
  if (wards.length) {
    const city = assistantFindCityForWard(wards[0]);
    if (city) {
      const cityInput = document.getElementById('cityInput');
      if (cityInput) cityInput.value = city;
      document.querySelectorAll('.city-pill').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.city === city);
      });
      if (typeof updateWardFilters === 'function') {
        const wardData = (typeof globalWardsByCity !== 'undefined' && Object.keys(globalWardsByCity || {}).length)
          ? globalWardsByCity
          : (window.INITIAL_WARDS_BY_CITY || {});
        updateWardFilters(wardData, wards, {
          preserveScroll: false,
          preserveSearch: false
        });
      }
    } else {
      assistantSetCheckboxes('#wardFilters input[name="ward"]', wards);
    }
  }

  assistantSetCheckboxes('#filterForm input[name="prop_type"]', Array.isArray(filt.property_type) ? filt.property_type : []);
  assistantSetValue('priceMin', filt.price_min);
  assistantSetValue('priceMax', filt.price_max);
  assistantSetValue('areaMin', filt.area_min);
  assistantSetValue('areaMax', filt.area_max);
  assistantSetValue('mosSlider', filt.mos_min);
  const onlyDrops = document.querySelector('input[name="only_drops"]');
  if (onlyDrops && filt.only_drops !== undefined) {
    onlyDrops.checked = !!filt.only_drops;
    onlyDrops.dispatchEvent(new Event('change', { bubbles: true }));
  }
  if (typeof syncCoreFilterVisuals === 'function') syncCoreFilterVisuals();
  const signalBtn = document.querySelector('[data-tab-target="signals"]');
  Promise.resolve(typeof switchTab === 'function' ? switchTab('signals', signalBtn || null) : null)
    .then(() => {
      if (typeof applyFilters === 'function') applyFilters();
    });
}

function prefillAssistantWatchlist(filter) {
  const filt = filter || {};
  if (!window.CURRENT_USER) {
    if (window.RadarAuth && typeof RadarAuth.openAuthModal === 'function') {
      RadarAuth.openAuthModal('Đăng nhập để lưu watchlist săn deal.');
    }
    return;
  }
  if (!window.RadarAuth || typeof RadarAuth.openWatchlistModal !== 'function') return;
  RadarAuth.openWatchlistModal();
  setTimeout(() => {
    const wards = Array.isArray(filt.ward) ? filt.ward : (filt.ward ? [filt.ward] : []);
    const firstWard = wards[0];
    const city = firstWard ? assistantFindCityForWard(firstWard) : '';
    if (city && typeof RadarAuth.selectWatchlistCity === 'function') RadarAuth.selectWatchlistCity(city);
    if (wards.length) {
      const selected = new Set(wards.map(String));
      document.querySelectorAll('#watchlistWardBox input[name="watchWard"]').forEach((el) => {
        el.checked = selected.has(String(el.value));
      });
      if (typeof RadarAuth.updateWatchlistWardCount === 'function') RadarAuth.updateWatchlistWardCount();
    }
    const name = document.getElementById('watchlistName');
    if (name) name.value = assistantWatchlistName(filt);
    assistantSetWatchValue('watchMosMin', filt.mos_min || 15);
    assistantSetWatchValue('watchPriceMin', filt.price_min);
    assistantSetWatchValue('watchPriceMax', filt.price_max);
    assistantSetWatchValue('watchAreaMin', filt.area_min);
    assistantSetWatchValue('watchAreaMax', filt.area_max);
    assistantSetCheckboxes('input[name="watchProp"]', Array.isArray(filt.property_type) ? filt.property_type : []);
  }, 120);
}

function assistantSetWatchValue(id, value) {
  const el = document.getElementById(id);
  if (el && value !== undefined && value !== null && value !== '') el.value = String(value);
}

function assistantWatchlistName(filter) {
  const parts = [];
  const wards = Array.isArray(filter.ward) ? filter.ward : [];
  if (wards.length) parts.push(wards.slice(0, 2).join(', '));
  if (filter.price_max) parts.push(`dưới ${filter.price_max} tỷ`);
  if (filter.mos_min) parts.push(`MOS ${filter.mos_min}%`);
  if (filter.only_drops) parts.push('có giảm giá');
  return parts.join(' · ') || 'Watchlist từ Radar Assistant';
}

function openAssistantLeadFlow() {
  if (typeof openGuestLeadForm === 'function') {
    openGuestLeadForm(null, 'assistant', '');
  } else if (typeof captureLeadAndOpen === 'function') {
    captureLeadAndOpen(null, '', 'assistant', 'standard');
  }
}

function openAssistantListingMemo(listingId) {
  const id = Number(listingId || 0);
  if (!id) return;
  const card = document.querySelector(`[data-id="${id}"]`);
  if (card && typeof openSignal === 'function') {
    openSignal(card);
    setTimeout(() => {
      if (typeof switchSignalPanel === 'function') switchSignalPanel('memo');
    }, 350);
    return;
  }
  if (typeof switchTab === 'function') switchTab('signals', document.querySelector('[data-tab-target="signals"]'));
  if (typeof applyFilters === 'function') applyFilters();
  appendMessage('bot', `Mình đã chuyển bạn về Săn deal. Nếu tin #${id} không nằm trên màn hình hiện tại, hãy tìm mã tin rồi mở tab Cố vấn trong modal.`);
}

function handleAssistantAction(action) {
  if (!action || !action.type) return;
  if (action.type === 'apply_filter') {
    applyAssistantFilter(action.filter || {});
  } else if (action.type === 'open_watchlist') {
    prefillAssistantWatchlist(action.filter || {});
  } else if (action.type === 'open_lead') {
    openAssistantLeadFlow();
  } else if (action.type === 'open_listing_memo') {
    openAssistantListingMemo(action.listing_id);
  } else if (action.type === 'auth_required') {
    if (window.RadarAuth && typeof RadarAuth.openAuthModal === 'function') {
      RadarAuth.openAuthModal('Đăng nhập miễn phí để dùng tính năng này.');
    }
  }
}

/* ───────────────────────────────────────────────────────────────
   Conversion tracker — fire-and-forget POST /api/track
   ─────────────────────────────────────────────────────────────── */
window.track = function (action, opts) {
  opts = opts || {};
  try {
    fetch('/api/track', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        action: action,
        listing_id: opts.listing_id || null,
        context: opts.context || {},
      }),
      keepalive: true,
    }).catch(() => { });
  } catch (e) { /* silent */ }
};

// Track + nudge wrappers for locked UI elements
function onLockedTabClick(tab, reason) {
  window.track('locked_tab_click', {
    context: { tab: tab || 'unknown', reason: reason || 'tier_required' },
  });
  if (window.RadarAuth && typeof RadarAuth.nudgeVipUpgrade === 'function') {
    RadarAuth.nudgeVipUpgrade(reason || 'Mở khoá Phân Tích Chuyên Sâu');
  }
}

/* ───────────────────────────────────────────────────────────────
   Tier-aware CTA dispatcher + Guest Lead modal
   ─────────────────────────────────────────────────────────────── */
function tierCTA(listingId, url, ctx) {
  const t = window.USER_TIER || 'guest';
  if (t === 'guest') {
    window.track('vip_cta_click', { listing_id: listingId, context: { tier: 'guest', ctx: ctx } });
  } else if (t === 'free') {
    window.track('cta_vip', { listing_id: listingId, context: { tier: 'free', ctx: ctx } });
  } else if (t === 'vip' || t === 'admin') {
    window.track('lead_vip_click', { listing_id: listingId, context: { tier: t, ctx: ctx } });
  }
  openGuestLeadForm(listingId, ctx, url);
}

let _guestLeadListingId = null;
let _guestLeadCtx = null;
let _guestLeadListingUrl = '';

function _currentUserPhone() {
  return ((window.CURRENT_USER && window.CURRENT_USER.phone) || '').trim();
}

function _guestLeadDefaultNote(tier, listingId) {
  const lotRef = listingId ? `#${listingId}` : 'này';
  let note = `Tôi quan tâm lô ${lotRef}, hãy gửi thêm thông tin.`;
  if (tier === 'vip' || tier === 'admin') {
    note += ' Tôi muốn được tư vấn và phân tích 1-1 với chuyên gia.';
  }
  return note;
}

function openGuestLeadForm(listingId, ctx, listingUrl = '') {
  _guestLeadListingId = listingId;
  _guestLeadCtx = ctx || 'card_signal';
  _guestLeadListingUrl = listingUrl || '';
  const tier = window.USER_TIER || 'guest';
  const m = document.getElementById('guestLeadModal');
  if (!m) return;
  const err = document.getElementById('guestLeadError');
  const title = document.getElementById('guestLeadTitle');
  const sub = document.getElementById('guestLeadSub');
  const vipNote = document.getElementById('guestLeadVipNote');
  const contactEl = document.getElementById('guestLeadContact');
  const noteEl = document.getElementById('guestLeadNote');

  if (err) { err.textContent = ''; err.classList.remove('show'); }
  if (title) title.textContent = tier === 'guest' ? 'Yêu cầu RadarBDS ráp mối' : 'Gửi yêu cầu tư vấn';
  if (sub) {
    sub.textContent = tier === 'guest'
      ? 'Chỉ cần để lại SĐT/Zalo, admin sẽ gửi thêm thông tin lô này.'
      : 'RadarBDS đã điền sẵn SĐT từ tài khoản của bạn. Bạn có thể gửi yêu cầu hoặc chat Zalo trực tiếp.';
  }
  if (vipNote) {
    if (tier === 'vip' || tier === 'admin') {
      vipNote.textContent = 'Đặc quyền VIP: yêu cầu này sẽ được ưu tiên và có tư vấn, phân tích 1-1 với chuyên gia.';
      vipNote.style.display = 'flex';
    } else {
      vipNote.textContent = '';
      vipNote.style.display = 'none';
    }
  }
  if (contactEl) contactEl.value = tier === 'guest' ? '' : _currentUserPhone();
  if (noteEl) noteEl.value = _guestLeadDefaultNote(tier, listingId);
  m.classList.add('show');
  setTimeout(() => {
    const contact = document.getElementById('guestLeadContact');
    const submitBtn = document.getElementById('guestLeadSubmitBtn');
    if (contact && !contact.value) contact.focus();
    else if (submitBtn) submitBtn.focus();
  }, 80);
}
function closeGuestLeadModal() {
  const m = document.getElementById('guestLeadModal');
  if (m) m.classList.remove('show');
}
function guestLeadChatZalo() {
  closeGuestLeadModal();
  _openZaloDirect();
}
async function submitGuestLead() {
  const contactEl = document.getElementById('guestLeadContact');
  const noteEl = document.getElementById('guestLeadNote');
  const err = document.getElementById('guestLeadError');
  const btn = document.getElementById('guestLeadSubmitBtn');
  const contact = (contactEl && contactEl.value || '').trim();
  const note = (noteEl && noteEl.value || '').trim();
  if (!contact) {
    if (err) { err.textContent = 'Vui lòng nhập số điện thoại/Zalo.'; err.classList.add('show'); }
    return;
  }
  if (!_isLikelyPhone(contact)) {
    if (err) { err.textContent = 'Số điện thoại chưa hợp lệ, vui lòng kiểm tra lại.'; err.classList.add('show'); }
    return;
  }
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('/api/lead-capture-guest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        listing_id: _guestLeadListingId,
        listing_url: _guestLeadListingUrl,
        contact,
        note,
        context: _guestLeadCtx,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      if (err) { err.textContent = data.error || 'Không gửi được, thử lại sau.'; err.classList.add('show'); }
      return;
    }
    closeGuestLeadModal();
    alert('Đã gửi yêu cầu. RadarBDS sẽ liên hệ và gửi thêm thông tin cho bạn.');
  } catch (e) {
    if (err) { err.textContent = 'Mất kết nối, thử lại sau.'; err.classList.add('show'); }
  } finally {
    if (btn) btn.disabled = false;
  }
}

Object.assign(window, {
  captureLeadAndOpen,
  closeLeadCaptureModal,
  submitLeadAndOpenZalo,
  skipLeadAndOpenZalo,
  toggleChat,
  sendMessage,
  sendAssistantPrompt,
  onLockedTabClick,
  tierCTA,
  closeGuestLeadModal,
  guestLeadChatZalo,
  submitGuestLead,
});
window.__radarEngagementLoaded = true;

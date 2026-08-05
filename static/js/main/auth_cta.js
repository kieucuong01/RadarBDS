// Lead capture, Radar Ask entry points, analytics tracking, and tier CTA flows.
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
  window.open(zaloHref, '_blank', 'noopener,noreferrer');
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

async function openRadarAsk(options = {}) {
  if (!window.CURRENT_USER) {
    if (window.RadarAuth && typeof window.RadarAuth.openAuthModal === 'function') {
      window.RadarAuth.openAuthModal('Đăng nhập để hỏi dữ liệu bất động sản có dẫn nguồn.');
    }
    return false;
  }

  if (!window.RadarAsk || typeof window.RadarAsk.open !== 'function') {
    try {
      if (typeof ensureDashboardScript === 'function') await ensureDashboardScript('radarAsk');
    } catch (error) {
      console.error('Không thể tải Hỏi Radar BĐS:', error);
      return false;
    }
  }
  if (!window.RadarAsk || typeof window.RadarAsk.open !== 'function') return false;

  return window.RadarAsk.open({
    listing_id: options.listing_id,
    ward: options.ward,
    road: options.road,
    question: options.question,
  });
}

function openRadarAskForListing(trigger) {
  const root = trigger && typeof trigger.closest === 'function'
    ? trigger.closest('[data-listing-actions]')
    : null;
  const listingId = Number(root?.dataset.listingId || trigger?.dataset.listingId || 0);
  return openRadarAsk({
    listing_id: Number.isInteger(listingId) && listingId > 0 ? listingId : undefined,
    ward: root?.dataset.ward || '',
    road: root?.dataset.road || '',
    question: 'Vì sao lô đất này được định giá như hiện tại?',
  });
}

/* ───────────────────────────────────────────────────────────────
   Conversion tracker — fire-and-forget POST /api/track
   ─────────────────────────────────────────────────────────────── */
window.track = function (action, opts) {
  opts = opts || {};
  const context = opts.context || {};
  try {
    fetch('/api/track', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        action: action,
        listing_id: opts.listing_id || null,
        context: context,
      }),
      keepalive: true,
    }).catch(() => { });
  } catch (e) { /* silent */ }
  try {
    if (typeof window.gtag === 'function') {
      window.gtag('event', action, {
        ...context,
        listing_id: opts.listing_id || undefined,
      });
    }
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
  openRadarAsk,
  openRadarAskForListing,
  onLockedTabClick,
  tierCTA,
  closeGuestLeadModal,
  guestLeadChatZalo,
  submitGuestLead,
});
window.__radarEngagementLoaded = true;

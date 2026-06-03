/* RBAC auth flow — unified check → register/login, user menu, tier nudges.
   Depends on globals injected by index.html: window.USER_TIER, window.CURRENT_USER. */

(function () {
  'use strict';

  const TIER_LABEL = { guest: 'Khách', free: 'Gói Free', vip: 'VIP', admin: 'Admin' };
  let authMode = null; // 'login' | 'register' | null (= identifier step)
  let authIdentType = null; // 'phone' | 'email'
  let watchlists = [];
  let watchlistCity = null;

  // ── Modal open/close ─────────────────────────────────────────────
  function openAuthModal(reason) {
    const m = document.getElementById('authModal');
    if (!m) return;
    resetAuthModal();
    if (reason) {
      const banner = document.getElementById('authReasonBanner');
      if (banner) {
        banner.textContent = reason;
        banner.style.display = 'block';
      }
    }
    m.classList.add('show');
    setTimeout(() => {
      const i = document.getElementById('authIdentifier');
      if (i) i.focus();
    }, 80);
  }
  function closeAuthModal() {
    const m = document.getElementById('authModal');
    if (m) m.classList.remove('show');
  }
  function resetAuthModal() {
    authMode = null;
    authIdentType = null;
    const id = document.getElementById('authIdentifier');
    const pw = document.getElementById('authPassword');
    const err = document.getElementById('authError');
    const pwField = document.getElementById('authPasswordField');
    const submitBtn = document.getElementById('authSubmitBtn');
    const title = document.getElementById('authTitle');
    const sub = document.getElementById('authSub');
    const trial = document.getElementById('authTrialBanner');
    const banner = document.getElementById('authReasonBanner');
    if (id) { id.value = ''; id.disabled = false; }
    if (pw) pw.value = '';
    if (err) { err.textContent = ''; err.classList.remove('show'); }
    if (pwField) pwField.style.display = 'none';
    if (submitBtn) submitBtn.textContent = 'Tiếp tục';
    if (title) title.textContent = 'Đăng nhập / Đăng ký';
    if (sub) sub.textContent = 'Nhập số điện thoại để tiếp tục.';
    if (trial) trial.style.display = 'none';
    if (banner) { banner.textContent = ''; banner.style.display = 'none'; }
  }

  function showAuthError(msg) {
    const err = document.getElementById('authError');
    if (!err) return;
    err.textContent = msg;
    err.classList.add('show');
  }
  function clearAuthError() {
    const err = document.getElementById('authError');
    if (err) err.classList.remove('show');
  }

  // ── Submit step 1: identifier check ──────────────────────────────
  async function submitAuth() {
    clearAuthError();
    const idEl = document.getElementById('authIdentifier');
    const pwEl = document.getElementById('authPassword');
    const submitBtn = document.getElementById('authSubmitBtn');
    if (!idEl) return;

    if (authMode === null) {
      const raw = (idEl.value || '').trim();
      if (!raw) { showAuthError('Vui lòng nhập số điện thoại.'); return; }
      submitBtn.disabled = true;
      try {
        const res = await fetch('/api/auth/check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ identifier: raw }),
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          const errMap = {
            invalid_identifier: 'Số điện thoại chưa đúng định dạng. SĐT bắt đầu bằng 0 và có 10 chữ số.',
            phone_only: 'Hiện tại chỉ hỗ trợ đăng ký bằng số điện thoại.',
          };
          showAuthError(errMap[data.error] || 'Có lỗi xảy ra, thử lại nhé.');
          return;
        }
        authIdentType = data.type;
        authMode = data.exists ? 'login' : 'register';
        idEl.disabled = true;
        document.getElementById('authPasswordField').style.display = 'block';
        const title = document.getElementById('authTitle');
        const sub = document.getElementById('authSub');
        if (authMode === 'login') {
          title.textContent = 'Đăng nhập';
          sub.textContent = 'Tài khoản đã tồn tại. Nhập mật khẩu để vào.';
          submitBtn.textContent = 'Đăng nhập';
        } else {
          title.textContent = 'Đăng ký nhanh';
          sub.textContent = authIdentType === 'phone'
            ? 'Tài khoản mới. Đặt mật khẩu để tạo tài khoản.'
            : 'Tài khoản mới. Đặt mật khẩu để tạo tài khoản.';
          submitBtn.textContent = 'Tạo tài khoản';
          if (authIdentType === 'phone') {
            const trial = document.getElementById('authTrialBanner');
            if (trial) {
              trial.innerHTML = '🎁 <span>Đăng ký bằng SĐT — tặng 24h dùng thử VIP miễn phí.</span>';
              trial.style.display = 'flex';
            }
          }
        }
        setTimeout(() => pwEl && pwEl.focus(), 60);
      } catch (e) {
        showAuthError('Mất kết nối, thử lại sau.');
      } finally {
        submitBtn.disabled = false;
      }
      return;
    }

    // Step 2: actual login or register
    const pw = (pwEl.value || '');
    if (pw.length < 6) { showAuthError('Mật khẩu cần ít nhất 6 ký tự.'); return; }
    submitBtn.disabled = true;
    const endpoint = authMode === 'login' ? '/api/auth/login' : '/api/auth/register';
    const body = { identifier: idEl.value.trim(), password: pw };
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        const codeMap = {
          invalid_credentials: 'Sai mật khẩu hoặc tài khoản không tồn tại.',
          identifier_taken: 'Tài khoản đã tồn tại, hãy đăng nhập thay vì đăng ký.',
          weak_password: 'Mật khẩu cần ít nhất 6 ký tự.',
          banned: 'Tài khoản đang bị khoá. Liên hệ admin để được hỗ trợ.',
        };
        showAuthError(codeMap[data.error] || 'Không thể tiếp tục, thử lại sau.');
        return;
      }
      // Success → reload to pick up new session cookie + tier-aware data
      window.location.reload();
    } catch (e) {
      showAuthError('Mất kết nối, thử lại sau.');
    } finally {
      submitBtn.disabled = false;
    }
  }

  function authBack() {
    // Lets user edit identifier again
    const idEl = document.getElementById('authIdentifier');
    if (idEl) idEl.disabled = false;
    document.getElementById('authPasswordField').style.display = 'none';
    document.getElementById('authSubmitBtn').textContent = 'Tiếp tục';
    document.getElementById('authTitle').textContent = 'Đăng nhập / Đăng ký';
    document.getElementById('authSub').textContent = 'Nhập số điện thoại hoặc email để tiếp tục.';
    const trial = document.getElementById('authTrialBanner');
    if (trial) trial.style.display = 'none';
    authMode = null;
    authIdentType = null;
    clearAuthError();
    if (idEl) idEl.focus();
  }

  // ── Logout ──────────────────────────────────────────────────────
  async function logout() {
    try { await fetch('/api/auth/logout', { method: 'POST' }); }
    catch (e) { /* ignore */ }
    window.location.reload();
  }

  // ── User menu toggle ────────────────────────────────────────────
  function toggleUserMenu(e) {
    if (e) e.stopPropagation();
    const dd = document.getElementById('userMenuDropdown');
    if (dd) dd.classList.toggle('open');
  }
  function closeUserMenuOnOutside(e) {
    const menu = document.getElementById('userMenu');
    if (!menu) return;
    if (!menu.contains(e.target)) {
      const dd = document.getElementById('userMenuDropdown');
      if (dd) dd.classList.remove('open');
    }
  }

  // ── Tier nudges (called from card CTAs) ─────────────────────────
  function nudgeVipUpgrade(reason) {
    const tier = window.USER_TIER || 'guest';
    if (tier === 'guest') {
      openAuthModal('🔒 ' + (reason || 'Đăng ký để mở khoá tin VIP và phân tích chuyên sâu.'));
      return;
    }
    // Free/already-logged-in → simple alert pointing to Zalo for now
    alert('💎 Nâng cấp VIP\n\nLiên hệ admin qua Zalo để được nâng cấp VIP (1.000.000đ/tháng).\nĐặc quyền:\n• Xem tin mới ngay khi crawl (sớm 24h)\n• Push Telegram + email tin khớp watchlist\n• Phân tích chuyên sâu (Cắt máu, Bất thường nguồn cung)');
  }

  function escHtml(v) {
    return String(v ?? '').replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
  }

  function closeUserMenu() {
    const dd = document.getElementById('userMenuDropdown');
    if (dd) dd.classList.remove('open');
  }

  function openWatchlistModal() {
    if (!window.CURRENT_USER) {
      openAuthModal('Đăng nhập để lưu khu vực quan tâm và nhận thông báo.');
      return;
    }
    const m = document.getElementById('watchlistModal');
    if (!m) return;
    closeUserMenu();
    initWatchlistWardPicker();
    resetWatchlistForm();
    renderTelegramState();
    renderWatchlistStatus();
    m.classList.add('show');
    loadWatchlists();
  }

  function closeWatchlistModal() {
    const m = document.getElementById('watchlistModal');
    if (m) m.classList.remove('show');
  }

  function showWatchlistError(msg) {
    const el = document.getElementById('watchlistError');
    if (!el) return;
    el.textContent = msg || '';
    el.classList.toggle('show', !!msg);
  }

  function renderWatchlistStatus() {
    const el = document.getElementById('watchlistStatus');
    if (!el) return;
    const tier = window.USER_TIER || 'guest';
    if (tier === 'vip' || tier === 'admin') {
      el.className = 'watchlist-status is-vip';
      el.textContent = 'VIP đang bật: tin mới khớp bộ lọc sẽ được gửi sau mỗi lần crawl.';
    } else {
      el.className = 'watchlist-status is-free';
      el.textContent = 'Free có thể lưu bộ lọc trước. Telegram realtime chỉ gửi khi tài khoản được nâng VIP.';
    }
  }

  function renderTelegramState() {
    const linked = !!(window.CURRENT_USER && window.CURRENT_USER.telegram_linked);
    const text = document.getElementById('watchlistTelegramText');
    const connect = document.getElementById('watchlistConnectTelegramBtn');
    const unbind = document.getElementById('watchlistUnbindTelegramBtn');
    if (text) text.textContent = linked ? 'Đã kết nối Telegram.' : 'Chưa kết nối Telegram.';
    if (connect) connect.style.display = linked ? 'none' : 'inline-flex';
    if (unbind) unbind.style.display = linked ? 'inline-flex' : 'none';
  }

  function initWatchlistWardPicker() {
    const data = window.INITIAL_WARDS_BY_CITY || {};
    const cities = Object.keys(data);
    if (!watchlistCity || !data[watchlistCity]) watchlistCity = cities[0] || '';
    const tabs = document.getElementById('watchlistCityTabs');
    if (tabs) {
      tabs.innerHTML = cities.map((city) => (
        `<button type="button" class="${city === watchlistCity ? 'active' : ''}" onclick="RadarAuth.selectWatchlistCity('${escHtml(city)}')">${escHtml(city)}</button>`
      )).join('');
    }
    renderWatchlistWards();
  }

  function selectWatchlistCity(city) {
    watchlistCity = city;
    initWatchlistWardPicker();
  }

  function getSelectedWatchlistWards() {
    return Array.from(document.querySelectorAll('#watchlistWardBox input[name="watchWard"]:checked')).map((x) => x.value);
  }

  function updateWatchlistWardCount() {
    const el = document.getElementById('watchlistWardCount');
    if (!el) return;
    const total = document.querySelectorAll('#watchlistWardBox input[name="watchWard"]').length;
    const selected = getSelectedWatchlistWards().length;
    el.textContent = `${selected}/${total} phường`;
  }

  function renderWatchlistWards(selected = null) {
    const box = document.getElementById('watchlistWardBox');
    if (!box) return;
    const data = window.INITIAL_WARDS_BY_CITY || {};
    const wards = data[watchlistCity] || [];
    const selectedSet = new Set(selected || getSelectedWatchlistWards());
    box.innerHTML = wards.map((ward) => {
      const checked = selectedSet.has(ward) ? 'checked' : '';
      return `<label><input type="checkbox" name="watchWard" value="${escHtml(ward)}" ${checked} onchange="RadarAuth.updateWatchlistWardCount()"> ${escHtml(ward)}</label>`;
    }).join('');
    updateWatchlistWardCount();
  }

  function setWatchlistCityWards(checked) {
    document.querySelectorAll('#watchlistWardBox input[name="watchWard"]').forEach((el) => { el.checked = !!checked; });
    updateWatchlistWardCount();
  }

  function watchlistNum(id) {
    const raw = (document.getElementById(id)?.value || '').trim();
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function resetWatchlistForm() {
    showWatchlistError('');
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ''; };
    set('watchlistId', '');
    set('watchlistName', '');
    set('watchMosMin', '15');
    set('watchPriceMin', '');
    set('watchPriceMax', '');
    set('watchAreaMin', '');
    set('watchAreaMax', '');
    document.querySelectorAll('input[name="watchProp"]').forEach((el) => {
      el.checked = ['dat_nen', 'nha_dat', 'dat_vuon'].includes(el.value);
    });
    const tg = document.getElementById('watchNotifyTelegram');
    if (tg) tg.checked = true;
    const active = document.getElementById('watchActive');
    if (active) active.checked = true;
    setWatchlistCityWards(false);
    const btn = document.getElementById('watchlistSaveBtn');
    if (btn) btn.textContent = 'Lưu bộ lọc';
  }

  async function loadWatchlists() {
    const items = document.getElementById('watchlistItems');
    if (items) items.innerHTML = '<div class="watchlist-empty">Đang tải...</div>';
    try {
      const res = await fetch('/api/watchlists');
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'load_failed');
      watchlists = data.items || [];
      renderWatchlists();
    } catch (e) {
      if (items) items.innerHTML = '<div class="watchlist-empty">Không tải được watchlist.</div>';
    }
  }

  function renderWatchlists() {
    const box = document.getElementById('watchlistItems');
    if (!box) return;
    if (!watchlists.length) {
      box.innerHTML = '<div class="watchlist-empty">Chưa có bộ lọc nào.</div>';
      return;
    }
    box.innerHTML = watchlists.map((w) => {
      const wards = (w.wards || []).slice(0, 3).join(', ') || 'Tất cả phường';
      const more = (w.wards || []).length > 3 ? ` +${(w.wards || []).length - 3}` : '';
      const props = (w.prop_types || []).length ? (w.prop_types || []).join(', ') : 'Tất cả loại hình';
      const active = w.active ? 'Đang bật' : 'Tạm tắt';
      const tg = w.notify_telegram ? 'Telegram' : 'Không TG';
      return `<article class="watchlist-item">
        <div>
          <strong>${escHtml(w.name)}</strong>
          <p>${escHtml(wards)}${escHtml(more)} · MOS ≥ ${escHtml(w.mos_min || 0)}% · ${escHtml(props)}</p>
          <span>${escHtml(active)} · ${escHtml(tg)}</span>
        </div>
        <div class="watchlist-item-actions">
          <button type="button" onclick="RadarAuth.editWatchlist(${Number(w.id)})">Sửa</button>
          <button type="button" class="danger" onclick="RadarAuth.deleteWatchlist(${Number(w.id)})">Xóa</button>
        </div>
      </article>`;
    }).join('');
  }

  function editWatchlist(id) {
    const w = watchlists.find((x) => Number(x.id) === Number(id));
    if (!w) return;
    const set = (elId, val) => { const el = document.getElementById(elId); if (el) el.value = val ?? ''; };
    set('watchlistId', w.id);
    set('watchlistName', w.name || '');
    set('watchMosMin', w.mos_min ?? 0);
    set('watchPriceMin', w.price_min_ty ?? '');
    set('watchPriceMax', w.price_max_ty ?? '');
    set('watchAreaMin', w.area_min ?? '');
    set('watchAreaMax', w.area_max ?? '');
    document.querySelectorAll('input[name="watchProp"]').forEach((el) => {
      el.checked = (w.prop_types || []).includes(el.value);
    });
    const tg = document.getElementById('watchNotifyTelegram');
    if (tg) tg.checked = !!w.notify_telegram;
    const active = document.getElementById('watchActive');
    if (active) active.checked = !!w.active;
    const firstWard = (w.wards || [])[0];
    if (firstWard) {
      const data = window.INITIAL_WARDS_BY_CITY || {};
      const city = Object.keys(data).find((c) => (data[c] || []).includes(firstWard));
      if (city) watchlistCity = city;
    }
    initWatchlistWardPicker();
    renderWatchlistWards(w.wards || []);
    const btn = document.getElementById('watchlistSaveBtn');
    if (btn) btn.textContent = 'Cập nhật bộ lọc';
  }

  async function saveWatchlist() {
    showWatchlistError('');
    const id = (document.getElementById('watchlistId')?.value || '').trim();
    const name = (document.getElementById('watchlistName')?.value || '').trim();
    if (!name) { showWatchlistError('Đặt tên bộ lọc để dễ nhận diện.'); return; }
    const payload = {
      name,
      wards: getSelectedWatchlistWards(),
      prop_types: Array.from(document.querySelectorAll('input[name="watchProp"]:checked')).map((x) => x.value),
      mos_min: watchlistNum('watchMosMin') || 0,
      price_min_ty: watchlistNum('watchPriceMin'),
      price_max_ty: watchlistNum('watchPriceMax'),
      area_min: watchlistNum('watchAreaMin'),
      area_max: watchlistNum('watchAreaMax'),
      notify_telegram: !!document.getElementById('watchNotifyTelegram')?.checked,
      notify_email: false,
      active: !!document.getElementById('watchActive')?.checked,
    };
    const btn = document.getElementById('watchlistSaveBtn');
    if (btn) btn.disabled = true;
    try {
      const res = await fetch(id ? `/api/watchlists/${encodeURIComponent(id)}` : '/api/watchlists', {
        method: id ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'save_failed');
      resetWatchlistForm();
      await loadWatchlists();
    } catch (e) {
      showWatchlistError('Không lưu được bộ lọc, thử lại sau.');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function deleteWatchlist(id) {
    if (!confirm('Xóa bộ lọc này?')) return;
    try {
      const res = await fetch(`/api/watchlists/${encodeURIComponent(id)}`, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'delete_failed');
      if ((document.getElementById('watchlistId')?.value || '') === String(id)) resetWatchlistForm();
      await loadWatchlists();
    } catch (e) {
      showWatchlistError('Không xóa được bộ lọc, thử lại sau.');
    }
  }

  async function connectTelegram() {
    showWatchlistError('');
    try {
      const res = await fetch('/api/auth/telegram/start', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        showWatchlistError(data.error === 'bot_not_configured'
          ? 'Chưa cấu hình TELEGRAM_BOT_USERNAME/TELEGRAM_BOT_TOKEN.'
          : 'Không tạo được link Telegram.');
        return;
      }
      window.open(data.url, '_blank', 'noopener,noreferrer');
      const text = document.getElementById('watchlistTelegramText');
      if (text) text.textContent = 'Đã mở Telegram. Sau khi bấm Start, tải lại trang để cập nhật trạng thái.';
    } catch (e) {
      showWatchlistError('Không kết nối được Telegram, thử lại sau.');
    }
  }

  async function connectTelegramFixed() {
    showWatchlistError('');
    const btn = document.getElementById('watchlistConnectTelegramBtn');
    const text = document.getElementById('watchlistTelegramText');
    const popup = window.open('', '_blank');
    if (popup) popup.document.write('<p style="font-family:system-ui;padding:20px">Dang tao link Telegram...</p>');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Dang ket noi...';
    }
    if (text) text.textContent = 'Dang tao link Telegram...';
    try {
      const res = await fetch('/api/auth/telegram/start', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        const msg = data.error === 'bot_not_configured'
          ? 'Chua cau hinh TELEGRAM_BOT_USERNAME/TELEGRAM_BOT_TOKEN.'
          : data.error === 'tier_required'
            ? 'Phien dang nhap chua hop le. Hay dang nhap lai roi ket noi Telegram.'
            : 'Khong tao duoc link Telegram.';
        if (popup) {
          popup.document.body.innerHTML = `<div style="font-family:system-ui;padding:24px;line-height:1.5">
            <h2 style="margin:0 0 10px;color:#b91c1c">Khong mo duoc Telegram</h2>
            <p>${escHtml(msg)}</p>
            <p style="color:#64748b">Quay lai RadarBDS de kiem tra cau hinh bot.</p>
          </div>`;
        }
        showWatchlistError(msg);
        if (text) text.textContent = 'Chua ket noi Telegram.';
        return;
      }
      if (popup) {
        popup.location.href = data.url;
        if (text) text.textContent = 'Da mo Telegram. Bam Start trong Telegram, sau do tai lai trang.';
      } else if (text) {
        text.innerHTML = `Trinh duyet da chan popup. <a href="${escHtml(data.url)}" target="_blank" rel="noopener noreferrer">Bam vao day mo Telegram</a>.`;
      }
      pollTelegramSync();
    } catch (e) {
      if (popup) {
        popup.document.body.innerHTML = `<div style="font-family:system-ui;padding:24px;line-height:1.5">
          <h2 style="margin:0 0 10px;color:#b91c1c">Khong ket noi duoc Telegram</h2>
          <p>Server hoac mang dang loi. Hay thu lai sau.</p>
        </div>`;
      }
      showWatchlistError('Khong ket noi duoc Telegram, thu lai sau.');
      if (text) text.textContent = 'Chua ket noi Telegram.';
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Ket noi Telegram';
      }
    }
  }

  function pollTelegramSync() {
    let tries = 0;
    const text = document.getElementById('watchlistTelegramText');
    const timer = setInterval(async () => {
      tries += 1;
      try {
        const res = await fetch('/api/auth/telegram/sync', { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.ok && data.linked) {
          clearInterval(timer);
          if (window.CURRENT_USER) window.CURRENT_USER.telegram_linked = true;
          renderTelegramState();
          if (text) text.textContent = 'Da ket noi Telegram.';
          return;
        }
        if (!res.ok && data.error && text) {
          text.textContent = 'Chua xac nhan duoc Telegram. Neu dang dung webhook public, hay tai lai trang sau khi bam Start.';
        }
      } catch (e) {
        // Keep polling briefly; local tunnel/network can lag.
      }
      if (tries >= 20) {
        clearInterval(timer);
        if (text && !(window.CURRENT_USER && window.CURRENT_USER.telegram_linked)) {
          text.textContent = 'Chua thay tin /start. Hay bam Start trong Telegram roi thu lai.';
        }
      }
    }, 3000);
  }

  async function unbindTelegram() {
    try {
      const res = await fetch('/api/auth/telegram/unbind', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || 'unbind_failed');
      if (window.CURRENT_USER) window.CURRENT_USER.telegram_linked = false;
      renderTelegramState();
    } catch (e) {
      showWatchlistError('Không ngắt được Telegram, thử lại sau.');
    }
  }

  // Expose API
  window.RadarAuth = {
    openAuthModal,
    closeAuthModal,
    submitAuth,
    authBack,
    logout,
    toggleUserMenu,
    nudgeVipUpgrade,
    openWatchlistModal,
    closeWatchlistModal,
    selectWatchlistCity,
    setWatchlistCityWards,
    updateWatchlistWardCount,
    resetWatchlistForm,
    saveWatchlist,
    editWatchlist,
    deleteWatchlist,
    connectTelegram: connectTelegramFixed,
    unbindTelegram,
  };

  document.addEventListener('DOMContentLoaded', () => {
    document.addEventListener('click', closeUserMenuOnOutside);
    // Submit-on-Enter inside auth modal
    const idEl = document.getElementById('authIdentifier');
    const pwEl = document.getElementById('authPassword');
    [idEl, pwEl].forEach((el) => {
      if (el) el.addEventListener('keypress', (ev) => {
        if (ev.key === 'Enter') { ev.preventDefault(); submitAuth(); }
      });
    });
  });
})();

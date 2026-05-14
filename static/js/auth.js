/* RBAC auth flow — unified check → register/login, user menu, tier nudges.
   Depends on globals injected by index.html: window.USER_TIER, window.CURRENT_USER. */

(function () {
  'use strict';

  const TIER_LABEL = { guest: 'Khách', free: 'Free', vip: 'VIP', admin: 'Admin' };
  let authMode = null; // 'login' | 'register' | null (= identifier step)
  let authIdentType = null; // 'phone' | 'email'

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
    if (sub) sub.textContent = 'Nhập số điện thoại hoặc email để tiếp tục.';
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
      if (!raw) { showAuthError('Vui lòng nhập số điện thoại hoặc email.'); return; }
      submitBtn.disabled = true;
      try {
        const res = await fetch('/api/auth/check', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ identifier: raw }),
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          showAuthError(data.error === 'invalid_identifier'
            ? 'Định dạng SĐT/email chưa đúng. SĐT bắt đầu bằng 0, email phải có @.'
            : 'Có lỗi xảy ra, thử lại nhé.');
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

  // Expose API
  window.RadarAuth = {
    openAuthModal,
    closeAuthModal,
    submitAuth,
    authBack,
    logout,
    toggleUserMenu,
    nudgeVipUpgrade,
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

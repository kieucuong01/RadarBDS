(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarListingDetailActions = api;
}(typeof window !== 'undefined' ? window : globalThis, function () {
  const REPORT_REASONS = new Set([
    'sold_or_unavailable',
    'wrong_price_or_area',
    'duplicate',
    'wrong_location',
    'spam_or_scam',
    'other',
  ]);

  function positiveInteger(value) {
    if (typeof value === 'string' && !/^[1-9]\d*$/.test(value)) return null;
    const number = Number(value);
    return Number.isSafeInteger(number) && number > 0 ? number : null;
  }

  function canonicalListingUrl(origin, listingId) {
    const id = positiveInteger(listingId);
    if (!id) return null;
    try {
      const parsed = new URL(origin);
      if (!['http:', 'https:'].includes(parsed.protocol)) return null;
      return `${parsed.origin}/listing/${id}`;
    } catch (_error) {
      return null;
    }
  }

  function facebookShareUrl(canonicalUrl) {
    if (!canonicalUrl) return null;
    return `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(canonicalUrl)}`;
  }

  function normalizeReportPayload(reason, note) {
    const normalizedReason = typeof reason === 'string' ? reason.trim() : '';
    const normalizedNote = typeof note === 'string' ? note.trim() : '';
    if (!REPORT_REASONS.has(normalizedReason) || normalizedNote.length > 500) return null;
    return { reason: normalizedReason, note: normalizedNote };
  }

  async function submitReport(fetchFn, listingId, reason, note) {
    const id = positiveInteger(listingId);
    const payload = normalizeReportPayload(reason, note);
    if (!id || !payload || typeof fetchFn !== 'function') return null;
    try {
      const response = await fetchFn(`/api/listings/${id}/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      let data = {};
      try {
        data = await response.json();
      } catch (_error) {
        data = {};
      }
      return {
        ok: Boolean(response.ok && data.ok),
        status: response.status,
        duplicate: Boolean(data.duplicate),
        error: typeof data.error === 'string' ? data.error : '',
      };
    } catch (_error) {
      return { ok: false, status: 0, duplicate: false, error: 'network_error' };
    }
  }

  async function copyText(value, view) {
    const currentView = view || (typeof window !== 'undefined' ? window : null);
    if (!currentView || !value) return false;
    try {
      if (currentView.navigator.clipboard && currentView.isSecureContext) {
        await currentView.navigator.clipboard.writeText(value);
        return true;
      }
      const textarea = currentView.document.createElement('textarea');
      textarea.value = value;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      currentView.document.body.appendChild(textarea);
      textarea.select();
      const copied = currentView.document.execCommand('copy');
      textarea.remove();
      return copied;
    } catch (_error) {
      return false;
    }
  }

  function track(view, listingId, surface, method) {
    if (!view || typeof view.fetch !== 'function') return;
    view.fetch('/api/track', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      keepalive: true,
      body: JSON.stringify({
        action: 'listing_share',
        listing_id: positiveInteger(listingId),
        context: { surface, method },
      }),
    }).catch(() => {});
  }

  function bindShare(rootElement, options) {
    const root = rootElement;
    if (!root || root.dataset.shareBound === 'true') return { destroy() {} };
    const trigger = root.querySelector('[data-listing-share-trigger]');
    const menu = root.querySelector('[data-listing-share-menu]');
    const copyButton = root.querySelector('[data-share-copy]');
    const facebookButton = root.querySelector('[data-share-facebook]');
    const status = root.querySelector('[data-share-status]');
    const view = root.ownerDocument.defaultView;
    const config = options || {};
    if (!trigger || !menu) return { destroy() {} };
    root.dataset.shareBound = 'true';

    function listingId() {
      return typeof config.getListingId === 'function'
        ? config.getListingId()
        : root.dataset.listingId;
    }
    function surface() {
      return root.dataset.surface === 'modal' ? 'modal' : 'detail';
    }
    function canonical() {
      return canonicalListingUrl(config.origin || view.location.origin, listingId());
    }
    function setStatus(message) {
      if (status) status.textContent = message;
    }
    function close(restoreFocus) {
      menu.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      if (restoreFocus) trigger.focus();
    }
    function open() {
      menu.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      setStatus('');
      const first = menu.querySelector('button');
      if (first) first.focus();
    }
    function onTrigger() {
      if (menu.hidden) open();
      else close(true);
    }
    async function onCopy(event) {
      event.stopPropagation();
      const url = canonical();
      if (!url) {
        setStatus('Không tạo được liên kết.');
        return;
      }
      const copied = await copyText(url, view);
      setStatus(copied ? 'Đã sao chép liên kết.' : 'Không sao chép được. Hãy thử lại.');
      if (copied) track(view, listingId(), surface(), 'copy');
    }
    function onFacebook(event) {
      event.stopPropagation();
      const url = facebookShareUrl(canonical());
      if (!url) {
        setStatus('Không tạo được liên kết.');
        return;
      }
      const popup = view.open(url, '_blank', 'noopener,noreferrer,width=680,height=620');
      if (popup) {
        track(view, listingId(), surface(), 'facebook');
        close(true);
      } else {
        setStatus('Trình duyệt đã chặn cửa sổ. Bạn có thể sao chép liên kết.');
      }
    }
    function onDocumentClick(event) {
      const path = typeof event.composedPath === 'function' ? event.composedPath() : [];
      if (!path.includes(root) && !root.contains(event.target)) close(false);
    }
    function onKeydown(event) {
      if (event.key === 'Escape' && !menu.hidden) {
        event.preventDefault();
        close(true);
      }
    }

    trigger.addEventListener('click', onTrigger);
    if (copyButton) copyButton.addEventListener('click', onCopy);
    if (facebookButton) facebookButton.addEventListener('click', onFacebook);
    root.ownerDocument.addEventListener('pointerdown', onDocumentClick);
    root.addEventListener('keydown', onKeydown);

    return {
      close,
      destroy() {
        trigger.removeEventListener('click', onTrigger);
        if (copyButton) copyButton.removeEventListener('click', onCopy);
        if (facebookButton) facebookButton.removeEventListener('click', onFacebook);
        root.ownerDocument.removeEventListener('pointerdown', onDocumentClick);
        root.removeEventListener('keydown', onKeydown);
        delete root.dataset.shareBound;
      },
    };
  }

  function bindReport(rootElement, options) {
    const root = rootElement;
    if (!root || root.dataset.reportBound === 'true') return { destroy() {} };
    const trigger = root.querySelector('[data-listing-report-trigger]');
    const overlay = root.querySelector('[data-listing-report-dialog]');
    const form = root.querySelector('[data-listing-report-form]');
    const note = root.querySelector('[data-listing-report-note]');
    const status = root.querySelector('[data-listing-report-status]');
    const submitButton = form && form.querySelector('[type="submit"]');
    const cancelButtons = root.querySelectorAll('[data-listing-report-close]');
    const view = root.ownerDocument.defaultView;
    const config = options || {};
    if (!trigger || !overlay || !form || !submitButton) return { destroy() {} };
    root.dataset.reportBound = 'true';
    let resetOnOpen = false;
    let closeTimer = null;

    function listingId() {
      return typeof config.getListingId === 'function'
        ? config.getListingId()
        : root.dataset.listingId;
    }
    function setStatus(message, state) {
      if (!status) return;
      status.textContent = message;
      status.dataset.state = state || '';
    }
    function close(restoreFocus) {
      overlay.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      if (closeTimer) {
        view.clearTimeout(closeTimer);
        closeTimer = null;
      }
      if (restoreFocus) trigger.focus();
    }
    function open() {
      if (resetOnOpen) {
        form.reset();
        setStatus('');
        resetOnOpen = false;
      }
      overlay.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      const firstReason = form.querySelector('input[name="reason"]');
      if (firstReason) firstReason.focus();
    }
    function errorMessage(result) {
      if (!result || result.error === 'invalid_reason') return 'Vui lòng chọn một lý do.';
      if (result.error === 'invalid_note') return 'Ghi chú tối đa 500 ký tự.';
      if (result.error === 'rate_limited' || result.status === 429) {
        return 'Bạn đã gửi nhiều báo cáo. Vui lòng thử lại sau.';
      }
      if (result.error === 'listing_not_found' || result.status === 404) {
        return 'Tin này không còn khả dụng.';
      }
      if (result.error === 'network_error' || result.status === 0) {
        return 'Mất kết nối. Nội dung vẫn được giữ để bạn thử lại.';
      }
      return 'Chưa gửi được báo cáo. Vui lòng thử lại.';
    }
    async function onSubmit(event) {
      event.preventDefault();
      const selected = form.querySelector('input[name="reason"]:checked');
      const payload = normalizeReportPayload(selected && selected.value, note ? note.value : '');
      if (!payload) {
        setStatus(
          note && note.value.trim().length > 500
            ? 'Ghi chú tối đa 500 ký tự.'
            : 'Vui lòng chọn một lý do.',
          'error',
        );
        return;
      }
      submitButton.disabled = true;
      setStatus('Đang gửi báo cáo...');
      const result = await submitReport(
        config.fetch || view.fetch.bind(view),
        listingId(),
        payload.reason,
        payload.note,
      );
      submitButton.disabled = false;
      if (result && result.ok) {
        setStatus(
          result.duplicate
            ? 'Báo cáo này đã được ghi nhận trước đó.'
            : 'Cảm ơn bạn. Radar đã ghi nhận báo cáo.',
          'success',
        );
        resetOnOpen = true;
        if (typeof config.onTrack === 'function') config.onTrack('submitted');
        closeTimer = view.setTimeout(() => close(true), 1100);
        return;
      }
      setStatus(errorMessage(result), 'error');
    }
    function onCancel() { close(true); }
    function onOverlayClick(event) {
      if (event.target === overlay) close(true);
    }
    function onKeydown(event) {
      if (overlay.hidden) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        close(true);
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(
        overlay.querySelectorAll('button:not([disabled]), input:not([disabled]), textarea:not([disabled])'),
      ).filter((element) => !element.hidden);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && root.ownerDocument.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && root.ownerDocument.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    trigger.addEventListener('click', open);
    form.addEventListener('submit', onSubmit);
    cancelButtons.forEach((button) => button.addEventListener('click', onCancel));
    overlay.addEventListener('click', onOverlayClick);
    overlay.addEventListener('keydown', onKeydown);

    return {
      open,
      close,
      destroy() {
        trigger.removeEventListener('click', open);
        form.removeEventListener('submit', onSubmit);
        cancelButtons.forEach((button) => button.removeEventListener('click', onCancel));
        overlay.removeEventListener('click', onOverlayClick);
        overlay.removeEventListener('keydown', onKeydown);
        if (closeTimer) view.clearTimeout(closeTimer);
        delete root.dataset.reportBound;
      },
    };
  }

  function init(rootDocument) {
    const doc = rootDocument || (typeof document !== 'undefined' ? document : null);
    if (!doc) return [];
    return Array.from(doc.querySelectorAll('[data-listing-actions]')).map((element) => ({
      share: bindShare(element),
      report: bindReport(element),
    }));
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => init(document));
    else init(document);
  }

  return {
    REPORT_REASONS,
    canonicalListingUrl,
    facebookShareUrl,
    normalizeReportPayload,
    submitReport,
    copyText,
    bindShare,
    bindReport,
    init,
  };
}));

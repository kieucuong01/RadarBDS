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
    async function onCopy() {
      const url = canonical();
      if (!url) {
        setStatus('Không tạo được liên kết.');
        return;
      }
      const copied = await copyText(url, view);
      setStatus(copied ? 'Đã sao chép liên kết.' : 'Không sao chép được. Hãy thử lại.');
      if (copied) track(view, listingId(), surface(), 'copy');
    }
    function onFacebook() {
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
      if (!root.contains(event.target)) close(false);
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
    root.ownerDocument.addEventListener('click', onDocumentClick);
    root.addEventListener('keydown', onKeydown);

    return {
      close,
      destroy() {
        trigger.removeEventListener('click', onTrigger);
        if (copyButton) copyButton.removeEventListener('click', onCopy);
        if (facebookButton) facebookButton.removeEventListener('click', onFacebook);
        root.ownerDocument.removeEventListener('click', onDocumentClick);
        root.removeEventListener('keydown', onKeydown);
        delete root.dataset.shareBound;
      },
    };
  }

  function init(rootDocument) {
    const doc = rootDocument || (typeof document !== 'undefined' ? document : null);
    if (!doc) return [];
    return Array.from(doc.querySelectorAll('[data-listing-actions]')).map((element) => bindShare(element));
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
    copyText,
    bindShare,
    init,
  };
}));

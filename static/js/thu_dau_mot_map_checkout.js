(function (factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined") {
    window.RadarThuDauMotMapCheckout = api;
  }
})(function () {
  "use strict";

  var RECOVERY_LINK_PREFIX = "radar:thu-dau-mot-map:recovery-link:";
  var PRODUCT_SLUG = "thu-dau-mot-map-bundle";
  var PRODUCT_VERSION = "1.0";
  var AMOUNT_VND = 99000;
  var TERMINAL_STATES = {
    paid: true,
    expired: true,
    cancelled: true,
    payment_review: true
  };

  function expectedOrderPath(publicId) {
    return /^[0-9a-f]{32}$/.test(publicId || "")
      ? "/ban-do-thu-dau-mot/don-hang/" + publicId
      : "";
  }

  function recoveryLinkKey(publicId) {
    return RECOVERY_LINK_PREFIX + publicId;
  }

  function getRecoveryLink(win, publicId) {
    var expectedPath = expectedOrderPath(publicId);
    if (!expectedPath || win.location.pathname !== expectedPath) return "";
    var stored = "";
    try {
      stored = win.sessionStorage.getItem(recoveryLinkKey(publicId)) || "";
    } catch (error) {
      return "";
    }
    if (!stored) return "";
    try {
      var parsed = new URL(stored);
      var params = new URLSearchParams(parsed.hash.replace(/^#/, ""));
      var keys = Array.from(params.keys());
      if (
        parsed.origin !== win.location.origin
        || parsed.pathname !== expectedPath
        || parsed.search
        || keys.length !== 1
        || keys[0] !== "token"
        || !params.get("token")
      ) {
        return "";
      }
      return parsed.href;
    } catch (error) {
      return "";
    }
  }

  function readRecoveryToken(win, publicId) {
    var target = win || window;
    var fragment = win ? win.location.hash : window.location.hash;
    var params = new URLSearchParams(fragment.replace(/^#/, ""));
    var token = params.get("token");
    var expectedPath = expectedOrderPath(publicId);
    if (
      token
      && expectedPath
      && target.location.pathname === expectedPath
    ) {
      var recoveryUrl = target.location.origin + target.location.pathname
        + "#token=" + encodeURIComponent(token);
      try {
        target.sessionStorage.setItem(
          recoveryLinkKey(publicId),
          recoveryUrl
        );
      } catch (error) {
        // A blocked session store must not prevent fragment removal.
      }
    }
    if (fragment) {
      target.history.replaceState(null, "", target.location.pathname);
    }
    return token || "";
  }

  function authorizeOrder(win, publicId, token) {
    return win.fetch(
      "/api/digital-products/orders/" + encodeURIComponent(publicId) + "/authorize",
      {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        body: JSON.stringify({ token: token })
      }
    ).then(function (response) {
      if (!response.ok) {
        var error = new Error("order_authorization_failed");
        error.status = response.status;
        throw error;
      }
      return true;
    });
  }

  function copyRecoveryLink(win, publicId) {
    var recoveryLink = getRecoveryLink(win, publicId);
    if (!recoveryLink || !win.navigator || !win.navigator.clipboard) {
      return Promise.reject(new Error("recovery_link_unavailable"));
    }
    return win.navigator.clipboard.writeText(recoveryLink);
  }

  function formatMoney(value) {
    return value === AMOUNT_VND ? "99.000đ" : "";
  }

  function formatDateTime(value) {
    var parsed = Date.parse(value || "");
    if (!Number.isFinite(parsed)) return "";
    try {
      return new Intl.DateTimeFormat("vi-VN", {
        dateStyle: "short",
        timeStyle: "short",
        timeZone: "Asia/Ho_Chi_Minh"
      }).format(new Date(parsed));
    } catch (error) {
      return new Date(parsed).toISOString();
    }
  }

  function formatCountdown(value, now) {
    var expiresAt = Date.parse(value || "");
    if (!Number.isFinite(expiresAt)) return "";
    var remaining = Math.max(0, expiresAt - now);
    var totalSeconds = Math.ceil(remaining / 1000);
    var minutes = Math.floor(totalSeconds / 60);
    var seconds = totalSeconds % 60;
    return String(minutes).padStart(2, "0") + ":"
      + String(seconds).padStart(2, "0");
  }

  function setHidden(element, hidden) {
    if (element) element.hidden = hidden;
  }

  function setText(element, value) {
    if (element) element.textContent = value || "";
  }

  function announceStatus(root, status, title, message) {
    var announcement = root.querySelector("[data-order-announcement]");
    if (!announcement || announcement.__radarOrderStatus === status) return;
    announcement.__radarOrderStatus = status;
    announcement.textContent = title + ". " + message;
  }

  function renderConnectionState(root, deadlineReached) {
    if (deadlineReached) {
      renderOrderState(root, { status: "expired" });
      return;
    }
    var title = "Đang kết nối lại";
    var message = "Kết nối tạm thời gián đoạn. Radar BDS sẽ tự thử lại.";
    setText(root.querySelector("[data-order-title]"), title);
    setText(root.querySelector("[data-order-message]"), message);
    announceStatus(
      root,
      "connection_retry",
      title,
      message
    );
  }

  function renderOrderState(root, state, options) {
    options = options || {};
    var now = typeof options.now === "function" ? options.now() : Date.now();
    var status = state && typeof state.status === "string"
      ? state.status
      : "unavailable";
    var live = root.querySelector("[data-order-live]");
    var title = root.querySelector("[data-order-title]");
    var message = root.querySelector("[data-order-message]");
    var qr = root.querySelector("[data-order-qr]");
    var qrImage = root.querySelector("[data-order-qr-image]");
    var label = root.querySelector("[data-order-label]");
    var amount = root.querySelector("[data-order-amount]");
    var countdown = root.querySelector("[data-order-countdown]");
    var copy = root.querySelector("[data-order-copy]");
    var download = root.querySelector("[data-order-download]");
    var newOrder = root.querySelector("[data-order-new]");
    var expiry = root.querySelector("[data-order-expiry]");
    var publicId = root.querySelector("[data-order-public-id]");
    var qrDisplayed = false;

    if (live) live.setAttribute("data-state", status);
    setHidden(qr, true);
    setHidden(copy, true);
    setHidden(download, true);
    setHidden(newOrder, true);
    setText(label, "");
    setText(amount, "");
    setText(countdown, "");
    setText(expiry, "");
    setText(publicId, "");
    if (qrImage) {
      qrImage.removeAttribute("src");
      qrImage.setAttribute("alt", "");
    }

    if (status === "pending") {
      var pendingTitle = "Đang chờ thanh toán";
      var pendingMessage = "Mở ứng dụng ngân hàng, quét VietQR và chuyển đúng số tiền hiển thị.";
      setText(title, pendingTitle);
      setText(message, pendingMessage);
      announceStatus(root, status, pendingTitle, pendingMessage);
      setText(label, state.order_label ? "Mã đơn: " + state.order_label : "");
      setText(amount, formatMoney(state.amount_vnd));
      setText(
        countdown,
        "VietQR còn hiệu lực " + formatCountdown(state.payment_expires_at, now)
      );
      var qrSource = state.qr_svg_data_uri || "";
      if (
        qrImage
        && /^data:image\/svg\+xml;base64,[A-Za-z0-9+/=]+$/.test(qrSource)
      ) {
        qrImage.setAttribute("src", qrSource);
        qrImage.setAttribute("alt", "Mã VietQR thanh toán 99.000 đồng");
        setHidden(qr, false);
        qrDisplayed = Boolean(qr && qr.hidden === false);
      }
      setHidden(copy, options.hasRecoveryLink !== true);
      return { status: status, qrDisplayed: qrDisplayed };
    }

    if (status === "paid") {
      var paidTitle = "Thanh toán thành công";
      var paidMessage = "Bộ bản đồ đã sẵn sàng. Bạn có thể tải lại trong thời hạn 24 giờ.";
      setText(title, paidTitle);
      setText(message, paidMessage);
      announceStatus(root, status, paidTitle, paidMessage);
      setText(
        expiry,
        "Link tải hết hiệu lực lúc " + formatDateTime(state.download_expires_at)
      );
      var expectedDownload = "/api/digital-products/orders/"
        + encodeURIComponent(root.dataset.digitalProductOrder) + "/download";
      if (state.download_url === expectedDownload) {
        download.setAttribute("href", expectedDownload);
        setHidden(download, false);
      }
      return { status: status, qrDisplayed: false };
    }

    if (status === "expired") {
      var expiredTitle = "Đơn hàng đã hết hạn";
      var expiredMessage = "VietQR này không còn hiệu lực. Hãy tạo đơn hàng mới.";
      setText(title, expiredTitle);
      setText(message, expiredMessage);
      announceStatus(root, status, expiredTitle, expiredMessage);
      setHidden(newOrder, false);
      return { status: status, qrDisplayed: false };
    }

    if (status === "cancelled") {
      var cancelledTitle = "Đơn hàng đã hủy";
      var cancelledMessage = "Bạn có thể quay lại trang sản phẩm để tạo đơn hàng mới.";
      setText(title, cancelledTitle);
      setText(message, cancelledMessage);
      announceStatus(root, status, cancelledTitle, cancelledMessage);
      setHidden(newOrder, false);
      return { status: status, qrDisplayed: false };
    }

    if (status === "payment_review") {
      var reviewTitle = "Thanh toán đang cần kiểm tra";
      var reviewMessage = "Radar BDS đã ghi nhận giao dịch nhưng chưa thể tự động giao file.";
      setText(title, reviewTitle);
      setText(message, reviewMessage);
      announceStatus(root, status, reviewTitle, reviewMessage);
      setText(
        publicId,
        "Mã hỗ trợ: " + (root.dataset.digitalProductOrder || "")
      );
      return { status: status, qrDisplayed: false };
    }

    var unavailableTitle = "Chưa thể mở đơn hàng";
    var unavailableMessage = "Link khôi phục không hợp lệ, đã hết hạn hoặc trình duyệt chưa được xác thực.";
    setText(title, unavailableTitle);
    setText(message, unavailableMessage);
    announceStatus(root, status, unavailableTitle, unavailableMessage);
    setHidden(newOrder, false);
    return { status: status, qrDisplayed: false };
  }

  function pollOrder(options) {
    var doc = options.document;
    var now = options.now || Date.now;
    var fetchStatus = options.fetchStatus;
    var render = options.render;
    var renderConnection = options.renderConnection || function () {};
    var setTimer = options.setTimer || setTimeout;
    var clearTimer = options.clearTimer || clearTimeout;
    var startedAt = now();
    var hiddenAt = null;
    var timer = null;
    var stopped = false;
    var terminal = false;
    var fallbackDeadline = startedAt + 900000;
    var authoritativeDeadline = null;

    function clearScheduled() {
      if (timer !== null) clearTimer(timer);
      timer = null;
    }

    function schedule(delay) {
      clearScheduled();
      timer = setTimer(tick, delay);
    }

    function nextDelay() {
      return now() - startedAt < 60000 ? 2000 : 5000;
    }

    function activeDeadline() {
      return authoritativeDeadline === null
        ? fallbackDeadline
        : authoritativeDeadline;
    }

    function stopAtDeadline() {
      stopped = true;
      clearScheduled();
      renderConnection(true);
      return Promise.resolve(null);
    }

    function scheduleWithinDeadline() {
      var remaining = activeDeadline() - now();
      if (remaining <= 0) return stopAtDeadline();
      schedule(Math.min(nextDelay(), remaining));
      return Promise.resolve(null);
    }

    function tick() {
      if (stopped || terminal) return Promise.resolve(null);
      if (now() >= activeDeadline()) return stopAtDeadline();
      if (doc.hidden) {
        if (hiddenAt === null) hiddenAt = now();
        var hiddenFor = now() - hiddenAt;
        if (hiddenFor >= 300000) {
          clearScheduled();
          stopped = true;
          return Promise.resolve(null);
        }
        schedule(Math.min(300000 - hiddenFor, activeDeadline() - now()));
        return Promise.resolve(null);
      }
      hiddenAt = null;
      return Promise.resolve().then(fetchStatus).then(function (state) {
        if (!state || typeof state.status !== "string") {
          throw new Error("invalid_order_status");
        }
        if (state.status === "pending") {
          var pendingDeadline = Date.parse(state.payment_expires_at || "");
          if (!Number.isFinite(pendingDeadline)) {
            throw new Error("invalid_payment_deadline");
          }
          authoritativeDeadline = pendingDeadline;
          if (now() >= activeDeadline()) return stopAtDeadline();
        } else if (!TERMINAL_STATES[state.status]) {
          throw new Error("invalid_order_status");
        }
        render(state);
        if (TERMINAL_STATES[state.status]) {
          terminal = true;
          clearScheduled();
          return state;
        }
        if (state.status !== "pending") {
          stopped = true;
          clearScheduled();
          return state;
        }
        scheduleWithinDeadline();
        return state;
      }).catch(function () {
        if (now() >= activeDeadline()) return stopAtDeadline();
        renderConnection(false);
        scheduleWithinDeadline();
        return null;
      });
    }

    function handleVisibility() {
      clearScheduled();
      if (doc.hidden) {
        if (now() >= activeDeadline()) {
          stopAtDeadline();
          return;
        }
        hiddenAt = now();
        schedule(Math.min(300000, activeDeadline() - now()));
        return;
      }
      hiddenAt = null;
      if (!terminal) {
        stopped = false;
        tick();
      }
    }

    function start() {
      stopped = false;
      doc.addEventListener("visibilitychange", handleVisibility);
      return tick();
    }

    function stop() {
      stopped = true;
      clearScheduled();
      doc.removeEventListener("visibilitychange", handleVisibility);
    }

    return {
      start: start,
      stop: stop,
      tick: tick,
      handleVisibility: handleVisibility,
      nextDelay: nextDelay
    };
  }

  function safeTrackingContext(status) {
    var coarse = {
      pending: true,
      paid: true,
      expired: true,
      cancelled: true,
      payment_review: true
    };
    return {
      product_slug: PRODUCT_SLUG,
      product_version: PRODUCT_VERSION,
      amount_vnd: AMOUNT_VND,
      order_status: coarse[status] ? status : "pending"
    };
  }

  function sendTrack(win, action, status) {
    return win.fetch("/api/track", {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify({
        action: action,
        context: safeTrackingContext(status)
      })
    }).catch(function () {
      return null;
    });
  }

  function fetchOrderStatus(win, publicId) {
    return win.fetch(
      "/api/digital-products/orders/" + encodeURIComponent(publicId) + "/status",
      {
        method: "GET",
        credentials: "same-origin",
        headers: { "Accept": "application/json" },
        cache: "no-store"
      }
    ).then(function (response) {
      if (!response.ok) throw new Error("order_status_unavailable");
      return response.json();
    });
  }

  function init(doc, win) {
    var root = doc.querySelector("[data-digital-product-order]");
    if (!root) return;
    var publicId = root.dataset.digitalProductOrder || "";
    var token = readRecoveryToken(win, publicId);
    var createdTracked = false;
    var qrTracked = false;
    var paidTracked = false;

    function renderAndTrack(state) {
      var rendered = renderOrderState(root, state, {
        hasRecoveryLink: Boolean(getRecoveryLink(win, publicId))
      });
      var status = rendered.status;
      if (!createdTracked) {
        createdTracked = true;
        sendTrack(win, "thu_dau_mot_map_checkout_created", status);
      }
      if (status === "pending" && rendered.qrDisplayed && !qrTracked) {
        qrTracked = true;
        sendTrack(win, "thu_dau_mot_map_qr_displayed", status);
      }
      if (status === "paid" && !paidTracked) {
        paidTracked = true;
        sendTrack(win, "thu_dau_mot_map_payment_confirmed", status);
      }
    }

    function beginPolling() {
      pollOrder({
        document: doc,
        fetchStatus: function () {
          return fetchOrderStatus(win, publicId);
        },
        render: renderAndTrack,
        renderConnection: function (deadlineReached) {
          renderConnectionState(root, deadlineReached);
        }
      }).start().catch(function () {
        renderOrderState(root, { status: "unavailable" });
      });
    }

    var authorized = token
      ? authorizeOrder(win, publicId, token)
      : Promise.resolve(true);
    authorized.then(beginPolling).catch(function () {
      renderOrderState(root, { status: "unavailable" });
    });

    var copy = root.querySelector("[data-order-copy]");
    if (copy) {
      copy.addEventListener("click", function () {
        copyRecoveryLink(win, publicId).then(function () {
          copy.textContent = "Đã sao chép link khôi phục";
        }).catch(function () {
          copy.textContent = "Không thể sao chép link";
        });
      });
    }

    var download = root.querySelector("[data-order-download]");
    if (download) {
      download.addEventListener("click", function () {
        sendTrack(win, "thu_dau_mot_map_download_clicked", "paid");
      });
    }
  }

  if (typeof document !== "undefined" && typeof window !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        init(document, window);
      }, { once: true });
    } else {
      init(document, window);
    }
  }

  return {
    readRecoveryToken: readRecoveryToken,
    authorizeOrder: authorizeOrder,
    pollOrder: pollOrder,
    renderOrderState: renderOrderState,
    renderConnectionState: renderConnectionState,
    copyRecoveryLink: copyRecoveryLink,
    init: init
  };
});

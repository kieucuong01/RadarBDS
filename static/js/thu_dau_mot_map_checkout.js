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

  var RECOVERY_LINK_KEY = "radar:thu-dau-mot-map:recovery-link";
  var PRODUCT_SLUG = "thu-dau-mot-map-bundle";
  var PRODUCT_VERSION = "1.0";
  var AMOUNT_VND = 99000;
  var TERMINAL_STATES = {
    paid: true,
    expired: true,
    cancelled: true,
    payment_review: true
  };

  function readRecoveryToken(win) {
    var target = win || window;
    var fragment = win ? win.location.hash : window.location.hash;
    var params = new URLSearchParams(fragment.replace(/^#/, ""));
    var token = params.get("token");
    if (token) {
      var recoveryUrl = target.location.origin + target.location.pathname
        + "#token=" + encodeURIComponent(token);
      try {
        target.sessionStorage.setItem(RECOVERY_LINK_KEY, recoveryUrl);
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

  function copyRecoveryLink(win) {
    var recoveryLink = "";
    try {
      recoveryLink = win.sessionStorage.getItem(RECOVERY_LINK_KEY) || "";
    } catch (error) {
      recoveryLink = "";
    }
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

    if (status === "pending") {
      setText(title, "Đang chờ thanh toán");
      setText(
        message,
        "Mở ứng dụng ngân hàng, quét VietQR và chuyển đúng số tiền hiển thị."
      );
      setText(label, state.order_label ? "Mã đơn: " + state.order_label : "");
      setText(amount, formatMoney(state.amount_vnd));
      setText(
        countdown,
        "VietQR còn hiệu lực " + formatCountdown(state.payment_expires_at, now)
      );
      var qrSource = state.qr_svg_data_uri || "";
      if (/^data:image\/svg\+xml;base64,[A-Za-z0-9+/=]+$/.test(qrSource)) {
        qrImage.setAttribute("src", qrSource);
        qrImage.setAttribute("alt", "Mã VietQR thanh toán 99.000 đồng");
        setHidden(qr, false);
      }
      setHidden(copy, false);
      return status;
    }

    if (status === "paid") {
      setText(title, "Thanh toán thành công");
      setText(
        message,
        "Bộ bản đồ đã sẵn sàng. Bạn có thể tải lại trong thời hạn 24 giờ."
      );
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
      return status;
    }

    if (status === "expired") {
      setText(title, "Đơn hàng đã hết hạn");
      setText(message, "VietQR này không còn hiệu lực. Hãy tạo đơn hàng mới.");
      setHidden(newOrder, false);
      return status;
    }

    if (status === "cancelled") {
      setText(title, "Đơn hàng đã hủy");
      setText(message, "Bạn có thể quay lại trang sản phẩm để tạo đơn hàng mới.");
      setHidden(newOrder, false);
      return status;
    }

    if (status === "payment_review") {
      setText(title, "Thanh toán đang cần kiểm tra");
      setText(
        message,
        "Radar BDS đã ghi nhận giao dịch nhưng chưa thể tự động giao file."
      );
      setText(
        publicId,
        "Mã hỗ trợ: " + (root.dataset.digitalProductOrder || "")
      );
      return status;
    }

    setText(title, "Chưa thể mở đơn hàng");
    setText(
      message,
      "Link khôi phục không hợp lệ, đã hết hạn hoặc trình duyệt chưa được xác thực."
    );
    setHidden(newOrder, false);
    return status;
  }

  function pollOrder(options) {
    var doc = options.document;
    var now = options.now || Date.now;
    var fetchStatus = options.fetchStatus;
    var render = options.render;
    var setTimer = options.setTimer || setTimeout;
    var clearTimer = options.clearTimer || clearTimeout;
    var startedAt = now();
    var hiddenAt = null;
    var timer = null;
    var stopped = false;
    var terminal = false;

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

    function tick() {
      if (stopped || terminal) return Promise.resolve(null);
      if (doc.hidden) {
        if (hiddenAt === null) hiddenAt = now();
        var hiddenFor = now() - hiddenAt;
        if (hiddenFor >= 300000) {
          clearScheduled();
          stopped = true;
          return Promise.resolve(null);
        }
        schedule(300000 - hiddenFor);
        return Promise.resolve(null);
      }
      hiddenAt = null;
      return Promise.resolve(fetchStatus()).then(function (state) {
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
        schedule(nextDelay());
        return state;
      });
    }

    function handleVisibility() {
      clearScheduled();
      if (doc.hidden) {
        hiddenAt = now();
        schedule(300000);
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
    var token = readRecoveryToken(win);
    var createdTracked = false;
    var qrTracked = false;
    var paidTracked = false;

    function renderAndTrack(state) {
      var status = renderOrderState(root, state);
      if (!createdTracked) {
        createdTracked = true;
        sendTrack(win, "thu_dau_mot_map_checkout_created", status);
      }
      if (status === "pending" && state.qr_svg_data_uri && !qrTracked) {
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
        render: renderAndTrack
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
        copyRecoveryLink(win).then(function () {
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
    copyRecoveryLink: copyRecoveryLink,
    init: init
  };
});

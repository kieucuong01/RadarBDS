from __future__ import annotations

import json
import subprocess
from pathlib import Path


CHECKOUT_JS = Path("static/js/thu_dau_mot_map_checkout.js")
CHECKOUT_EVENTS = (
    "thu_dau_mot_map_checkout_created",
    "thu_dau_mot_map_qr_displayed",
    "thu_dau_mot_map_payment_confirmed",
    "thu_dau_mot_map_download_clicked",
)


def _run_node(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "-e", script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )


def test_checkout_module_exists_and_exports_required_browser_functions():
    result = _run_node(
        r"""
const checkout = require("./static/js/thu_dau_mot_map_checkout.js");
const expected = [
  "readRecoveryToken",
  "authorizeOrder",
  "pollOrder",
  "renderOrderState",
  "copyRecoveryLink"
];
for (const name of expected) {
  if (typeof checkout[name] !== "function") {
    throw new Error("missing export: " + name);
  }
}
"""
    )

    assert result.returncode == 0, result.stderr


def test_read_recovery_token_keeps_recovery_url_in_session_and_clears_fragment():
    result = _run_node(
        r"""
const checkout = require("./static/js/thu_dau_mot_map_checkout.js");
const calls = [];
const stored = {};
const win = {
  location: {
    hash: "#token=secret%2Bvalue",
    origin: "https://radarbds.vn",
    pathname: "/ban-do-thu-dau-mot/don-hang/abc"
  },
  history: {
    replaceState(state, title, url) {
      calls.push(["replace", url]);
      win.location.hash = "";
    }
  },
  sessionStorage: {
    setItem(key, value) { stored[key] = value; },
    getItem(key) { return stored[key] || null; }
  }
};
const token = checkout.readRecoveryToken(win);
if (token !== "secret+value") process.exit(1);
if (calls.length !== 1 || calls[0][1] !== win.location.pathname) process.exit(2);
const values = Object.values(stored);
if (values.length !== 1 || values[0] !== "https://radarbds.vn/ban-do-thu-dau-mot/don-hang/abc#token=secret%2Bvalue") process.exit(3);
"""
    )

    assert result.returncode == 0, result.stderr


def test_read_recovery_token_clears_unknown_fragment_before_other_work():
    result = _run_node(
        r"""
const checkout = require("./static/js/thu_dau_mot_map_checkout.js");
const calls = [];
const win = {
  location: {
    hash: "#unexpected-private-fragment",
    origin: "https://radarbds.vn",
    pathname: "/ban-do-thu-dau-mot/don-hang/abc"
  },
  history: {
    replaceState(_state, _title, url) { calls.push(url); }
  },
  sessionStorage: { setItem() { process.exit(1); } }
};
if (checkout.readRecoveryToken(win) !== "") process.exit(2);
if (calls.length !== 1 || calls[0] !== win.location.pathname) process.exit(3);
"""
    )

    assert result.returncode == 0, result.stderr


def test_authorize_posts_json_without_ever_placing_token_in_a_url():
    result = _run_node(
        r"""
const checkout = require("./static/js/thu_dau_mot_map_checkout.js");
let request;
const win = {
  fetch(url, options) {
    request = { url, options };
    return Promise.resolve({ ok: true, status: 204 });
  }
};
checkout.authorizeOrder(win, "a".repeat(32), "private-token").then(() => {
  if (request.url.includes("private-token") || request.url.includes("?token=")) process.exit(1);
  if (request.options.method !== "POST") process.exit(2);
  if (JSON.parse(request.options.body).token !== "private-token") process.exit(3);
  if (request.options.credentials !== "same-origin") process.exit(4);
}).catch((error) => {
  console.error(error);
  process.exit(5);
});
"""
    )

    assert result.returncode == 0, result.stderr


def test_polling_uses_fast_then_slow_cadence_and_stops_on_terminal_state():
    result = _run_node(
        r"""
const checkout = require("./static/js/thu_dau_mot_map_checkout.js");
let now = 0;
let timerDelay = null;
let renders = [];
let states = [
  {status: "pending", payment_expires_at: "2030-01-01T00:00:00Z"},
  {status: "pending", payment_expires_at: "2030-01-01T00:00:00Z"},
  {status: "paid", download_expires_at: "2030-01-02T00:00:00Z"}
];
const controller = checkout.pollOrder({
  document: { hidden: false, addEventListener() {}, removeEventListener() {} },
  now: () => now,
  fetchStatus: () => Promise.resolve(states.shift()),
  render: (state) => renders.push(state.status),
  setTimer: (_fn, delay) => { timerDelay = delay; return 1; },
  clearTimer() {}
});
(async () => {
  await controller.tick();
  if (timerDelay !== 2000) process.exit(1);
  now = 61000;
  await controller.tick();
  if (timerDelay !== 5000) process.exit(2);
  timerDelay = null;
  await controller.tick();
  if (timerDelay !== null) process.exit(3);
  if (renders.join(",") !== "pending,pending,paid") process.exit(4);
})().catch((error) => {
  console.error(error);
  process.exit(5);
});
"""
    )

    assert result.returncode == 0, result.stderr


def test_polling_pauses_after_five_hidden_minutes_and_resumes_when_visible():
    result = _run_node(
        r"""
const checkout = require("./static/js/thu_dau_mot_map_checkout.js");
let now = 0;
let requests = 0;
let scheduled = [];
const doc = {
  hidden: false,
  listener: null,
  addEventListener(name, callback) { if (name === "visibilitychange") this.listener = callback; },
  removeEventListener() {}
};
const controller = checkout.pollOrder({
  document: doc,
  now: () => now,
  fetchStatus: () => {
    requests += 1;
    return Promise.resolve({status: "pending", payment_expires_at: "2030-01-01T00:00:00Z"});
  },
  render() {},
  setTimer: (fn, delay) => { scheduled.push({fn, delay}); return scheduled.length; },
  clearTimer() {}
});
(async () => {
  controller.start();
  await Promise.resolve();
  doc.hidden = true;
  now = 1000;
  doc.listener();
  now = 301001;
  const hiddenTimer = scheduled[scheduled.length - 1];
  hiddenTimer.fn();
  await Promise.resolve();
  const pausedRequests = requests;
  doc.hidden = false;
  doc.listener();
  await Promise.resolve();
  await Promise.resolve();
  if (requests !== pausedRequests + 1) process.exit(1);
})().catch((error) => {
  console.error(error);
  process.exit(2);
});
"""
    )

    assert result.returncode == 0, result.stderr


def test_renderer_supports_all_public_states_without_identifier_tracking():
    result = _run_node(
        r"""
const checkout = require("./static/js/thu_dau_mot_map_checkout.js");
function node() {
  return {
    hidden: false,
    textContent: "",
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
    removeAttribute(name) { delete this.attrs[name]; }
  };
}
const selectors = [
  "[data-order-live]", "[data-order-title]", "[data-order-message]",
  "[data-order-qr]", "[data-order-qr-image]", "[data-order-label]",
  "[data-order-amount]", "[data-order-countdown]", "[data-order-copy]",
  "[data-order-download]", "[data-order-new]", "[data-order-expiry]",
  "[data-order-public-id]"
];
const nodes = Object.fromEntries(selectors.map((selector) => [selector, node()]));
const root = {
  dataset: { digitalProductOrder: "public-safe-id" },
  querySelector(selector) { return nodes[selector] || null; }
};
const statuses = ["pending", "paid", "expired", "cancelled", "payment_review"];
for (const status of statuses) {
  checkout.renderOrderState(root, {
    status,
    amount_vnd: 99000,
    order_label: "BDTEST",
    qr_svg_data_uri: "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
    payment_expires_at: "2030-01-01T00:00:00Z",
    download_expires_at: "2030-01-02T00:00:00Z",
    download_url: "/api/digital-products/orders/public-safe-id/download"
  }, {now: () => 0});
  if (nodes["[data-order-live]"].attrs["data-state"] !== status) process.exit(1);
}
if (!nodes["[data-order-public-id]"].textContent.includes("public-safe-id")) process.exit(2);
"""
    )

    assert result.returncode == 0, result.stderr


def test_checkout_source_has_no_persistent_or_query_string_token_storage():
    source = CHECKOUT_JS.read_text(encoding="utf-8")

    assert "window.location.hash" in source
    assert "history.replaceState" in source
    assert "?token=" not in source
    assert "localStorage" not in source
    assert "document.cookie" not in source
    for forbidden in (
        "recovery_token",
        "raw_order_code",
        "payment_reference",
        "payos_signature",
    ):
        assert forbidden not in source


def test_checkout_tracking_names_and_context_are_privacy_bounded(monkeypatch):
    import app as radar_app
    from auth import core as auth_core

    recorded = []
    monkeypatch.setattr(auth_core, "current_tier", lambda: "admin")
    monkeypatch.setattr(
        radar_app,
        "log_audit",
        lambda **payload: recorded.append(payload),
    )
    monkeypatch.setattr(radar_app, "current_user", lambda: None)
    monkeypatch.setattr(radar_app, "current_tier", lambda: "guest")
    client = radar_app.app.test_client()
    for action in CHECKOUT_EVENTS:
        assert action in radar_app.ALLOWED_TRACK_ACTIONS
        response = client.post(
            "/api/track",
            json={
                "action": action,
                "listing_id": 99,
                "context": {
                    "product_slug": "thu-dau-mot-map-bundle",
                    "product_version": "1.0",
                    "amount_vnd": 99_000,
                    "order_status": "paid",
                    "public_id": "must-drop",
                    "order_label": "must-drop",
                    "download_url": "must-drop",
                },
            },
        )
        assert response.status_code == 200

    expected = {
        "product_slug": "thu-dau-mot-map-bundle",
        "product_version": "1.0",
        "amount_vnd": 99_000,
        "order_status": "paid",
    }
    assert len(recorded) == len(CHECKOUT_EVENTS)
    assert all(item["context"] == expected for item in recorded)
    assert all(item["listing_id"] is None for item in recorded)


def test_checkout_module_only_emits_the_approved_context_keys():
    source = CHECKOUT_JS.read_text(encoding="utf-8")
    for event in CHECKOUT_EVENTS:
        assert event in source
    for forbidden in (
        "public_id:",
        "order_label:",
        "download_url:",
        "payment_expires_at:",
        "download_expires_at:",
    ):
        assert forbidden not in source


def test_invalid_order_never_emits_checkout_tracking_and_fragment_is_cleared_first():
    result = _run_node(
        r"""
const checkout = require("./static/js/thu_dau_mot_map_checkout.js");
const calls = [];
function node() {
  return {
    hidden: false,
    textContent: "",
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
    removeAttribute(name) { delete this.attrs[name]; },
    addEventListener() {}
  };
}
const root = node();
root.dataset = { digitalProductOrder: "a".repeat(32) };
root.querySelector = () => node();
const doc = {
  hidden: false,
  readyState: "complete",
  querySelector() { return root; },
  addEventListener() {},
  removeEventListener() {}
};
const win = {
  location: {
    hash: "#untrusted-private-fragment",
    origin: "https://radarbds.vn",
    pathname: "/ban-do-thu-dau-mot/don-hang/" + "a".repeat(32)
  },
  history: {
    replaceState() { calls.push("replace"); }
  },
  sessionStorage: { setItem() {}, getItem() { return null; } },
  navigator: {},
  fetch(url) {
    calls.push(url);
    return Promise.resolve({ok: false, status: 404});
  }
};
checkout.init(doc, win);
setImmediate(() => {
  if (calls[0] !== "replace") process.exit(1);
  if (calls.some((value) => value === "/api/track")) process.exit(2);
});
"""
    )

    assert result.returncode == 0, result.stderr


def test_checkout_created_is_emitted_only_after_first_successful_status():
    result = _run_node(
        r"""
const checkout = require("./static/js/thu_dau_mot_map_checkout.js");
const calls = [];
function node() {
  return {
    hidden: false,
    textContent: "",
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
    removeAttribute(name) { delete this.attrs[name]; },
    addEventListener() {}
  };
}
const root = node();
root.dataset = { digitalProductOrder: "b".repeat(32) };
root.querySelector = () => node();
const doc = {
  hidden: false,
  readyState: "complete",
  querySelector() { return root; },
  addEventListener() {},
  removeEventListener() {}
};
const win = {
  location: {
    hash: "",
    origin: "https://radarbds.vn",
    pathname: "/ban-do-thu-dau-mot/don-hang/" + "b".repeat(32)
  },
  history: { replaceState() { calls.push("replace"); } },
  sessionStorage: { setItem() {}, getItem() { return null; } },
  navigator: {},
  fetch(url, options) {
    calls.push(url);
    if (url === "/api/track") {
      calls.push(JSON.parse(options.body));
      return Promise.resolve({ok: true});
    }
    return Promise.resolve({
      ok: true,
      json() {
        return Promise.resolve({
          status: "paid",
          amount_vnd: 99000,
          download_expires_at: "2030-01-01T00:00:00Z",
          download_url: "/api/digital-products/orders/" + "b".repeat(32) + "/download"
        });
      }
    });
  }
};
checkout.init(doc, win);
setImmediate(() => {
  const payloads = calls.filter((value) => value && value.action);
  const created = payloads.find((value) => value.action === "thu_dau_mot_map_checkout_created");
  if (!created || created.context.order_status !== "paid") process.exit(1);
  const statusIndex = calls.findIndex((value) => typeof value === "string" && value.endsWith("/status"));
  const trackIndex = calls.indexOf("/api/track");
  if (statusIndex < 0 || trackIndex <= statusIndex) process.exit(2);
});
"""
    )

    assert result.returncode == 0, result.stderr

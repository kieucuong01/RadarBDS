const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

(async () => {
  const status = { textContent: '' };
  const button = { disabled: false, textContent: '', attrs: {},
    parentElement: { querySelector: () => status },
    setAttribute(name, value) { this.attrs[name] = value; } };
  const requests = [];
  let fail = false;
  const sandbox = {
    window: { USER_TIER: 'vip', CURRENT_USER: { id: 7 } },
    document: { querySelectorAll: () => [] },
    escHtml: (x) => String(x),
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (fail) return { ok: false, status: 500 };
      if (!options.method) return { ok: true, json: async () => ({ listing_ids: [42], items: [{ listing_id: 42, alert_enabled: false }] }) };
      return { ok: true, json: async () => ({ alert_enabled: JSON.parse(options.body).alert_enabled }) };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../static/js/main/signals.js'), 'utf8'), sandbox);
  await sandbox.window.RadarFavorites.load();
  assert.match(sandbox.savedAlertButtonHtml(42, 'inactive'), /chưa xác nhận đã bán/);
  assert.match(sandbox.savedAlertButtonHtml(42), /aria-pressed="false"/);
  const event = { currentTarget: button, preventDefault() {}, stopPropagation() {} };
  await sandbox.window.toggleSavedListingAlert(42, event);
  assert.equal(requests.at(-1).options.method, 'PATCH');
  assert.deepEqual(JSON.parse(requests.at(-1).options.body), { alert_enabled: true });
  assert.equal(button.attrs['aria-pressed'], 'true');
  assert.equal(button.disabled, false);
  fail = true;
  await sandbox.window.toggleSavedListingAlert(42, event);
  assert.equal(button.attrs['aria-pressed'], 'true');
  assert.match(status.textContent, /Chưa lưu/);
  fail = false;
  await sandbox.window.toggleSavedListingAlert(42, event);
  assert.equal(button.attrs['aria-pressed'], 'false');
  sandbox.window.CURRENT_USER = { id: 8 };
  await sandbox.window.RadarFavorites.load();
  assert.match(sandbox.savedAlertButtonHtml(42), /aria-pressed="false"/);
  console.log('saved listing alert controls: passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });

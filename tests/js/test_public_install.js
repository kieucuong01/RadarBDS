'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/public_install.js', 'utf8');

function setup(userAgent = 'Android', standalone = false) {
  const events = {};
  const elements = {};
  for (const id of ['radarInstallDialog', 'radarInstallSteps', 'radarInstallConfirm', 'radarInstallStatus']) {
    elements[id] = {
      hidden: false, disabled: false, open: false, textContent: '', children: [],
      replaceChildren() { this.children = []; },
      appendChild(item) { this.children.push(item); },
      showModal() { this.open = true; },
      addEventListener(name, fn) { this[name] = fn; }
    };
  }
  const document = {
    getElementById: id => elements[id], querySelectorAll: () => [],
    createElement: () => ({ textContent: '' }),
    body: { appendChild(item) { document.movedDialog = item; } },
    addEventListener(name, fn) { events[name] = fn; }
  };
  const window = {
    matchMedia: () => ({ matches: standalone }),
    addEventListener(name, fn) { events[name] = fn; }
  };
  vm.runInNewContext(source, { window, document, navigator: { userAgent, platform: '', maxTouchPoints: 0 } });
  events.DOMContentLoaded();
  const open = () => events.click({ target: { closest: () => ({}) } });
  return { events, elements, document, open };
}

(async () => {
  const android = setup();
  android.open();
  assert.ok(android.elements.radarInstallDialog.open);
  assert.equal(android.document.movedDialog, android.elements.radarInstallDialog, 'dialog must escape a collapsed footer');
  assert.ok(android.elements.radarInstallConfirm.hidden);
  assert.match(android.elements.radarInstallSteps.children[1].textContent, /menu ⋮/);
  let prompts = 0;
  let prevented = false;
  android.events.beforeinstallprompt({
    preventDefault() { prevented = true; },
    async prompt() { prompts++; }, userChoice: Promise.resolve({ outcome: 'dismissed' })
  });
  assert.ok(prevented);
  assert.equal(android.elements.radarInstallConfirm.hidden, false);
  assert.equal(prompts, 0, 'must never prompt without explicit user action');
  await android.elements.radarInstallConfirm.click();
  await android.elements.radarInstallConfirm.click();
  assert.equal(prompts, 1, 'native prompt must only be used once');
  assert.match(android.elements.radarInstallStatus.textContent, /cài lại/);
  android.events.appinstalled();
  assert.match(android.elements.radarInstallStatus.textContent, /đã được cài/);
  assert.ok(android.elements.radarInstallConfirm.hidden);

  const ios = setup('iPhone');
  ios.open();
  assert.match(ios.elements.radarInstallSteps.children[1].textContent, /Chia sẻ/);
  const installed = setup('Android', true);
  installed.open();
  assert.equal(installed.elements.radarInstallSteps.children.length, 0);
  assert.match(installed.elements.radarInstallStatus.textContent, /đã được cài/);
  console.log('Public install: explicit prompt, one-use dismissal, iOS fallback and installed state passed');
})().catch(error => { console.error(error); process.exitCode = 1; });

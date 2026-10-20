'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const events = {};
let activeElement;
function element() {
  const classes = new Set();
  return {
    attributes: {}, children: [], hidden: true,
    classList: { contains: name => classes.has(name), toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); } },
    appendChild(child) { child.parentElement = this; this.children.push(child); },
    contains(child) { return child === this || child.parentElement === this; },
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    focus() { activeElement = this; }
  };
}
const menu = element(), dropdown = element(), backdrop = element(), trigger = element();
const first = element(), last = element(), body = element();
menu.appendChild(dropdown);
menu.appendChild(trigger);
dropdown.appendChild(first);
dropdown.appendChild(last);
dropdown.querySelector = () => first;
dropdown.querySelectorAll = () => [first, last];
const elements = { userMenu: menu, userMenuDropdown: dropdown, userMenuBackdrop: backdrop };
const media = { matches: true, addEventListener(name, fn) { this.change = fn; } };
const document = {
  body, readyState: 'complete', get activeElement() { return activeElement; },
  getElementById: id => elements[id], querySelector: () => trigger,
  addEventListener(name, fn) { (events[name] ||= []).push(fn); }
};
const window = { matchMedia: () => media, addEventListener() {} };
const context = { window, document, fetch() { throw new Error('Opening the menu must never require network'); } };
vm.runInNewContext(fs.readFileSync('static/js/main/account_menu.js', 'utf8'), context);
const click = target => events.click.forEach(fn => fn({ target }));
const key = (name, shiftKey = false) => {
  let prevented = false;
  events.keydown.forEach(fn => fn({ key: name, shiftKey, preventDefault() { prevented = true; } }));
  return prevented;
};
function assertOpen() {
  assert.ok(dropdown.classList.contains('open'));
  assert.equal(backdrop.hidden, false);
  assert.equal(dropdown.parentElement, body);
  assert.equal(dropdown.attributes['aria-modal'], 'true');
}

assert.equal(window.RadarAuth.__radarAuthLoaded, undefined);
window.RadarAuth.toggleUserMenu({ stopPropagation() {} });
assertOpen();
assert.equal(activeElement, first);
click(last);
assertOpen();
last.focus();
assert.ok(key('Tab'));
assert.equal(activeElement, first);
assert.ok(key('Tab', true));
assert.equal(activeElement, last);
click(backdrop);
assert.equal(backdrop.hidden, true);
assert.equal(activeElement, trigger);
assert.equal(dropdown.parentElement, menu);

window.RadarAuth.toggleUserMenu();
assert.ok(key('Escape'));
assert.equal(dropdown.classList.contains('open'), false);
window.RadarAuth.toggleUserMenu();
media.matches = false;
media.change();
assert.equal(dropdown.parentElement, menu);
assert.equal(backdrop.hidden, true);
assert.equal(dropdown.attributes.role, 'menu');
media.matches = true;
media.change();
assertOpen();

// Loading the auth module later must retain the shell's portal/backdrop behavior.
vm.runInNewContext(fs.readFileSync('static/js/auth.js', 'utf8'), context);
window.RadarAuth.toggleUserMenu();
assert.equal(dropdown.classList.contains('open'), false);
window.RadarAuth.toggleUserMenu();
assertOpen();
assert.equal(events.click.length, 1, 'auth must not attach the obsolete outside-click handler');
console.log('Account menu: synchronous open, backdrop, inside/outside clicks, focus, Escape, resize and lazy auth integration passed');

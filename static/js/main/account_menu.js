// The already-rendered account menu must open without loading auth/modal assets.
(function () {
  'use strict';
  const menu = document.getElementById('userMenu');
  const dropdown = document.getElementById('userMenuDropdown');
  const backdrop = document.getElementById('userMenuBackdrop');
  const trigger = document.querySelector('.user-menu-trigger');
  if (!menu || !dropdown || !trigger || !backdrop) return;
  const mobile = window.matchMedia('(max-width: 1024px)');

  function setOpen(open) {
    const wasOpen = dropdown.classList.contains('open');
    const shouldOpen = Boolean(open);
    // Escape the header's backdrop-filter stacking context on mobile.
    (shouldOpen && mobile.matches ? document.body : menu).appendChild(dropdown);
    dropdown.classList.toggle('open', shouldOpen);
    dropdown.setAttribute('role', mobile.matches ? 'dialog' : 'menu');
    if (shouldOpen && mobile.matches) dropdown.setAttribute('aria-modal', 'true');
    else dropdown.removeAttribute('aria-modal');
    trigger.setAttribute('aria-expanded', String(shouldOpen));
    trigger.setAttribute('aria-haspopup', mobile.matches ? 'dialog' : 'menu');
    backdrop.hidden = !(shouldOpen && mobile.matches);
    document.body.classList.toggle('user-menu-open', shouldOpen && mobile.matches);
    if (shouldOpen && mobile.matches && (!wasOpen || !dropdown.contains(document.activeElement))) dropdown.querySelector('button').focus();
    if (!shouldOpen && wasOpen) trigger.focus();
  }

  function toggle(event) {
    if (event) event.stopPropagation();
    setOpen(!dropdown.classList.contains('open'));
  }

  function close() { setOpen(false); }
  document.addEventListener('click', function (event) {
    if (!menu.contains(event.target) && !dropdown.contains(event.target)) close();
  });
  document.addEventListener('keydown', function (event) {
    if (!dropdown.classList.contains('open')) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key !== 'Tab' || !mobile.matches) return;
    const buttons = Array.from(dropdown.querySelectorAll('button:not([disabled])'));
    const first = buttons[0];
    const last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  });
  mobile.addEventListener('change', function () {
    if (dropdown.classList.contains('open')) setOpen(true);
  });
  window.RadarAccountMenu = { setOpen, toggle, close };
  window.RadarAuth = window.RadarAuth || {};
  window.RadarAuth.toggleUserMenu = toggle;
})();

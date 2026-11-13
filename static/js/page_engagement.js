(() => {
  if (window.RadarPageEngagement || navigator.globalPrivacyControl || navigator.doNotTrack === '1') return;
  window.RadarPageEngagement = true;
  const path = location.pathname.replace(/\/$/, '') || '/';
  const view = Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
  const reading = document.querySelector('.article-reading-column, main article');
  const content = reading && reading.getBoundingClientRect().height > innerHeight ? reading : null;
  let elapsed = 0;
  let last = performance.now();
  let activity = last;
  let visible = document.visibilityState === 'visible';
  let depth = content ? 0 : -1;
  let lastSent = '';
  let lastSeconds = 0;

  function tick(now) {
    if (visible) elapsed += Math.max(0, Math.min(now, activity + 60000) - last);
    last = now;
  }

  function noteActivity(event) {
    if (!event.isTrusted || !visible) return;
    const now = performance.now();
    tick(now);
    activity = now;
    if (event.type === 'scroll' && content) {
      const rect = content.getBoundingClientRect();
      if (rect.height <= innerHeight) return;
      const progress = (innerHeight - rect.top) / rect.height;
      for (const mark of [25, 50, 75, 90]) {
        if (progress >= mark / 100) depth = Math.max(depth, mark);
      }
    }
  }

  function send(closed) {
    tick(performance.now());
    const seconds = Math.min(1800, Math.floor(elapsed / 1000));
    const key = [seconds, depth, closed].join(':');
    if (key === lastSent) return;
    const body = JSON.stringify({action: 'page_engagement', context: {path, view, seconds, depth, closed}});
    if (navigator.sendBeacon('/api/track', new Blob([body], {type: 'application/json'}))) {
      lastSent = key;
      lastSeconds = seconds;
    }
  }

  for (const event of ['scroll', 'pointerdown', 'keydown', 'touchstart']) {
    window.addEventListener(event, noteActivity, {passive: true});
  }
  document.addEventListener('visibilitychange', () => {
    tick(performance.now());
    visible = document.visibilityState === 'visible';
    if (!visible) send(false);
    else activity = last;
  });
  window.addEventListener('pagehide', event => send(!event.persisted));
  window.setInterval(() => {
    tick(performance.now());
    if (visible && Math.floor(elapsed / 1000) - lastSeconds >= 30 && lastSeconds < 1800) send(false);
  }, 30000);
  if (visible) send(false);
})();

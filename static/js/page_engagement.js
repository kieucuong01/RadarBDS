(() => {
  if (window.RadarPageEngagement || navigator.globalPrivacyControl || navigator.doNotTrack === '1'
      || !crypto.getRandomValues || !navigator.sendBeacon) return;
  window.RadarPageEngagement = true;
  const path = location.pathname.replace(/\/$/, '') || '/';
  const randomId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
  const view = randomId();
  const reading = document.querySelector('.article-reading-column, .report-layout, .planning-main > article');
  const content = reading && reading.getBoundingClientRect().height > innerHeight ? reading : null;
  let elapsed = 0;
  let last = performance.now();
  let activity = last;
  let visible = document.visibilityState === 'visible';
  let depth = content ? 0 : -1;
  let lastSent = '';
  let lastSeconds = 0;
  let planningEntrySent = false;
  let session;

  function activeSession() {
    const now = Date.now();
    const storageKey = 'radar_usage_session';
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey));
      if (saved && /^[0-9a-f]{32}$/.test(saved.id) && Number.isFinite(saved.at)
          && saved.at <= now && now - saved.at < 1800000 && saved.id !== session?.id) {
        session = {id: saved.id, at: saved.at, fresh: false};
      } else if (saved?.id === session?.id && saved?.at > session?.at && saved.at <= now) {
        session.at = saved.at;
      }
    } catch (_) {}
    if (!session || now - session.at >= 1800000) session = {id: randomId(), at: now, fresh: true};
    session.at = now;
    try { localStorage.setItem(storageKey, JSON.stringify({id: session.id, at: now})); } catch (_) {}
    return session;
  }

  function opensPlanning(link) {
    const url = new URL(link.href);
    return url.origin === location.origin && url.pathname === '/'
      && url.searchParams.get('map') === '1' && url.searchParams.has('planning');
  }

  const planningEntry = path !== '/' && (document.querySelector('[data-planning-launch-form]')
    || Array.from(document.querySelectorAll('main a[href*="planning="]')).some(opensPlanning));

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

  function send(closed, step) {
    tick(performance.now());
    const seconds = Math.min(1800, Math.floor(elapsed / 1000));
    const key = [seconds, depth, closed].join(':');
    if (!step && key === lastSent) return;
    const active = activeSession();
    const body = JSON.stringify({action: 'page_engagement', context: {
      path, view, seconds, depth, closed, session: active.id, session_start: active.fresh, step
    }});
    if (navigator.sendBeacon('/api/track', new Blob([body], {type: 'application/json'}))) {
      lastSent = key;
      lastSeconds = seconds;
      active.fresh = false;
      if (step === 'planning_entry') planningEntrySent = true;
    }
  }

  function sendEntry() {
    if (planningEntry && !planningEntrySent) send(false, 'planning_entry');
    else send(false);
  }
  window.RadarUsageStep = step => send(false, step);
  document.addEventListener('click', event => {
    const link = event.target.closest?.('a[href*="planning="]');
    if (event.isTrusted && planningEntry && link && opensPlanning(link)) send(false, 'map_click');
  }, true);
  document.addEventListener('submit', event => {
    if (event.isTrusted && event.target.matches('[data-planning-launch-form]')) send(false, 'map_click');
  }, true);
  for (const event of ['scroll', 'pointerdown', 'keydown', 'touchstart']) {
    window.addEventListener(event, noteActivity, {passive: true});
  }
  document.addEventListener('visibilitychange', () => {
    tick(performance.now());
    visible = document.visibilityState === 'visible';
    if (!visible) send(false);
    else {
      activity = last;
      sendEntry();
    }
  });
  window.addEventListener('pagehide', event => send(!event.persisted));
  window.setInterval(() => {
    tick(performance.now());
    if (visible && Math.floor(elapsed / 1000) - lastSeconds >= 30 && lastSeconds < 1800) send(false);
  }, 30000);
  if (visible) sendEntry();
})();

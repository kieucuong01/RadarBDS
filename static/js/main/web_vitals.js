(function initRadarWebVitals(root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarWebVitals = api;
})(typeof window !== 'undefined' ? window : null, function buildWebVitals(root) {
  'use strict';

  const THRESHOLDS = Object.freeze({
    LCP: [2500, 4000],
    INP: [200, 500],
    CLS: [0.1, 0.25],
  });

  function rate(name, value) {
    const thresholds = THRESHOLDS[name];
    if (!thresholds) return 'unknown';
    if (value <= thresholds[0]) return 'good';
    if (value <= thresholds[1]) return 'needs-improvement';
    return 'poor';
  }

  function start() {
    if (!root || typeof root.PerformanceObserver !== 'function' || !root.document) return;
    const values = { LCP: null, INP: null, CLS: 0 };
    const sent = new Set();
    const observe = (type, callback, options = {}) => {
      try {
        const observer = new root.PerformanceObserver((list) => callback(list.getEntries()));
        observer.observe(Object.assign({ type, buffered: true }, options));
      } catch (_) {
        // Unsupported entry types must never interfere with page rendering.
      }
    };

    observe('largest-contentful-paint', (entries) => {
      const latest = entries[entries.length - 1];
      if (latest) values.LCP = latest.startTime;
    });
    observe('layout-shift', (entries) => {
      for (const entry of entries) {
        if (!entry.hadRecentInput) values.CLS += entry.value;
      }
    });
    observe('event', (entries) => {
      for (const entry of entries) {
        if (entry.interactionId && (values.INP === null || entry.duration > values.INP)) {
          values.INP = entry.duration;
        }
      }
    }, { durationThreshold: 40 });

    const emit = () => {
      if (typeof root.gtag !== 'function') return;
      for (const name of Object.keys(values)) {
        const value = values[name];
        if (value === null || sent.has(name)) continue;
        sent.add(name);
        const rounded = name === 'CLS' ? Math.round(value * 1000) / 1000 : Math.round(value);
        root.gtag('event', 'web_vital', {
          metric_name: name,
          metric_value: rounded,
          metric_rating: rate(name, value),
          non_interaction: true,
        });
      }
    };
    root.document.addEventListener('visibilitychange', () => {
      if (root.document.visibilityState === 'hidden') emit();
    });
  }

  start();
  return Object.freeze({ rate });
});

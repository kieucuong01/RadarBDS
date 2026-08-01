(function initRadarFilterRuntime(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarFilterRuntime = api;
})(typeof window !== 'undefined' ? window : globalThis, function buildRuntime() {
  'use strict';

  const MULTI_KEYS = new Set([
    'ward', 'ward[]', 'source', 'source[]', 'prop_type', 'prop_type[]',
    'price_range', 'area_range',
  ]);
  const RANGE_KEYS = new Set(['price_range', 'area_range']);
  const DROP_KEYS = new Set(['sigv']);

  function compareValues(key, left, right) {
    if (!RANGE_KEYS.has(key)) return left.localeCompare(right);
    const bounds = (value) => {
      const [low = '', high = ''] = String(value).split(':', 2);
      return [Number(low || 0), Number(high || 0)];
    };
    const [leftLow, leftHigh] = bounds(left);
    const [rightLow, rightHigh] = bounds(right);
    return leftLow - rightLow || leftHigh - rightHigh || left.localeCompare(right);
  }

  function canonicalize(input) {
    const source = input instanceof URLSearchParams
      ? input
      : new URLSearchParams(String(input || ''));
    const grouped = new Map();
    for (const [rawKey, rawValue] of source.entries()) {
      const key = String(rawKey || '').trim();
      if (!key || DROP_KEYS.has(key)) continue;
      const value = String(rawValue || '').trim();
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(value);
    }

    const output = new URLSearchParams();
    for (const key of Array.from(grouped.keys()).sort()) {
      const values = grouped.get(key);
      const normalized = MULTI_KEYS.has(key)
        ? Array.from(new Set(values.filter(Boolean)))
          .sort((left, right) => compareValues(key, left, right))
        : [values[values.length - 1]];
      for (const value of normalized) output.append(key, value);
    }
    return output.toString();
  }

  async function runSignalFirst(
    loadSignals,
    scheduleCounts,
    shouldSchedule = () => true,
  ) {
    try {
      return await loadSignals();
    } finally {
      if (shouldSchedule()) scheduleCounts();
    }
  }

  return Object.freeze({ canonicalize, runSignalFirst });
});

(function initRadarAreaScope(root, factory) {
  const api = factory(root || {});
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarAreaScope = api;
})(typeof window !== 'undefined' ? window : globalThis, function buildAreaScope(root) {
  'use strict';

  const STORAGE_KEY = 'radar_area_scope_v2';
  const LEGACY_STORAGE_KEY = 'radar_area_scope_v1';
  const VALID_MODES = new Set(['custom', 'preset', 'city_all']);
  const PROP_TYPE_LABELS = Object.freeze({
    dat_nen: '\u0110\u1ea5t',
    nha_dat: 'Nh\u00e0 \u0111\u1ea5t',
    chung_cu: 'Chung c\u01b0',
    nha_tro: 'Nh\u00e0 tr\u1ecd',
  });
  const FILTER_PARAM_KEYS = Object.freeze([
    'price_range',
    'area_range',
    'prop_type',
    'price_min',
    'price_max',
    'area_min',
    'area_max',
  ]);
  let areaScopeDraft = null;
  let areaScopeDraftCity = '';
  let currentScope = null;

  const PRESET_SCOPES = Object.freeze([
    Object.freeze({
      id: 'tdm_tan_an_west',
      city: 'THỦ DẦU MỘT',
      wards: Object.freeze(['Tân An', 'Chánh Mỹ', 'Tương Bình Hiệp', 'Hiệp An']),
      mode: 'preset',
      label: 'Cụm Tân An phía Tây',
    }),
    Object.freeze({
      id: 'tdm_central',
      city: 'THỦ DẦU MỘT',
      wards: Object.freeze(['Phú Cường', 'Phú Thọ', 'Chánh Nghĩa', 'Hiệp Thành']),
      mode: 'preset',
      label: 'Trung tâm Thủ Dầu Một',
    }),
    Object.freeze({
      id: 'tdm_north_industrial',
      city: 'THỦ DẦU MỘT',
      wards: Object.freeze(['Định Hòa', 'Phú Mỹ', 'Phú Tân', 'Hòa Phú']),
      mode: 'preset',
      label: 'Phú Tân - Hòa Phú - Phú Mỹ',
    }),
    Object.freeze({
      id: 'ben_cat_my_phuoc',
      city: 'BẾN CÁT',
      wards: Object.freeze(['Mỹ Phước', 'Mỹ Phước 1', 'Mỹ Phước 2', 'Mỹ Phước 3', 'Mỹ Phước 4', 'Thới Hòa']),
      mode: 'preset',
      label: 'Cụm Mỹ Phước',
    }),
    Object.freeze({
      id: 'ben_cat_outer',
      city: 'BẾN CÁT',
      wards: Object.freeze(['Tân Định', 'Hòa Lợi', 'Chánh Phú Hòa', 'Tân Hưng', 'Lai Hưng']),
      mode: 'preset',
      label: 'Bến Cát ngoài',
    }),
  ]);

  function cityLabel(city) {
    const raw = String(city || '').trim();
    if (raw === 'THỦ DẦU MỘT') return 'Thủ Dầu Một';
    if (raw === 'BẾN CÁT') return 'Bến Cát';
    if (raw === 'DĨ AN') return 'Dĩ An';
    if (raw === 'THUẬN AN') return 'Thuận An';
    if (raw === 'TÂN UYÊN') return 'Tân Uyên';
    return raw;
  }

  function inferCityForWard(ward, wardsByCity) {
    for (const [city, wards] of Object.entries(wardsByCity || {})) {
      if ((wards || []).includes(ward)) return city;
    }
    return '';
  }

  function resolveCity(city, wardsByCity) {
    const raw = String(city || '').trim();
    if (!raw) return '';
    if (Object.prototype.hasOwnProperty.call(wardsByCity || {}, raw)) return raw;
    const folded = raw.toLocaleLowerCase('vi-VN');
    return Object.keys(wardsByCity || {}).find(
      (candidate) => candidate.toLocaleLowerCase('vi-VN') === folded
    ) || '';
  }

  function uniqueValues(values) {
    return Array.from(new Set((values || []).map((value) => String(value || '').trim()).filter(Boolean)));
  }

  function validRangeToken(token) {
    const value = String(token || '').trim();
    return value !== ':' && /^[0-9.]*:[0-9.]*$/.test(value);
  }

  function normalizeNumericFilterValue(value) {
    const raw = String(value || '').trim();
    if (!raw || !/^[0-9.]+$/.test(raw)) return '';
    return raw;
  }

  function normalizeStoredFilters(filters) {
    if (!filters || typeof filters !== 'object') return null;
    if (filters instanceof URLSearchParams) {
      filters = {
        price_range: filters.getAll('price_range'),
        area_range: filters.getAll('area_range'),
        prop_type: filters.getAll('prop_type'),
        price_min: filters.get('price_min'),
        price_max: filters.get('price_max'),
        area_min: filters.get('area_min'),
        area_max: filters.get('area_max'),
      };
    }
    const normalized = {};
    const priceRanges = uniqueValues(filters.price_range).filter(validRangeToken);
    if (priceRanges.length) normalized.price_range = priceRanges;
    const areaRanges = uniqueValues(filters.area_range).filter(validRangeToken);
    if (areaRanges.length) normalized.area_range = areaRanges;

    if (!priceRanges.length) {
      const priceMin = normalizeNumericFilterValue(filters.price_min);
      const priceMax = normalizeNumericFilterValue(filters.price_max);
      if (priceMin) normalized.price_min = priceMin;
      if (priceMax) normalized.price_max = priceMax;
    }
    if (!areaRanges.length) {
      const areaMin = normalizeNumericFilterValue(filters.area_min);
      const areaMax = normalizeNumericFilterValue(filters.area_max);
      if (areaMin) normalized.area_min = areaMin;
      if (areaMax) normalized.area_max = areaMax;
    }

    const propTypes = uniqueValues(filters.prop_type).filter((value) => Object.prototype.hasOwnProperty.call(PROP_TYPE_LABELS, value));
    if (propTypes.length && propTypes.length < Object.keys(PROP_TYPE_LABELS).length) {
      normalized.prop_type = propTypes;
    }
    return Object.keys(normalized).length ? normalized : null;
  }

  function normalizedSelections(candidate, wardsByCity) {
    const rawSelections = candidate && candidate.selections && typeof candidate.selections === 'object'
      ? candidate.selections
      : {};
    const selections = {};
    Object.keys(wardsByCity || {}).forEach((city) => {
      const available = wardsByCity[city] || [];
      const selected = uniqueValues(rawSelections[city]).filter((ward) => available.includes(ward));
      if (selected.length) selections[city] = selected;
    });
    return selections;
  }

  function flattenScopeWards(scope, wardsByCity) {
    if (!scope) return [];
    if (scope.mode === 'city_all' && !Object.keys(scope.selections || {}).length) {
      return Array.from((wardsByCity || {})[scope.activeCity] || []);
    }
    const selections = scope.selections || {};
    const cityOrder = Object.keys(wardsByCity || {});
    const orderedCities = cityOrder.concat(
      Object.keys(selections).filter((city) => !cityOrder.includes(city))
    );
    return uniqueValues(orderedCities.flatMap((city) => selections[city] || []));
  }

  function selectionCounts(scope) {
    const selections = (scope && scope.selections) || {};
    const cityLists = Object.values(selections).filter(
      (wards) => Array.isArray(wards) && wards.length
    );
    return {
      wards: cityLists.reduce((sum, wards) => sum + wards.length, 0),
      cities: cityLists.length,
    };
  }

  function scopeLabel(scope) {
    if (!scope) return '';
    if (scope.mode === 'city_all') {
      const selectedCity = Object.keys(scope.selections || {})[0]
        || scope.activeCity
        || scope.city;
      return `Toàn ${cityLabel(selectedCity)}`;
    }
    if (!scope.selections && uniqueValues(scope.wards).length) {
      return uniqueValues(scope.wards).join(' + ');
    }
    const counts = selectionCounts(scope);
    if (counts.cities > 1) {
      return `${counts.wards} phường · ${counts.cities} thành phố`;
    }
    const selections = scope.selections || {};
    const wards = uniqueValues(Object.values(selections).flat());
    return wards.length ? wards.join(' + ') : 'Chưa chọn phường';
  }

  function validateScope(candidate, wardsByCity) {
    if (!candidate || ![1, 2].includes(Number(candidate.version))) return null;
    const isLegacy = Number(candidate.version) === 1;
    const activeCity = resolveCity(
      isLegacy ? candidate.city : (candidate.activeCity || candidate.city),
      wardsByCity
    );
    if (!activeCity) return null;
    const mode = VALID_MODES.has(candidate.mode) ? candidate.mode : 'custom';
    let selections;
    if (isLegacy) {
      const availableWards = wardsByCity[activeCity] || [];
      const legacyWards = mode === 'city_all'
        ? Array.from(availableWards)
        : uniqueValues(candidate.wards);
      if (legacyWards.some((ward) => !availableWards.includes(ward))) return null;
      selections = legacyWards.length ? { [activeCity]: legacyWards } : {};
    } else {
      selections = normalizedSelections(candidate, wardsByCity);
      const submittedCount = Object.values(candidate.selections || {}).reduce(
        (sum, wards) => sum + uniqueValues(wards).length,
        0
      );
      if (submittedCount !== selectionCounts({ selections }).wards) return null;
    }
    if (isLegacy && mode !== 'city_all' && !selectionCounts({ selections }).wards) return null;
    const normalized = {
      version: 2,
      activeCity,
      selections,
      mode,
    };
    normalized.label = scopeLabel(normalized);
    if (typeof candidate.updatedAt === 'string' && candidate.updatedAt) {
      normalized.updatedAt = candidate.updatedAt;
    }
    const filters = normalizeStoredFilters(candidate.filters);
    if (filters) normalized.filters = filters;
    return normalized;
  }

  function setCurrentScope(scope, wardsByCity) {
    const normalized = validateScope(
      scope,
      wardsByCity || root.INITIAL_WARDS_BY_CITY || {}
    );
    if (!normalized) return null;
    currentScope = normalized;
    return currentScope;
  }

  function getCurrentScope() {
    return currentScope;
  }

  function setActiveScopeCity(city, wardsByCity) {
    const cityMap = wardsByCity || root.INITIAL_WARDS_BY_CITY || {};
    const resolvedCity = resolveCity(city, cityMap);
    if (!resolvedCity) return null;
    if (!currentScope) {
      currentScope = {
        version: 2,
        activeCity: resolvedCity,
        selections: {},
        mode: 'custom',
        label: 'Chưa chọn phường',
      };
      return currentScope;
    }
    currentScope = {
      ...currentScope,
      activeCity: resolvedCity,
    };
    return currentScope;
  }

  function updateCitySelection(city, wards, wardsByCity) {
    const cityMap = wardsByCity || root.INITIAL_WARDS_BY_CITY || {};
    const resolvedCity = resolveCity(city, cityMap);
    if (!resolvedCity) return null;
    const availableWards = cityMap[resolvedCity] || [];
    const selected = uniqueValues(wards).filter((ward) => availableWards.includes(ward));
    if (selected.length !== uniqueValues(wards).length) return null;
    const selections = Object.fromEntries(
      Object.entries((currentScope && currentScope.selections) || {}).map(
        ([key, values]) => [key, Array.from(values)]
      )
    );
    if (selected.length) selections[resolvedCity] = selected;
    else delete selections[resolvedCity];
    const selectedCities = Object.keys(selections).filter((key) => selections[key].length);
    const mode = selectedCities.length === 1
      && selections[selectedCities[0]].length === (cityMap[selectedCities[0]] || []).length
      ? 'city_all'
      : 'custom';
    currentScope = validateScope({
      version: 2,
      activeCity: resolvedCity,
      selections,
      mode,
      filters: currentScope && currentScope.filters,
    }, cityMap);
    return currentScope;
  }

  function commitVisibleCitySelection(doc, wardsByCity) {
    const documentRef = doc || root.document;
    const cityMap = wardsByCity || root.INITIAL_WARDS_BY_CITY || {};
    if (!documentRef) return null;
    const cityInput = documentRef.getElementById('cityInput');
    const city = resolveCity(cityInput ? cityInput.value : '', cityMap);
    if (!city) return null;
    const boxes = Array.from(
      documentRef.querySelectorAll('#wardFilters input[name="ward"]')
    );
    const checked = boxes.filter((box) => box.checked).map((box) => box.value);
    return updateCitySelection(city, checked, cityMap);
  }

  function renderCitySelectionBadges(doc) {
    const documentRef = doc || root.document;
    if (!documentRef || typeof documentRef.querySelectorAll !== 'function') return;
    const scope = currentScope;
    const selections = (scope && scope.selections) || {};
    documentRef.querySelectorAll('[data-city-count]').forEach((badge) => {
      const city = badge.dataset ? badge.dataset.cityCount : '';
      const count = uniqueValues(selections[city]).length;
      badge.textContent = String(count);
      badge.hidden = count === 0;
    });
    const summary = documentRef.getElementById('wardSelectedCount');
    if (summary) {
      const counts = selectionCounts(scope);
      summary.textContent = `${counts.wards} phường · ${counts.cities} thành phố`;
    }
  }

  function filtersFromSearchParams(filterParams) {
    const params = filterParams instanceof URLSearchParams
      ? filterParams
      : new URLSearchParams(String(filterParams || ''));
    return normalizeStoredFilters({
      price_range: params.getAll('price_range'),
      area_range: params.getAll('area_range'),
      prop_type: params.getAll('prop_type'),
      price_min: params.get('price_min'),
      price_max: params.get('price_max'),
      area_min: params.get('area_min'),
      area_max: params.get('area_max'),
    });
  }

  function scopeFromSearchParams(params, wardsByCity) {
    const source = params instanceof URLSearchParams
      ? params
      : new URLSearchParams(String(params || ''));
    const wards = uniqueValues(source.getAll('ward[]').concat(source.getAll('ward')));
    const cityFromQuery = resolveCity(source.get('city'), wardsByCity);
    if (wards.length) {
      const selections = {};
      for (const ward of wards) {
        const city = inferCityForWard(ward, wardsByCity);
        if (!city) return null;
        if (!selections[city]) selections[city] = [];
        selections[city].push(ward);
      }
      return validateScope({
        version: 2,
        activeCity: cityFromQuery || inferCityForWard(wards[0], wardsByCity),
        selections,
        mode: 'custom',
      }, wardsByCity);
    }
    if (cityFromQuery && source.has('city')) {
      return validateScope({
        version: 2,
        activeCity: cityFromQuery,
        selections: { [cityFromQuery]: Array.from(wardsByCity[cityFromQuery] || []) },
        mode: 'city_all',
      }, wardsByCity);
    }
    return null;
  }

  function applyScopeToParams(params, scope, wardsByCity) {
    if (!(params instanceof URLSearchParams) || !scope) return params;
    params.delete('city');
    params.delete('ward');
    params.delete('ward[]');
    params.delete('ward_mode');
    const activeCity = scope.activeCity || scope.city || '';
    if (scope.mode === 'city_all') {
      const selectedCity = Object.keys(scope.selections || {})[0] || activeCity;
      params.set('city', selectedCity);
      return params;
    }
    const selections = scope.selections || (
      activeCity && uniqueValues(scope.wards).length
        ? { [activeCity]: uniqueValues(scope.wards) }
        : {}
    );
    const selectedCities = Object.keys(selections).filter((city) => selections[city].length);
    if (!selectedCities.length) {
      params.set('ward_mode', 'none');
      return params;
    }
    if (selectedCities.length === 1) params.set('city', selectedCities[0]);
    flattenScopeWards({ ...scope, selections }, wardsByCity || root.INITIAL_WARDS_BY_CITY || {})
      .forEach((ward) => params.append('ward', ward));
    return params;
  }

  function appendUniqueParams(params, key, values) {
    uniqueValues(values).forEach((value) => params.append(key, value));
  }

  function applyOptionalFiltersToParams(params, optionalFilters) {
    if (!(params instanceof URLSearchParams)) return params;
    const filters = optionalFilters || {};
    ['price_range', 'area_range', 'prop_type'].forEach((key) => {
      if (!Object.prototype.hasOwnProperty.call(filters, key)) return;
      params.delete(key);
      appendUniqueParams(params, key, filters[key]);
    });
    return params;
  }

  function filtersFromScopeOrFilters(scopeOrFilters) {
    if (!scopeOrFilters) return null;
    return normalizeStoredFilters(scopeOrFilters.filters || scopeOrFilters);
  }

  function applyStoredFiltersToParams(params, scopeOrFilters) {
    if (!(params instanceof URLSearchParams)) return params;
    FILTER_PARAM_KEYS.forEach((key) => params.delete(key));
    const filters = filtersFromScopeOrFilters(scopeOrFilters);
    if (!filters) return params;
    appendUniqueParams(params, 'price_range', filters.price_range);
    appendUniqueParams(params, 'area_range', filters.area_range);
    appendUniqueParams(params, 'prop_type', filters.prop_type);
    ['price_min', 'price_max', 'area_min', 'area_max'].forEach((key) => {
      if (filters[key]) params.set(key, filters[key]);
    });
    return params;
  }

  function rangeTokenFromDataset(dataset) {
    const min = dataset && dataset.min !== undefined ? dataset.min : '';
    const max = dataset && dataset.max !== undefined ? dataset.max : '';
    return `${min}:${max}`;
  }

  function formatRangeLabel(token, unit) {
    const [rawMin, rawMax] = String(token || '').split(':');
    const min = String(rawMin || '').trim();
    const max = String(rawMax || '').trim();
    if (min && max) return `${min} - ${max} ${unit}`;
    if (min) return `> ${min} ${unit}`;
    if (max) return `< ${max} ${unit}`;
    return '';
  }

  function appendManualRange(params, key, minKey, maxKey) {
    const min = String(params.get(minKey) || '').trim();
    const max = String(params.get(maxKey) || '').trim();
    if (min || max) return formatRangeLabel(`${min}:${max}`, key);
    return '';
  }

  function scopeFilterPartsFromParams(filterParams) {
    const params = filterParams instanceof URLSearchParams
      ? filterParams
      : new URLSearchParams(String(filterParams || ''));
    const parts = [];
    const priceRanges = uniqueValues(params.getAll('price_range'));
    const manualPrice = priceRanges.length ? '' : appendManualRange(params, 't\u1ef7', 'price_min', 'price_max');
    const priceLabels = priceRanges.map((token) => formatRangeLabel(token, 't\u1ef7')).filter(Boolean);
    if (manualPrice) priceLabels.push(manualPrice);
    if (priceLabels.length) parts.push({ kind: 'price', label: priceLabels.join(' + ') });

    const areaRanges = uniqueValues(params.getAll('area_range'));
    const manualArea = areaRanges.length ? '' : appendManualRange(params, 'm2', 'area_min', 'area_max');
    const areaLabels = areaRanges.map((token) => formatRangeLabel(token, 'm2')).filter(Boolean);
    if (manualArea) areaLabels.push(manualArea);
    if (areaLabels.length) parts.push({ kind: 'area', label: areaLabels.join(' + ') });

    const propTypes = uniqueValues(params.getAll('prop_type'));
    const propLabels = propTypes.map((value) => PROP_TYPE_LABELS[value] || value).filter(Boolean);
    if (propLabels.length && propLabels.length < Object.keys(PROP_TYPE_LABELS).length) {
      parts.push({ kind: 'type', label: propLabels.join(' + ') });
    }
    return parts;
  }

  function scopeStatusParts(scope, filterParams) {
    const base = scopeLabel(scope);
    const parts = base ? [{ kind: 'location', label: base }] : [];
    return parts.concat(scopeFilterPartsFromParams(filterParams));
  }

  function scopeStatusLabel(scope, filterParams) {
    return scopeStatusParts(scope, filterParams).map((part) => part.label).filter(Boolean).join(' | ');
  }

  function renderScopeStatusChips(container, parts, doc) {
    if (!container) return;
    const visibleParts = (parts || []).filter((part) => part && part.label);
    if (typeof container.replaceChildren === 'function') container.replaceChildren();
    else if (Array.isArray(container.children)) container.children.length = 0;
    container.textContent = '';
    if (!visibleParts.length) return;

    const documentRef = doc || root.document;
    const plainLabel = visibleParts.map((part) => part.label).join(' ');
    if (!documentRef || typeof documentRef.createElement !== 'function' || typeof container.appendChild !== 'function') {
      container.textContent = plainLabel;
      return;
    }
    visibleParts.forEach((part) => {
      const chip = documentRef.createElement('span');
      chip.className = `area-scope-chip area-scope-chip-${part.kind}`;
      chip.textContent = part.label;
      container.appendChild(chip);
    });
    if (typeof container.setAttribute === 'function') container.setAttribute('aria-label', plainLabel);
  }

  function currentFilterParamsFromControls(doc) {
    const documentRef = doc || root.document;
    const params = new URLSearchParams();
    if (!documentRef || typeof documentRef.querySelectorAll !== 'function') return params;
    documentRef.querySelectorAll('.range-chip.active[data-range-kind="price"]').forEach((chip) => {
      const token = rangeTokenFromDataset(chip.dataset);
      if (token !== ':') params.append('price_range', token);
    });
    documentRef.querySelectorAll('.range-chip.active[data-range-kind="area"]').forEach((chip) => {
      const token = rangeTokenFromDataset(chip.dataset);
      if (token !== ':') params.append('area_range', token);
    });
    if (!params.has('price_range')) {
      const minEl = documentRef.getElementById('priceMin');
      const maxEl = documentRef.getElementById('priceMax');
      if (minEl && minEl.value) params.set('price_min', minEl.value);
      if (maxEl && maxEl.value) params.set('price_max', maxEl.value);
    }
    if (!params.has('area_range')) {
      const minEl = documentRef.getElementById('areaMin');
      const maxEl = documentRef.getElementById('areaMax');
      if (minEl && minEl.value) params.set('area_min', minEl.value);
      if (maxEl && maxEl.value) params.set('area_max', maxEl.value);
    }
    const propBoxes = Array.from(documentRef.querySelectorAll('#filterForm input[name="prop_type"]'));
    const checkedProps = propBoxes.filter((box) => box.checked).map((box) => box.value);
    if (checkedProps.length && checkedProps.length < propBoxes.length) {
      checkedProps.forEach((value) => params.append('prop_type', value));
    }
    return params;
  }

  function selectedAreaScopeOptionalFilters(doc) {
    const documentRef = doc || root.document;
    if (!documentRef || typeof documentRef.querySelectorAll !== 'function') return null;
    const selected = { price_range: [], area_range: [], prop_type: [] };
    documentRef.querySelectorAll('.area-scope-option-chip.is-selected').forEach((chip) => {
      const name = chip.dataset ? chip.dataset.filterName : '';
      if (name === 'price_range' || name === 'area_range') {
        selected[name].push(rangeTokenFromDataset(chip.dataset));
      } else if (name === 'prop_type' && chip.dataset && chip.dataset.value) {
        selected.prop_type.push(chip.dataset.value);
      }
    });
    const compact = {};
    Object.entries(selected).forEach(([key, values]) => {
      if (values.length) compact[key] = values;
    });
    return Object.keys(compact).length ? compact : null;
  }

  function setSidebarRangeSelection(kind, tokens, doc) {
    const documentRef = doc || root.document;
    if (!documentRef || !tokens || !tokens.length) return;
    const tokenSet = new Set(tokens);
    documentRef.querySelectorAll(`.range-chip[data-range-kind="${kind}"]`).forEach((chip) => {
      const selected = tokenSet.has(rangeTokenFromDataset(chip.dataset));
      chip.classList.toggle('active', selected);
      chip.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
    const prefix = kind === 'price' ? 'price' : 'area';
    const minEl = documentRef.getElementById(`${prefix}Min`);
    const maxEl = documentRef.getElementById(`${prefix}Max`);
    if (minEl) minEl.value = '';
    if (maxEl) maxEl.value = '';
  }

  function clearSidebarRangeSelection(kind, doc) {
    const documentRef = doc || root.document;
    if (!documentRef || typeof documentRef.querySelectorAll !== 'function') return;
    documentRef.querySelectorAll(`.range-chip[data-range-kind="${kind}"]`).forEach((chip) => {
      chip.classList.remove('active');
      chip.setAttribute('aria-pressed', 'false');
    });
  }

  function setManualRangeSelection(kind, min, max, doc) {
    const documentRef = doc || root.document;
    if (!documentRef) return;
    clearSidebarRangeSelection(kind, documentRef);
    const prefix = kind === 'price' ? 'price' : 'area';
    const minEl = documentRef.getElementById(`${prefix}Min`);
    const maxEl = documentRef.getElementById(`${prefix}Max`);
    if (minEl) minEl.value = min || '';
    if (maxEl) maxEl.value = max || '';
  }

  function syncStoredFiltersControls(scopeOrFilters, doc) {
    const documentRef = doc || root.document;
    const filters = filtersFromScopeOrFilters(scopeOrFilters);
    if (!filters || !documentRef || typeof documentRef.querySelectorAll !== 'function') return null;
    if (filters.price_range) setSidebarRangeSelection('price', filters.price_range, documentRef);
    else if (filters.price_min || filters.price_max) setManualRangeSelection('price', filters.price_min || '', filters.price_max || '', documentRef);
    if (filters.area_range) setSidebarRangeSelection('area', filters.area_range, documentRef);
    else if (filters.area_min || filters.area_max) setManualRangeSelection('area', filters.area_min || '', filters.area_max || '', documentRef);
    if (filters.prop_type) {
      const allowed = new Set(filters.prop_type);
      documentRef.querySelectorAll('#filterForm input[name="prop_type"]').forEach((box) => {
        box.checked = allowed.has(box.value);
      });
    }
    return filters;
  }

  function syncAreaScopeOptionalFilters(doc) {
    const documentRef = doc || root.document;
    const selected = selectedAreaScopeOptionalFilters(documentRef);
    if (!selected) return null;
    if ((selected.price_range || []).length) setSidebarRangeSelection('price', selected.price_range, documentRef);
    if ((selected.area_range || []).length) setSidebarRangeSelection('area', selected.area_range, documentRef);
    if ((selected.prop_type || []).length && documentRef && typeof documentRef.querySelectorAll === 'function') {
      const allowed = new Set(uniqueValues(selected.prop_type));
      documentRef.querySelectorAll('#filterForm input[name="prop_type"]').forEach((box) => {
        box.checked = allowed.has(box.value);
      });
    }
    return selected;
  }

  function readStoredScope(storage, wardsByCity) {
    try {
      const raw = storage.getItem(STORAGE_KEY);
      if (raw) {
        const current = validateScope(JSON.parse(raw), wardsByCity);
        if (current) return current;
      }
      const legacyRaw = storage.getItem(LEGACY_STORAGE_KEY);
      if (!legacyRaw) return null;
      return validateScope(JSON.parse(legacyRaw), wardsByCity);
    } catch (err) {
      return null;
    }
  }

  function saveScope(scope, storage, filters) {
    const target = storage || root.localStorage;
    if (!target || !scope) return null;
    const normalizedFilters = normalizeStoredFilters(filters);
    const normalizedScope = Number(scope.version) === 2 ? scope : {
      version: 2,
      activeCity: scope.city,
      selections: scope.mode === 'city_all'
        ? { [scope.city]: Array.from((root.INITIAL_WARDS_BY_CITY || {})[scope.city] || []) }
        : { [scope.city]: uniqueValues(scope.wards) },
      mode: scope.mode,
    };
    const payload = {
      version: 2,
      activeCity: normalizedScope.activeCity,
      selections: normalizedScope.selections,
      mode: normalizedScope.mode,
      label: scopeLabel(normalizedScope),
      updatedAt: new Date().toISOString(),
    };
    if (normalizedFilters) payload.filters = normalizedFilters;
    try {
      target.setItem(STORAGE_KEY, JSON.stringify(payload));
      return payload;
    } catch (err) {
      return null;
    }
  }

  function clearStoredScope(storage) {
    const target = storage || root.localStorage;
    try {
      if (target) {
        target.removeItem(STORAGE_KEY);
        target.removeItem(LEGACY_STORAGE_KEY);
      }
    } catch (err) {}
  }

  function selectedScopeFromControls(doc, wardsByCity) {
    const documentRef = doc || root.document;
    if (!documentRef) return null;
    const cityInput = documentRef.getElementById('cityInput');
    const city = resolveCity(cityInput ? cityInput.value : '', wardsByCity);
    if (!city) return null;
    if (currentScope) return currentScope;
    const boxes = Array.from(documentRef.querySelectorAll('#wardFilters input[name="ward"]'));
    const checked = boxes.filter((box) => box.checked).map((box) => box.value);
    if (!checked.length) return null;
    const mode = checked.length === boxes.length ? 'city_all' : 'custom';
    return validateScope({
      version: 2,
      activeCity: city,
      selections: { [city]: checked },
      mode,
    }, wardsByCity);
  }

  function nextDraftWardScope(current, city, ward, wardsByCity) {
    const resolvedCity = resolveCity(city, wardsByCity);
    const selectedWard = String(ward || '').trim();
    if (!resolvedCity || !selectedWard || !(wardsByCity[resolvedCity] || []).includes(selectedWard)) return null;
    const base = validateScope(current, wardsByCity);
    const selections = base && base.mode !== 'city_all'
      ? Object.fromEntries(Object.entries(base.selections).map(([key, wards]) => [key, Array.from(wards)]))
      : {};
    const currentWards = uniqueValues(selections[resolvedCity]);
    const nextWards = currentWards.includes(selectedWard)
      ? currentWards.filter((item) => item !== selectedWard)
      : currentWards.concat(selectedWard);
    if (nextWards.length) selections[resolvedCity] = nextWards;
    else delete selections[resolvedCity];
    if (!Object.keys(selections).length) return null;
    return validateScope({
      version: 2,
      activeCity: resolvedCity,
      selections,
      mode: 'custom',
    }, wardsByCity);
  }

  function setAreaScopeDraft(scope, doc) {
    const normalized = validateScope(scope, root.INITIAL_WARDS_BY_CITY || {});
    areaScopeDraft = normalized;
    areaScopeDraftCity = normalized ? normalized.activeCity : '';
    renderAreaScopeDraft(doc || root.document);
    return areaScopeDraft;
  }

  function renderAreaScopeDraft(doc) {
    const documentRef = doc || root.document;
    if (!documentRef || typeof documentRef.querySelectorAll !== 'function') return;
    const selectedCity = areaScopeDraftCity || (areaScopeDraft && areaScopeDraft.activeCity) || '';
    const selections = (areaScopeDraft && areaScopeDraft.selections) || {};
    documentRef.querySelectorAll('.area-scope-city-tab').forEach((tab) => {
      const tabCity = tab.dataset ? tab.dataset.city : '';
      tab.classList.toggle('is-active', Boolean(selectedCity && tabCity === selectedCity));
      tab.setAttribute('aria-pressed', selectedCity && tabCity === selectedCity ? 'true' : 'false');
    });
    documentRef.querySelectorAll('.area-scope-city-group').forEach((group) => {
      const groupCity = group.dataset ? group.dataset.areaScopeCity : '';
      const active = Boolean(selectedCity && groupCity === selectedCity);
      group.hidden = !active;
      group.classList.toggle('is-active', active);
    });
    documentRef.querySelectorAll('.area-scope-ward-chip').forEach((chip) => {
      const chipCity = chip.dataset ? chip.dataset.city : '';
      const chipWard = chip.dataset ? chip.dataset.ward : '';
      const selected = Boolean((selections[chipCity] || []).includes(chipWard));
      chip.classList.toggle('is-selected', selected);
      chip.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
    const applyBtn = documentRef.getElementById('areaScopeApplySelection');
    if (applyBtn) {
      const enabled = Boolean(areaScopeDraft && selectionCounts(areaScopeDraft).wards);
      applyBtn.disabled = !enabled;
      applyBtn.textContent = enabled ? `Áp dụng: ${scopeLabel(areaScopeDraft)}` : 'Áp dụng khu vực';
    }
  }

  function setCityControls(scope, doc) {
    const documentRef = doc || root.document;
    if (!documentRef || !scope) return;
    const cityInput = documentRef.getElementById('cityInput');
    const activeCity = scope.activeCity || scope.city;
    if (cityInput) cityInput.value = activeCity;
    documentRef.querySelectorAll('.city-pill').forEach((btn) => {
      const active = btn.dataset.city === activeCity;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function syncScopeControls(scope, wardsByCity, doc, updateWardFilters) {
    const documentRef = doc || root.document;
    if (!documentRef || !scope) return;
    const normalized = setCurrentScope(scope, wardsByCity);
    if (!normalized) return;
    setCityControls(normalized, documentRef);
    const selectedWards = normalized.selections[normalized.activeCity] || [];
    if (typeof updateWardFilters === 'function') {
      updateWardFilters(wardsByCity, selectedWards, { preserveScroll: false, preserveSearch: false });
    }
    renderCitySelectionBadges(documentRef);
    setAreaScopeDraft(normalized, documentRef);
  }

  function updateScopeUi(scope, doc) {
    const documentRef = doc || root.document;
    if (!documentRef) return;
    const chooser = documentRef.getElementById('areaScopeChooser');
    const bar = documentRef.getElementById('areaScopeBar');
    const label = documentRef.getElementById('areaScopeLabel');
    if (label) {
      const parts = scope ? scopeStatusParts(scope, currentFilterParamsFromControls(documentRef)) : [];
      renderScopeStatusChips(label, parts, documentRef);
    }
    if (bar) bar.hidden = !scope;
    if (chooser) chooser.hidden = Boolean(scope);
    if (documentRef.body) {
      documentRef.body.classList.toggle('area-scope-modal-open', !scope && chooser && !chooser.hidden);
    }
  }

  function refreshCurrentScopeUi(doc) {
    const documentRef = doc || root.document;
    const scope = selectedScopeFromControls(documentRef, root.INITIAL_WARDS_BY_CITY || {});
    if (scope) updateScopeUi(scope, documentRef);
    return scope;
  }

  function hideChooser(doc) {
    const documentRef = doc || root.document;
    if (!documentRef) return;
    const chooser = documentRef.getElementById('areaScopeChooser');
    if (chooser) chooser.hidden = true;
    if (documentRef.body) documentRef.body.classList.remove('area-scope-modal-open');
  }

  function showChooser(doc) {
    const documentRef = doc || root.document;
    if (!documentRef) return;
    const chooser = documentRef.getElementById('areaScopeChooser');
    const bar = documentRef.getElementById('areaScopeBar');
    const draft = currentScope || selectedScopeFromControls(documentRef, root.INITIAL_WARDS_BY_CITY || {});
    const label = documentRef.getElementById('areaScopeLabel');
    const hasSavedScopeLabel = Boolean(label && String(label.textContent || '').trim());
    areaScopeDraft = draft || null;
    areaScopeDraftCity = draft && (draft.mode !== 'city_all' || hasSavedScopeLabel)
      ? draft.activeCity
      : '';
    if (chooser) {
      chooser.hidden = false;
      if (documentRef.body) documentRef.body.classList.add('area-scope-modal-open');
      renderAreaScopeDraft(documentRef);
      const focusTarget = chooser.querySelector('.area-scope-city-tab, .area-scope-city-all, .area-scope-ward-chip, .area-scope-filter');
      if (focusTarget && typeof focusTarget.focus === 'function') focusTarget.focus();
    }
    if (bar) bar.hidden = true;
  }

  function defaultDismissedScope(doc) {
    const documentRef = doc || root.document;
    const wardsByCity = root.INITIAL_WARDS_BY_CITY || {};
    const selected = currentScope || selectedScopeFromControls(documentRef, wardsByCity);
    if (selected) return selected;
    const defaultCity = resolveCity('THỦ DẦU MỘT', wardsByCity) || Object.keys(wardsByCity)[0] || '';
    if (!defaultCity) return null;
    return validateScope({
      version: 2,
      activeCity: defaultCity,
      selections: { [defaultCity]: Array.from(wardsByCity[defaultCity] || []) },
      mode: 'city_all',
    }, wardsByCity);
  }

  function replaceUrlWithScope(scope, optionalFilters) {
    if (!root.location || !root.history || !scope) return;
    const params = new URLSearchParams(root.location.search || '');
    params.set('tab', 'signals');
    applyScopeToParams(params, scope, root.INITIAL_WARDS_BY_CITY || {});
    if (optionalFilters) applyOptionalFiltersToParams(params, optionalFilters);
    else if (scope.filters) applyStoredFiltersToParams(params, scope);
    const nextUrl = `${root.location.pathname || '/'}?${params.toString()}${root.location.hash || ''}`;
    root.history.replaceState(null, '', nextUrl);
  }

  function applyDashboardScope(scope, options) {
    const opts = options || {};
    const wardsByCity = root.INITIAL_WARDS_BY_CITY || {};
    const normalized = validateScope(scope, wardsByCity);
    if (!normalized) return null;
    currentScope = normalized;
    syncScopeControls(normalized, wardsByCity, root.document, root.updateWardFilters);
    updateScopeUi(normalized, root.document);
    const filtersToPersist = opts.optionalFilters || opts.filters || currentFilterParamsFromControls(root.document);
    if (opts.persist !== false) saveScope(normalized, root.localStorage, filtersToPersist);
    if (opts.updateUrl !== false) {
      const urlScope = Object.assign({}, normalized);
      const storedFilters = normalizeStoredFilters(filtersToPersist);
      if (storedFilters) urlScope.filters = storedFilters;
      replaceUrlWithScope(urlScope, opts.optionalFilters || null);
    }
    if (opts.apply !== false && typeof root.applyFilters === 'function') root.applyFilters();
    return normalized;
  }

  function presetById(id) {
    const preset = PRESET_SCOPES.find((item) => item.id === id);
    if (!preset) return null;
    return {
      version: 2,
      activeCity: preset.city,
      selections: { [preset.city]: Array.from(preset.wards) },
      mode: preset.mode,
      label: preset.label,
    };
  }

  root.selectAreaPreset = function selectAreaPreset(id) {
    return applyDashboardScope(presetById(id), { persist: true, updateUrl: true, apply: true });
  };

  root.selectCurrentCityAllAreaScope = function selectCurrentCityAllAreaScope() {
    const doc = root.document;
    const cityInput = doc && doc.getElementById('cityInput');
    const city = resolveCity(cityInput ? cityInput.value : 'THỦ DẦU MỘT', root.INITIAL_WARDS_BY_CITY || {});
    return applyDashboardScope({
      version: 2,
      activeCity: city || 'THỦ DẦU MỘT',
      selections: {
        [city || 'THỦ DẦU MỘT']: Array.from(
          (root.INITIAL_WARDS_BY_CITY || {})[city || 'THỦ DẦU MỘT'] || []
        ),
      },
      mode: 'city_all',
    }, { persist: true, updateUrl: true, apply: true });
  };

  root.selectAreaCityAll = function selectAreaCityAll(city) {
    const resolvedCity = resolveCity(city, root.INITIAL_WARDS_BY_CITY || {});
    if (!resolvedCity) return null;
    const optionalFilters = syncAreaScopeOptionalFilters(root.document);
    return applyDashboardScope({
      version: 2,
      activeCity: resolvedCity,
      selections: {
        [resolvedCity]: Array.from((root.INITIAL_WARDS_BY_CITY || {})[resolvedCity] || []),
      },
      mode: 'city_all',
    }, { persist: true, updateUrl: true, apply: true, optionalFilters });
  };

  root.selectAreaScopeCity = function selectAreaScopeCity(city) {
    const resolvedCity = resolveCity(city, root.INITIAL_WARDS_BY_CITY || {});
    if (!resolvedCity) return null;
    areaScopeDraftCity = resolvedCity;
    if (areaScopeDraft) areaScopeDraft = { ...areaScopeDraft, activeCity: resolvedCity };
    renderAreaScopeDraft(root.document);
    return areaScopeDraft;
  };

  root.toggleAreaScopeWard = function toggleAreaScopeWard(button) {
    if (!button || !button.dataset) return null;
    areaScopeDraftCity = resolveCity(button.dataset.city, root.INITIAL_WARDS_BY_CITY || {});
    areaScopeDraft = nextDraftWardScope(
      areaScopeDraft,
      button.dataset.city,
      button.dataset.ward,
      root.INITIAL_WARDS_BY_CITY || {}
    );
    renderAreaScopeDraft(root.document);
    return areaScopeDraft;
  };

  root.applyAreaScopeWardSelection = function applyAreaScopeWardSelection() {
    if (!areaScopeDraft) return null;
    const optionalFilters = syncAreaScopeOptionalFilters(root.document);
    return applyDashboardScope(areaScopeDraft, { persist: true, updateUrl: true, apply: true, optionalFilters });
  };

  root.toggleAreaScopeOptionalChip = function toggleAreaScopeOptionalChip(button) {
    if (!button) return null;
    button.classList.toggle('is-selected');
    button.setAttribute('aria-pressed', button.classList.contains('is-selected') ? 'true' : 'false');
    return selectedAreaScopeOptionalFilters(root.document);
  };

  root.clearAreaScopeOptionalFilters = function clearAreaScopeOptionalFilters() {
    const doc = root.document;
    if (!doc || typeof doc.querySelectorAll !== 'function') return;
    doc.querySelectorAll('.area-scope-option-chip.is-selected').forEach((chip) => {
      chip.classList.remove('is-selected');
      chip.setAttribute('aria-pressed', 'false');
    });
  };

  root.openAreaScopeChooser = function openAreaScopeChooser() {
    showChooser(root.document);
  };

  root.closeAreaScopeChooser = function closeAreaScopeChooser() {
    const scope = defaultDismissedScope(root.document);
    if (!scope) {
      hideChooser(root.document);
      return null;
    }
    if (typeof root.applyFilters === 'function') root.RADAR_AREA_SCOPE_SKIP_PERSIST_ONCE = true;
    return applyDashboardScope(scope, { persist: false, updateUrl: false, apply: true });
  };

  root.openAreaScopeFilterSheet = function openAreaScopeFilterSheet() {
    hideChooser(root.document);
    const sidebar = root.document && root.document.getElementById('sidebar');
    if (sidebar && Number(root.innerWidth || 0) > 1024) {
      sidebar.classList.remove('collapsed');
    } else if (sidebar && !sidebar.classList.contains('show') && typeof root.toggleMenu === 'function') {
      root.toggleMenu();
    }
    const wardSearch = root.document && root.document.getElementById('wardSearch');
    if (wardSearch && typeof wardSearch.focus === 'function') wardSearch.focus();
  };

  root.persistCurrentAreaScope = function persistCurrentAreaScope(options) {
    const scope = selectedScopeFromControls(root.document, root.INITIAL_WARDS_BY_CITY || {});
    if (!scope) return null;
    updateScopeUi(scope, root.document);
    const filters = currentFilterParamsFromControls(root.document);
    const storedFilters = normalizeStoredFilters(filters);
    saveScope(scope, root.localStorage, storedFilters);
    if (options && options.updateUrl) {
      const urlScope = Object.assign({}, scope);
      if (storedFilters) urlScope.filters = storedFilters;
      replaceUrlWithScope(urlScope);
    }
    return scope;
  };

  root.refreshCurrentScopeUi = function refreshCurrentScopeUiFromControls() {
    return refreshCurrentScopeUi(root.document);
  };

  return Object.freeze({
    STORAGE_KEY,
    LEGACY_STORAGE_KEY,
    PRESET_SCOPES,
    applyDashboardScope,
    applyOptionalFiltersToParams,
    applyStoredFiltersToParams,
    applyScopeToParams,
    clearStoredScope,
    commitVisibleCitySelection,
    filtersFromSearchParams,
    flattenScopeWards,
    getCurrentScope,
    hideChooser,
    renderAreaScopeDraft,
    nextDraftWardScope,
    readStoredScope,
    renderCitySelectionBadges,
    replaceUrlWithScope,
    saveScope,
    selectionCounts,
    setActiveScopeCity,
    setCurrentScope,
    scopeFromSearchParams,
    scopeStatusLabel,
    scopeStatusParts,
    scopeLabel,
    selectedScopeFromControls,
    showChooser,
    renderScopeStatusChips,
    refreshCurrentScopeUi,
    syncStoredFiltersControls,
    syncAreaScopeOptionalFilters,
    syncScopeControls,
    updateScopeUi,
    updateCitySelection,
    validateScope,
  });
});

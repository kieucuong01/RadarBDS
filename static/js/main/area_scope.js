(function initRadarAreaScope(root, factory) {
  const api = factory(root || {});
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarAreaScope = api;
})(typeof window !== 'undefined' ? window : globalThis, function buildAreaScope(root) {
  'use strict';

  const STORAGE_KEY = 'radar_area_scope_v1';
  const VALID_MODES = new Set(['custom', 'preset', 'city_all']);
  const PROP_TYPE_LABELS = Object.freeze({
    dat_nen: '\u0110\u1ea5t',
    nha_dat: 'Nh\u00e0 \u0111\u1ea5t',
    chung_cu: 'Chung c\u01b0',
    nha_tro: 'Nh\u00e0 tr\u1ecd',
  });
  let areaScopeDraft = null;
  let areaScopeDraftCity = '';

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

  function scopeLabel(scope) {
    if (!scope) return '';
    if (scope.mode === 'city_all') return `Toàn ${cityLabel(scope.city)}`;
    const wards = uniqueValues(scope.wards);
    return wards.length ? wards.join(' + ') : `Toàn ${cityLabel(scope.city)}`;
  }

  function validateScope(candidate, wardsByCity) {
    if (!candidate || Number(candidate.version) !== 1) return null;
    const city = resolveCity(candidate.city, wardsByCity);
    if (!city) return null;
    const mode = VALID_MODES.has(candidate.mode) ? candidate.mode : 'custom';
    const availableWards = wardsByCity[city] || [];
    const wards = mode === 'city_all' ? [] : uniqueValues(candidate.wards);
    if (mode !== 'city_all') {
      if (!wards.length) return null;
      if (wards.some((ward) => !availableWards.includes(ward))) return null;
    }
    const normalized = {
      version: 1,
      city,
      wards,
      mode,
      label: scopeLabel({ city, wards, mode }),
    };
    if (typeof candidate.updatedAt === 'string' && candidate.updatedAt) {
      normalized.updatedAt = candidate.updatedAt;
    }
    return normalized;
  }

  function scopeFromSearchParams(params, wardsByCity) {
    const source = params instanceof URLSearchParams
      ? params
      : new URLSearchParams(String(params || ''));
    const wards = uniqueValues(source.getAll('ward[]').concat(source.getAll('ward')));
    const cityFromQuery = resolveCity(source.get('city'), wardsByCity);
    if (wards.length) {
      const city = cityFromQuery || inferCityForWard(wards[0], wardsByCity);
      return validateScope({ version: 1, city, wards, mode: 'custom' }, wardsByCity);
    }
    if (cityFromQuery && source.has('city')) {
      return validateScope({ version: 1, city: cityFromQuery, wards: [], mode: 'city_all' }, wardsByCity);
    }
    return null;
  }

  function applyScopeToParams(params, scope) {
    if (!(params instanceof URLSearchParams) || !scope) return params;
    params.delete('city');
    params.delete('ward');
    params.delete('ward[]');
    params.delete('ward_mode');
    params.set('city', scope.city);
    if (scope.mode !== 'city_all') {
      uniqueValues(scope.wards).forEach((ward) => params.append('ward', ward));
    }
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
    if (priceLabels.length) parts.push(`Gi\u00e1: ${priceLabels.join(' + ')}`);

    const areaRanges = uniqueValues(params.getAll('area_range'));
    const manualArea = areaRanges.length ? '' : appendManualRange(params, 'm2', 'area_min', 'area_max');
    const areaLabels = areaRanges.map((token) => formatRangeLabel(token, 'm2')).filter(Boolean);
    if (manualArea) areaLabels.push(manualArea);
    if (areaLabels.length) parts.push(`Di\u1ec7n t\u00edch: ${areaLabels.join(' + ')}`);

    const propTypes = uniqueValues(params.getAll('prop_type'));
    const propLabels = propTypes.map((value) => PROP_TYPE_LABELS[value] || value).filter(Boolean);
    if (propLabels.length && propLabels.length < Object.keys(PROP_TYPE_LABELS).length) {
      parts.push(`Lo\u1ea1i h\u00ecnh: ${propLabels.join(' + ')}`);
    }
    return parts;
  }

  function scopeStatusLabel(scope, filterParams) {
    const base = scopeLabel(scope);
    const filterParts = scopeFilterPartsFromParams(filterParams);
    return [base].concat(filterParts).filter(Boolean).join(' | ');
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
      if (!raw) return null;
      return validateScope(JSON.parse(raw), wardsByCity);
    } catch (err) {
      return null;
    }
  }

  function saveScope(scope, storage) {
    const target = storage || root.localStorage;
    if (!target || !scope) return null;
    const payload = {
      version: 1,
      city: scope.city,
      wards: scope.mode === 'city_all' ? [] : uniqueValues(scope.wards),
      mode: scope.mode,
      label: scopeLabel(scope),
      updatedAt: new Date().toISOString(),
    };
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
      if (target) target.removeItem(STORAGE_KEY);
    } catch (err) {}
  }

  function selectedScopeFromControls(doc, wardsByCity) {
    const documentRef = doc || root.document;
    if (!documentRef) return null;
    const cityInput = documentRef.getElementById('cityInput');
    const city = resolveCity(cityInput ? cityInput.value : '', wardsByCity);
    if (!city) return null;
    const boxes = Array.from(documentRef.querySelectorAll('#wardFilters input[name="ward"]'));
    const checked = boxes.filter((box) => box.checked).map((box) => box.value);
    if (!checked.length) return null;
    const mode = checked.length === boxes.length ? 'city_all' : 'custom';
    return validateScope({ version: 1, city, wards: checked, mode }, wardsByCity);
  }

  function nextDraftWardScope(current, city, ward, wardsByCity) {
    const resolvedCity = resolveCity(city, wardsByCity);
    const selectedWard = String(ward || '').trim();
    if (!resolvedCity || !selectedWard || !(wardsByCity[resolvedCity] || []).includes(selectedWard)) return null;
    const base = validateScope(current, wardsByCity);
    const currentWards = base && base.city === resolvedCity && base.mode !== 'city_all'
      ? uniqueValues(base.wards)
      : [];
    const nextWards = currentWards.includes(selectedWard)
      ? currentWards.filter((item) => item !== selectedWard)
      : currentWards.concat(selectedWard);
    if (!nextWards.length) return null;
    return validateScope({
      version: 1,
      city: resolvedCity,
      wards: nextWards,
      mode: 'custom',
    }, wardsByCity);
  }

  function setAreaScopeDraft(scope, doc) {
    const normalized = validateScope(scope, root.INITIAL_WARDS_BY_CITY || {});
    areaScopeDraft = normalized && normalized.mode !== 'city_all' ? normalized : null;
    areaScopeDraftCity = normalized ? normalized.city : '';
    renderAreaScopeDraft(doc || root.document);
    return areaScopeDraft;
  }

  function renderAreaScopeDraft(doc) {
    const documentRef = doc || root.document;
    if (!documentRef || typeof documentRef.querySelectorAll !== 'function') return;
    const selectedCity = areaScopeDraftCity || (areaScopeDraft && areaScopeDraft.city) || '';
    const selectedWards = new Set(areaScopeDraft && areaScopeDraft.mode !== 'city_all' ? areaScopeDraft.wards : []);
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
      const selected = Boolean(selectedCity && chipCity === selectedCity && selectedWards.has(chipWard));
      chip.classList.toggle('is-selected', selected);
      chip.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
    const applyBtn = documentRef.getElementById('areaScopeApplySelection');
    if (applyBtn) {
      const enabled = Boolean(areaScopeDraft && areaScopeDraft.mode !== 'city_all' && areaScopeDraft.wards.length);
      applyBtn.disabled = !enabled;
      applyBtn.textContent = enabled ? `Áp dụng: ${scopeLabel(areaScopeDraft)}` : 'Áp dụng khu vực';
    }
  }

  function setCityControls(scope, doc) {
    const documentRef = doc || root.document;
    if (!documentRef || !scope) return;
    const cityInput = documentRef.getElementById('cityInput');
    if (cityInput) cityInput.value = scope.city;
    documentRef.querySelectorAll('.city-pill').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.city === scope.city);
    });
  }

  function syncScopeControls(scope, wardsByCity, doc, updateWardFilters) {
    const documentRef = doc || root.document;
    if (!documentRef || !scope) return;
    setCityControls(scope, documentRef);
    const selectedWards = scope.mode === 'city_all' ? [] : scope.wards;
    if (typeof updateWardFilters === 'function') {
      updateWardFilters(wardsByCity, selectedWards, { preserveScroll: false, preserveSearch: false });
    }
    setAreaScopeDraft(scope, documentRef);
  }

  function updateScopeUi(scope, doc) {
    const documentRef = doc || root.document;
    if (!documentRef) return;
    const chooser = documentRef.getElementById('areaScopeChooser');
    const bar = documentRef.getElementById('areaScopeBar');
    const label = documentRef.getElementById('areaScopeLabel');
    if (label) label.textContent = scope ? scopeStatusLabel(scope, currentFilterParamsFromControls(documentRef)) : '';
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
    const draft = selectedScopeFromControls(documentRef, root.INITIAL_WARDS_BY_CITY || {});
    const label = documentRef.getElementById('areaScopeLabel');
    const hasSavedScopeLabel = Boolean(label && String(label.textContent || '').trim());
    areaScopeDraft = draft && draft.mode !== 'city_all' ? draft : null;
    areaScopeDraftCity = draft && (draft.mode !== 'city_all' || hasSavedScopeLabel) ? draft.city : '';
    if (chooser) {
      chooser.hidden = false;
      if (documentRef.body) documentRef.body.classList.add('area-scope-modal-open');
      renderAreaScopeDraft(documentRef);
      const focusTarget = chooser.querySelector('.area-scope-city-tab, .area-scope-city-all, .area-scope-ward-chip, .area-scope-filter');
      if (focusTarget && typeof focusTarget.focus === 'function') focusTarget.focus();
    }
    if (bar) bar.hidden = true;
  }

  function replaceUrlWithScope(scope, optionalFilters) {
    if (!root.location || !root.history || !scope) return;
    const params = new URLSearchParams(root.location.search || '');
    params.set('tab', 'signals');
    applyScopeToParams(params, scope);
    if (optionalFilters) applyOptionalFiltersToParams(params, optionalFilters);
    const nextUrl = `${root.location.pathname || '/'}?${params.toString()}${root.location.hash || ''}`;
    root.history.replaceState(null, '', nextUrl);
  }

  function applyDashboardScope(scope, options) {
    const opts = options || {};
    const wardsByCity = root.INITIAL_WARDS_BY_CITY || {};
    const normalized = validateScope(scope, wardsByCity);
    if (!normalized) return null;
    syncScopeControls(normalized, wardsByCity, root.document, root.updateWardFilters);
    updateScopeUi(normalized, root.document);
    if (opts.persist !== false) saveScope(normalized, root.localStorage);
    if (opts.updateUrl !== false) replaceUrlWithScope(normalized, opts.optionalFilters || null);
    if (opts.apply !== false && typeof root.applyFilters === 'function') root.applyFilters();
    return normalized;
  }

  function presetById(id) {
    const preset = PRESET_SCOPES.find((item) => item.id === id);
    if (!preset) return null;
    return {
      version: 1,
      city: preset.city,
      wards: Array.from(preset.wards),
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
      version: 1,
      city: city || 'THỦ DẦU MỘT',
      wards: [],
      mode: 'city_all',
    }, { persist: true, updateUrl: true, apply: true });
  };

  root.selectAreaCityAll = function selectAreaCityAll(city) {
    const resolvedCity = resolveCity(city, root.INITIAL_WARDS_BY_CITY || {});
    if (!resolvedCity) return null;
    const optionalFilters = syncAreaScopeOptionalFilters(root.document);
    return applyDashboardScope({
      version: 1,
      city: resolvedCity,
      wards: [],
      mode: 'city_all',
    }, { persist: true, updateUrl: true, apply: true, optionalFilters });
  };

  root.selectAreaScopeCity = function selectAreaScopeCity(city) {
    const resolvedCity = resolveCity(city, root.INITIAL_WARDS_BY_CITY || {});
    if (!resolvedCity) return null;
    areaScopeDraftCity = resolvedCity;
    if (!areaScopeDraft || areaScopeDraft.city !== resolvedCity) areaScopeDraft = null;
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
    hideChooser(root.document);
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
    saveScope(scope, root.localStorage);
    if (options && options.updateUrl) replaceUrlWithScope(scope);
    return scope;
  };

  root.refreshCurrentScopeUi = function refreshCurrentScopeUiFromControls() {
    return refreshCurrentScopeUi(root.document);
  };

  return Object.freeze({
    STORAGE_KEY,
    PRESET_SCOPES,
    applyDashboardScope,
    applyOptionalFiltersToParams,
    applyScopeToParams,
    clearStoredScope,
    hideChooser,
    renderAreaScopeDraft,
    nextDraftWardScope,
    readStoredScope,
    replaceUrlWithScope,
    saveScope,
    scopeFromSearchParams,
    scopeStatusLabel,
    scopeLabel,
    selectedScopeFromControls,
    showChooser,
    refreshCurrentScopeUi,
    syncAreaScopeOptionalFilters,
    syncScopeControls,
    updateScopeUi,
    validateScope,
  });
});

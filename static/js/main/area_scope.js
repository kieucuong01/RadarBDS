(function initRadarAreaScope(root, factory) {
  const api = factory(root || {});
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarAreaScope = api;
})(typeof window !== 'undefined' ? window : globalThis, function buildAreaScope(root) {
  'use strict';

  const STORAGE_KEY = 'radar_area_scope_v1';
  const VALID_MODES = new Set(['custom', 'preset', 'city_all']);
  let areaScopeDraft = null;

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
    areaScopeDraft = validateScope(scope, root.INITIAL_WARDS_BY_CITY || {});
    renderAreaScopeDraft(doc || root.document);
    return areaScopeDraft;
  }

  function renderAreaScopeDraft(doc) {
    const documentRef = doc || root.document;
    if (!documentRef || typeof documentRef.querySelectorAll !== 'function') return;
    const selectedCity = areaScopeDraft && areaScopeDraft.city;
    const selectedWards = new Set(areaScopeDraft && areaScopeDraft.mode !== 'city_all' ? areaScopeDraft.wards : []);
    documentRef.querySelectorAll('.area-scope-city-group').forEach((group) => {
      const groupCity = group.dataset ? group.dataset.areaScopeCity : '';
      group.classList.toggle('is-active', Boolean(selectedCity && groupCity === selectedCity));
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
    if (label) label.textContent = scope ? scopeLabel(scope) : '';
    if (bar) bar.hidden = !scope;
    if (chooser) chooser.hidden = Boolean(scope);
    if (documentRef.body) {
      documentRef.body.classList.toggle('area-scope-modal-open', !scope && chooser && !chooser.hidden);
    }
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
    areaScopeDraft = draft && draft.mode !== 'city_all' ? draft : null;
    if (chooser) {
      chooser.hidden = false;
      if (documentRef.body) documentRef.body.classList.add('area-scope-modal-open');
      renderAreaScopeDraft(documentRef);
      const focusTarget = chooser.querySelector('.area-scope-city-all, .area-scope-ward-chip, .area-scope-filter');
      if (focusTarget && typeof focusTarget.focus === 'function') focusTarget.focus();
    }
    if (bar) bar.hidden = true;
  }

  function replaceUrlWithScope(scope) {
    if (!root.location || !root.history || !scope) return;
    const params = new URLSearchParams(root.location.search || '');
    params.set('tab', 'signals');
    applyScopeToParams(params, scope);
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
    if (opts.updateUrl !== false) replaceUrlWithScope(normalized);
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
    return applyDashboardScope({
      version: 1,
      city: resolvedCity,
      wards: [],
      mode: 'city_all',
    }, { persist: true, updateUrl: true, apply: true });
  };

  root.toggleAreaScopeWard = function toggleAreaScopeWard(button) {
    if (!button || !button.dataset) return null;
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
    return applyDashboardScope(areaScopeDraft, { persist: true, updateUrl: true, apply: true });
  };

  root.openAreaScopeChooser = function openAreaScopeChooser() {
    showChooser(root.document);
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

  return Object.freeze({
    STORAGE_KEY,
    PRESET_SCOPES,
    applyDashboardScope,
    applyScopeToParams,
    clearStoredScope,
    hideChooser,
    nextDraftWardScope,
    readStoredScope,
    replaceUrlWithScope,
    saveScope,
    scopeFromSearchParams,
    scopeLabel,
    selectedScopeFromControls,
    showChooser,
    syncScopeControls,
    updateScopeUi,
    validateScope,
  });
});

(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root && root.document) {
    root.RadarListingMap = api;
    api.bind(root.document, root);
  }
})(typeof window !== "undefined" ? window : null, function (root) {
  "use strict";

  var VALID_MODES = ["signals", "all"];
  var VALID_BASE_LAYERS = ["street", "satellite"];
  var DIRECTORY_BATCH_SIZE = 100;
  var DIRECTORY_FRAME_CHUNK_SIZE = 25;
  var MARKER_BATCH_SIZE = 200;
  var MOBILE_MEDIA_QUERY = "(max-width: 760px)";
  var PRICE_LABEL_MIN_ZOOM = 13;
  var PRICE_LABEL_WIDTH = 92;
  var PRICE_LABEL_HEIGHT = 30;
  var PRICE_LABEL_ANCHOR_Y = 40;
  var COUNT_LABEL_WIDTH = 44;
  var COUNT_LABEL_HEIGHT = 18;
  var COUNT_LABEL_ANCHOR_Y = 29;
  var MARKER_LABEL_COLLISION_GAP = 4;
  var INITIAL_MAP_MIN_ZOOM = 14;
  var INITIAL_MAP_MAX_ZOOM = 16;
  var LOCATION_KEY_PATTERN = /^(exact|road|landmark|ward):[a-z0-9:-]+$/;
  var SAFE_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/;
  var SHARE_EXCLUDED_PARAMS = [
    "page", "limit", "include_total", "sort_by", "sort_dir",
    "location_key", "lat", "lng", "accuracy", "zoom", "center",
    "marker", "selected"
  ];
  var leafletPromise = null;
  var bound = false;
  var summarySequence = 0;
  var itemSequence = 0;
  var state = {
    open: false,
    snapshot: null,
    workspace: null,
    map: null,
    markerLayer: null,
    markerLabelLayer: null,
    markerLabelGroups: [],
    markerLabelFrameId: null,
    baseLayers: {},
    activeBaseLayer: "street",
    summaryController: null,
    itemController: null,
    previousFocus: null,
    previousTab: "signals",
    scrollElement: null,
    scrollTop: 0,
    historyPushed: false,
    initialSharedOpen: false,
    summary: null,
    selectedGroup: null,
    panelView: { kind: "directory", group: null, payload: null },
    directoryVisibleCount: DIRECTORY_BATCH_SIZE,
    directoryGeneration: 0,
    directoryFrameId: null,
    mediaQuery: null,
    mediaQueryHandler: null,
    markerGeneration: 0,
    markerFrameId: null,
    markerRenderCount: 0,
    sheetExpanded: false,
    mapActionControl: null,
    locationButton: null,
    shareButton: null,
    userLocationMarker: null,
    userAccuracyCircle: null,
    locationRequestId: 0,
    mapFeedbackTimer: null,
    mapFeedbackElement: null
  };

  function normalizeMode(value) {
    var mode = String(value || "").toLowerCase();
    return VALID_MODES.indexOf(mode) >= 0 ? mode : null;
  }

  function normalizeBaseLayer(value) {
    var layer = String(value || "").toLowerCase();
    return VALID_BASE_LAYERS.indexOf(layer) >= 0 ? layer : "street";
  }

  function cardDateText(item) {
    var rawDays = item && item.days_ago;
    var days = Number(rawDays);
    var relative = rawDays === null || rawDays === undefined || rawDays === ""
      || !Number.isFinite(days) || days < 0
      ? "Chưa rõ ngày"
      : (days <= 0 ? "hôm nay" : days + " ngày trước");
    var reason = String((item && item.card_date_reason) || "posted");
    if (reason === "price_updated") return "Cập nhật giá " + relative;
    if (reason === "first_seen") return "Theo dõi từ " + relative;
    return relative.charAt(0).toUpperCase() + relative.slice(1);
  }

  function mapBaseLayers() {
    return {
      street: {
        url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        maxZoom: 19,
        attribution: (
          '&copy; <a href="https://www.openstreetmap.org/copyright">'
          + "OpenStreetMap</a> contributors"
        )
      },
      satellite: {
        url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        maxZoom: 19,
        attribution: (
          "Tiles &copy; Esri &mdash; Source: Esri, Maxar, "
          + "Earthstar Geographics, and the GIS User Community"
        )
      }
    };
  }

  function mapOptions() {
    return {
      zoomControl: true,
      scrollWheelZoom: true,
      preferCanvas: true
    };
  }

  function precisionCopy(value) {
    var copies = {
      exact: {
        badge: "Vị trí chính xác",
        detail: "Tọa độ được cung cấp trực tiếp từ tin rao."
      },
      road: {
        badge: "Theo tên đường",
        detail: "Các tin cùng tuyến đường được gom tại một điểm đại diện."
      },
      landmark: {
        badge: "Theo khu vực",
        detail: "Tin được đặt tại khu TĐC, KDC hoặc dự án đã xác minh."
      },
      ward: {
        badge: "Theo trung tâm phường",
        detail: "Tin chưa đủ tên đường nên dùng điểm đại diện cấp phường."
      }
    };
    var normalized = value === "nearby" ? "road" : value;
    return copies[normalized] || {
      badge: "Chưa xác định",
      detail: "Chưa đủ dữ liệu để xác định độ chính xác."
    };
  }

  function normalizedSnapshot(snapshot) {
    var mode = normalizeMode(snapshot && snapshot.mode);
    if (!mode) return null;
    return {
      mode: mode,
      query: String((snapshot && snapshot.query) || "")
    };
  }

  function buildSummaryUrl(snapshot) {
    var safe = normalizedSnapshot(snapshot);
    if (!safe) return null;
    var params = new URLSearchParams(safe.query);
    params.set("mode", safe.mode);
    params.delete("page");
    params.delete("limit");
    params.delete("location_key");
    return "/api/map-listings?" + params.toString();
  }

  function buildItemsUrl(snapshot, locationKey, page, limit) {
    var safe = normalizedSnapshot(snapshot);
    var key = String(locationKey || "");
    if (
      !safe
      || key.length > 240
      || !LOCATION_KEY_PATTERN.test(key)
    ) {
      return null;
    }
    var safePage = Math.max(parseInt(page, 10) || 1, 1);
    var safeLimit = Math.min(Math.max(parseInt(limit, 10) || 20, 1), 50);
    var params = new URLSearchParams(safe.query);
    params.set("mode", safe.mode);
    params.set("location_key", key);
    params.set("page", String(safePage));
    params.set("limit", String(safeLimit));
    return "/api/map-listing-items?" + params.toString();
  }

  function buildMapShareUrl(snapshot, currentHref) {
    var safe = normalizedSnapshot(snapshot);
    if (!safe) return null;
    try {
      var url = new URL(currentHref);
      var params = new URLSearchParams(safe.query);
      SHARE_EXCLUDED_PARAMS.forEach(function (key) {
        params.delete(key);
      });
      params.set("tab", safe.mode);
      params.set("map", "1");
      url.search = params.toString();
      url.hash = "";
      return url.toString();
    } catch (error) {
      return null;
    }
  }

  function urlWithoutMapFlag(currentHref) {
    try {
      var url = new URL(currentHref);
      url.searchParams.delete("map");
      return url.toString();
    } catch (error) {
      return String(currentHref || "");
    }
  }

  function safeCount(value) {
    var number = Number(value);
    return Number.isFinite(number) && number >= 0 ? Math.round(number) : 0;
  }

  function activePanelId(isMobile) {
    return isMobile ? "listingMapMobileSheet" : "listingMapPanel";
  }

  function directoryWindow(total, requestedVisible) {
    var safeTotal = safeCount(total);
    var requested = safeCount(requestedVisible);
    var visible = Math.min(
      safeTotal,
      Math.max(requested || DIRECTORY_BATCH_SIZE, DIRECTORY_BATCH_SIZE)
    );
    var nextVisible = Math.min(safeTotal, visible + DIRECTORY_BATCH_SIZE);
    return {
      visible: visible,
      nextVisible: nextVisible,
      remaining: Math.max(safeTotal - visible, 0)
    };
  }

  function panelRenderModel(isMobile, locations, requestedVisible) {
    var safeLocations = Array.isArray(locations)
      ? locations.filter(function (group) {
        return !group || group.precision !== "exact";
      })
      : [];
    var page = directoryWindow(safeLocations.length, requestedVisible);
    return {
      activePanelId: activePanelId(Boolean(isMobile)),
      inactivePanelId: activePanelId(!Boolean(isMobile)),
      groups: safeLocations.slice(0, page.visible),
      visible: page.visible,
      nextVisible: page.nextVisible,
      remaining: page.remaining
    };
  }

  function finiteNumber(value) {
    var number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function trimNumber(value, decimals) {
    var number = finiteNumber(value);
    if (number === null) return "";
    return Number(number.toFixed(decimals)).toLocaleString("vi-VN", {
      maximumFractionDigits: decimals
    });
  }

  function hiddenMarkerLabel() {
    return { visible: false, kind: "", line1: "", line2: "" };
  }

  function markerLabelModel(group, zoom) {
    if (!group) return hiddenMarkerLabel();
    var precision = group.precision === "nearby" ? "road" : group.precision;
    var count = safeCount(group.listing_count);
    var isPriceLabel = precision === "exact"
      || (precision === "road" && count === 1);
    if (!isPriceLabel) {
      var priorities = { road: 2, landmark: 3, ward: 4 };
      if (!count || priorities[precision] === undefined) {
        return hiddenMarkerLabel();
      }
      return {
        visible: true,
        kind: "count",
        priority: priorities[precision],
        line1: count + " tin",
        line2: "",
        width: COUNT_LABEL_WIDTH,
        height: COUNT_LABEL_HEIGHT,
        anchorY: COUNT_LABEL_ANCHOR_Y
      };
    }
    if (Number(zoom) < PRICE_LABEL_MIN_ZOOM) return hiddenMarkerLabel();
    var price = finiteNumber(group.price_ty);
    var area = finiteNumber(group.area_m2);
    var pricePerM2 = finiteNumber(group.price_per_m2);
    if (
      (pricePerM2 === null || pricePerM2 <= 0)
      && price > 0
      && area > 0
    ) {
      pricePerM2 = price * 1000 / area;
    }
    if (!(price > 0) || !(area > 0) || !(pricePerM2 > 0)) {
      return hiddenMarkerLabel();
    }
    return {
      visible: true,
      kind: "price",
      priority: precision === "exact" ? 0 : 1,
      line1: trimNumber(price, 2) + " tỷ · " + trimNumber(area, 1) + "m²",
      line2: trimNumber(pricePerM2, 1) + "tr/m²",
      width: PRICE_LABEL_WIDTH,
      height: PRICE_LABEL_HEIGHT,
      anchorY: PRICE_LABEL_ANCHOR_Y
    };
  }

  function labelRectCollides(candidate, existingRects, gap) {
    var safeGap = Math.max(finiteNumber(gap) || 0, 0);
    var rects = Array.isArray(existingRects) ? existingRects : [];
    return rects.some(function (rect) {
      return !(
        candidate.right + safeGap <= rect.left
        || candidate.left - safeGap >= rect.right
        || candidate.bottom + safeGap <= rect.top
        || candidate.top - safeGap >= rect.bottom
      );
    });
  }

  function markerLabelRect(point, model) {
    var width = model && finiteNumber(model.width);
    var height = model && finiteNumber(model.height);
    var anchorY = model && finiteNumber(model.anchorY);
    width = width > 0 ? width : COUNT_LABEL_WIDTH;
    height = height > 0 ? height : COUNT_LABEL_HEIGHT;
    anchorY = anchorY > 0 ? anchorY : COUNT_LABEL_ANCHOR_Y;
    return {
      left: point.x - (width / 2),
      right: point.x + (width / 2),
      top: point.y - anchorY,
      bottom: point.y - anchorY + height
    };
  }

  function markerLabelClassName(group, model) {
    var precision = group && group.precision === "nearby"
      ? "road"
      : String((group && group.precision) || "");
    return "listing-map-marker-label listing-map-marker-label-"
      + model.kind + " listing-map-marker-label-precision-" + precision;
  }

  function closerInitialZoom(fittedZoom) {
    var zoom = finiteNumber(fittedZoom);
    if (zoom === null) return INITIAL_MAP_MIN_ZOOM;
    return Math.min(
      Math.max(zoom + 1, INITIAL_MAP_MIN_ZOOM),
      INITIAL_MAP_MAX_ZOOM
    );
  }

  function batchRanges(total, batchSize) {
    var safeTotal = safeCount(total);
    var safeBatch = Math.max(safeCount(batchSize) || 1, 1);
    var ranges = [];
    for (var start = 0; start < safeTotal; start += safeBatch) {
      ranges.push([start, Math.min(start + safeBatch, safeTotal)]);
    }
    return ranges;
  }

  function nextBatch(total, start, batchSize) {
    var safeTotal = safeCount(total);
    var safeStart = Math.min(safeCount(start), safeTotal);
    var safeBatch = Math.max(safeCount(batchSize) || 1, 1);
    var end = Math.min(safeStart + safeBatch, safeTotal);
    return {
      start: safeStart,
      end: end,
      done: end >= safeTotal
    };
  }

  function canContinueMarkerRender(
    isOpen,
    expectedGeneration,
    currentGeneration,
    hasMarkerLayer
  ) {
    return Boolean(
      isOpen
      && hasMarkerLayer
      && expectedGeneration === currentGeneration
    );
  }

  function mobileSheetModel(expanded, viewKind) {
    var isExpanded = Boolean(expanded);
    var isDirectory = String(viewKind || "directory") === "directory";
    return {
      expanded: isExpanded,
      state: isExpanded ? "expanded" : "collapsed",
      ariaExpanded: isExpanded ? "true" : "false",
      label: isExpanded
        ? "Thu gọn"
        : (isDirectory ? "Xem danh sách vị trí" : "Mở rộng")
    };
  }

  function sheetExpandedForView(kind, currentExpanded) {
    if (["items-loading", "items", "items-error"].indexOf(kind) >= 0) {
      return true;
    }
    return Boolean(currentExpanded);
  }

  function selectedSheetActionModel(viewKind) {
    return {
      backLabel: "← Tất cả vị trí",
      retryLabel: viewKind === "items-error" ? "Thử lại" : null
    };
  }

  function normalizeAccuracyRadius(value) {
    var number = Number(value);
    if (!Number.isFinite(number) || number <= 0) return 0;
    return Math.min(Math.round(number), 20000);
  }

  function locationTargetZoom(currentZoom) {
    var zoom = finiteNumber(currentZoom);
    return Math.max(zoom === null ? 0 : zoom, 16);
  }

  function geolocationErrorMessage(error) {
    var code = Number(error && error.code);
    if (code === 1) return "Bạn chưa cấp quyền vị trí.";
    if (code === 2) return "Không xác định được vị trí.";
    if (code === 3) return "Định vị quá thời gian, hãy thử lại.";
    return "Không thể định vị lúc này.";
  }

  function isCurrentLocationCallback(
    requestId,
    activeRequestId,
    isOpen,
    hasMap
  ) {
    return Boolean(
      requestId === activeRequestId
      && isOpen
      && hasMap
    );
  }

  function safeTrackingContext(input) {
    input = input || {};
    var output = {};
    var mode = normalizeMode(input.mode);
    if (mode) output.mode = mode;
    if (
      ["exact", "road", "landmark", "ward"]
        .indexOf(input.precision) >= 0
    ) {
      output.precision = input.precision;
    }
    [
      "listing_count",
      "mapped_count",
      "unmapped_count",
      "group_count"
    ].forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(input, key)) {
        output[key] = safeCount(input[key]);
      }
    });
    if (Array.isArray(input.layer_ids)) {
      output.layer_ids = input.layer_ids
        .map(String)
        .filter(function (value) {
          return SAFE_ID_PATTERN.test(value);
        })
        .slice(0, 12);
    }
    if (VALID_BASE_LAYERS.indexOf(input.base_layer_id) >= 0) {
      output.base_layer_id = input.base_layer_id;
    }
    if (SAFE_ID_PATTERN.test(String(input.close_reason || ""))) {
      output.close_reason = String(input.close_reason);
    }
    return output;
  }

  function emitTrack(action, context) {
    if (!root) return;
    var allowed = [
      "listing_map_opened",
      "listing_map_closed",
      "listing_map_base_layer_changed",
      "listing_map_group_selected",
      "listing_map_retry"
    ];
    if (allowed.indexOf(action) < 0) return;
    try {
      if (typeof root.track === "function") {
        root.track(action, { context: safeTrackingContext(context) });
      }
    } catch (error) {
      // Telemetry is best effort and must never block the map.
    }
  }

  function vendorConfig() {
    return (root && root.RADAR_MAP_VENDOR) || {};
  }

  function appendVendorStyle(doc, config) {
    var existing = doc.querySelector("link[data-radar-leaflet-style]");
    if (existing) return Promise.resolve(existing);
    return new Promise(function (resolve, reject) {
      var link = doc.createElement("link");
      link.rel = "stylesheet";
      link.href = config.url;
      link.integrity = config.integrity;
      link.crossOrigin = "anonymous";
      link.dataset.radarLeafletStyle = "true";
      link.onload = function () { resolve(link); };
      link.onerror = function () {
        link.remove();
        reject(new Error("Leaflet stylesheet failed to load"));
      };
      doc.head.appendChild(link);
    });
  }

  function appendVendorScript(doc, config) {
    if (root && root.L) return Promise.resolve(root.L);
    var existing = doc.querySelector("script[data-radar-leaflet-script]");
    if (existing) {
      return new Promise(function (resolve, reject) {
        existing.addEventListener("load", function () {
          resolve(root.L);
        }, { once: true });
        existing.addEventListener("error", function () {
          reject(new Error("Leaflet script failed to load"));
        }, { once: true });
      });
    }
    return new Promise(function (resolve, reject) {
      var script = doc.createElement("script");
      script.src = config.url;
      script.integrity = config.integrity;
      script.crossOrigin = "anonymous";
      script.async = true;
      script.dataset.radarLeafletScript = "true";
      script.onload = function () {
        if (root.L) resolve(root.L);
        else reject(new Error("Leaflet did not initialize"));
      };
      script.onerror = function () {
        script.remove();
        reject(new Error("Leaflet script failed to load"));
      };
      doc.body.appendChild(script);
    });
  }

  function loadLeaflet() {
    if (!root || !root.document) {
      return Promise.reject(new Error("Leaflet requires a browser"));
    }
    if (root.L) return Promise.resolve(root.L);
    if (leafletPromise) return leafletPromise;
    var config = vendorConfig();
    if (
      !config.leafletScript
      || !config.leafletStyle
      || !config.leafletScript.url
      || !config.leafletStyle.url
    ) {
      return Promise.reject(new Error("Missing Leaflet vendor configuration"));
    }
    leafletPromise = Promise.all([
      appendVendorStyle(root.document, config.leafletStyle),
      appendVendorScript(root.document, config.leafletScript)
    ]).then(function () {
      return root.L;
    }).catch(function (error) {
      leafletPromise = null;
      throw error;
    });
    return leafletPromise;
  }

  function element(id) {
    return root && root.document
      ? root.document.getElementById(id)
      : null;
  }

  function setStatus(text, busy) {
    var status = element("listingMapStatus");
    if (!status) return;
    status.textContent = String(text || "");
    status.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function clearElement(target) {
    if (!target) return;
    while (target.firstChild) target.removeChild(target.firstChild);
  }

  function create(tag, className, text) {
    var node = root.document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function isMobileViewport() {
    return Boolean(state.mediaQuery && state.mediaQuery.matches);
  }

  function activePanel() {
    return element(activePanelId(isMobileViewport()));
  }

  function inactivePanel() {
    return element(activePanelId(!isMobileViewport()));
  }

  function clearPanels() {
    clearElement(element("listingMapPanel"));
    clearElement(element("listingMapMobileSheet"));
  }

  function cancelDirectoryRender() {
    state.directoryGeneration += 1;
    if (state.directoryFrameId !== null) {
      if (typeof root.cancelAnimationFrame === "function") {
        root.cancelAnimationFrame(state.directoryFrameId);
      } else {
        root.clearTimeout(state.directoryFrameId);
      }
    }
    state.directoryFrameId = null;
  }

  function scheduleDirectoryChunk(callback) {
    if (typeof root.requestAnimationFrame === "function") {
      state.directoryFrameId = root.requestAnimationFrame(callback);
      return;
    }
    state.directoryFrameId = root.setTimeout(callback, 0);
  }

  function appendDirectoryGroups(list, groups) {
    cancelDirectoryRender();
    var generation = state.directoryGeneration;
    var index = 0;

    function appendChunk() {
      if (!state.open || generation !== state.directoryGeneration) return;
      var end = Math.min(index + DIRECTORY_FRAME_CHUNK_SIZE, groups.length);
      var fragment = root.document.createDocumentFragment();
      for (; index < end; index += 1) {
        fragment.appendChild(groupButton(groups[index]));
      }
      list.appendChild(fragment);
      if (index < groups.length) {
        scheduleDirectoryChunk(appendChunk);
      } else {
        state.directoryFrameId = null;
      }
    }

    appendChunk();
  }

  function renderRetry(target, message, retry, retryContext) {
    clearElement(target);
    var box = create("div", "listing-map-error");
    box.appendChild(create("strong", "", message));
    var button = create("button", "listing-map-retry", "Thử lại");
    button.type = "button";
    button.addEventListener("click", function () {
      emitTrack("listing_map_retry", retryContext || {});
      retry();
    });
    box.appendChild(button);
    target.appendChild(box);
  }

  function fetchJson(url, controller) {
    return root.fetch(url, {
      signal: controller.signal,
      cache: "no-store",
      credentials: "same-origin"
    }).then(function (response) {
      if (!response.ok) {
        throw new Error(response.status + " " + response.statusText);
      }
      return response.json();
    });
  }

  function markerStyle(precision) {
    if (precision === "exact") {
      return {
        radius: 8,
        color: "#047857",
        weight: 3,
        fillColor: "#10b981",
        fillOpacity: 0.86
      };
    }
    if (precision === "road") {
      return {
        radius: 9,
        color: "#3730a3",
        weight: 3,
        fillColor: "#6366f1",
        fillOpacity: 0.84
      };
    }
    if (precision === "landmark") {
      return {
        radius: 9,
        color: "#0f766e",
        weight: 3,
        fillColor: "#14b8a6",
        fillOpacity: 0.84
      };
    }
    return {
      radius: 10,
      color: "#b45309",
      weight: 3,
      fillColor: "#f59e0b",
      fillOpacity: 0.82
    };
  }

  function activateBaseLayer(layerId) {
    var safeId = normalizeBaseLayer(layerId);
    var layer = state.baseLayers[safeId];
    if (!state.map || !layer) return;
    Object.keys(state.baseLayers).forEach(function (key) {
      var candidate = state.baseLayers[key];
      if (key !== safeId && state.map.hasLayer(candidate)) {
        state.map.removeLayer(candidate);
      }
    });
    if (!state.map.hasLayer(layer)) layer.addTo(state.map);
    state.activeBaseLayer = safeId;
  }

  function setLocationButtonLoading(loading) {
    if (!state.locationButton) return;
    state.locationButton.disabled = Boolean(loading);
    state.locationButton.setAttribute(
      "aria-busy",
      loading ? "true" : "false"
    );
    state.locationButton.classList.toggle("is-loading", Boolean(loading));
  }

  function showMapFeedback(message, kind) {
    if (!state.mapFeedbackElement) return;
    if (state.mapFeedbackTimer !== null) {
      root.clearTimeout(state.mapFeedbackTimer);
    }
    state.mapFeedbackElement.textContent = String(message || "");
    state.mapFeedbackElement.dataset.kind = kind || "info";
    state.mapFeedbackElement.hidden = false;
    state.mapFeedbackTimer = root.setTimeout(function () {
      state.mapFeedbackTimer = null;
      if (state.mapFeedbackElement) state.mapFeedbackElement.hidden = true;
    }, 2500);
  }

  function clearUserLocation() {
    state.locationRequestId += 1;
    if (state.map && state.userLocationMarker) {
      state.map.removeLayer(state.userLocationMarker);
    }
    if (state.map && state.userAccuracyCircle) {
      state.map.removeLayer(state.userAccuracyCircle);
    }
    state.userLocationMarker = null;
    state.userAccuracyCircle = null;
    setLocationButtonLoading(false);
    if (state.mapFeedbackTimer !== null) {
      root.clearTimeout(state.mapFeedbackTimer);
      state.mapFeedbackTimer = null;
    }
    state.mapFeedbackElement = null;
    state.locationButton = null;
    state.shareButton = null;
    state.mapActionControl = null;
  }

  function requestUserLocation() {
    var geolocation = root.navigator && root.navigator.geolocation;
    if (!geolocation || typeof geolocation.getCurrentPosition !== "function") {
      showMapFeedback("Trình duyệt không hỗ trợ định vị.", "error");
      return;
    }
    state.locationRequestId += 1;
    var requestId = state.locationRequestId;
    setLocationButtonLoading(true);
    geolocation.getCurrentPosition(function (position) {
      if (!isCurrentLocationCallback(
        requestId,
        state.locationRequestId,
        state.open,
        Boolean(state.map)
      )) return;
      var latitude = finiteNumber(position && position.coords && position.coords.latitude);
      var longitude = finiteNumber(position && position.coords && position.coords.longitude);
      if (latitude === null || longitude === null) {
        setLocationButtonLoading(false);
        showMapFeedback("Không xác định được vị trí.", "error");
        return;
      }
      if (state.userLocationMarker) {
        state.map.removeLayer(state.userLocationMarker);
      }
      if (state.userAccuracyCircle) {
        state.map.removeLayer(state.userAccuracyCircle);
      }
      state.userAccuracyCircle = root.L.circle([latitude, longitude], {
        radius: normalizeAccuracyRadius(position.coords.accuracy),
        className: "listing-map-user-accuracy",
        color: "#2563eb",
        fillColor: "#60a5fa",
        fillOpacity: 0.12,
        opacity: 0.38,
        weight: 1,
        interactive: false
      }).addTo(state.map);
      state.userLocationMarker = root.L.circleMarker(
        [latitude, longitude],
        {
          radius: 7,
          className: "listing-map-user-location",
          color: "#ffffff",
          fillColor: "#2563eb",
          fillOpacity: 1,
          opacity: 1,
          weight: 3,
          interactive: false
        }
      ).addTo(state.map);
      state.map.setView(
        [latitude, longitude],
        locationTargetZoom(state.map.getZoom())
      );
      setLocationButtonLoading(false);
      showMapFeedback("Đã xác định vị trí của bạn.", "success");
    }, function (error) {
      if (!isCurrentLocationCallback(
        requestId,
        state.locationRequestId,
        state.open,
        Boolean(state.map)
      )) return;
      setLocationButtonLoading(false);
      showMapFeedback(geolocationErrorMessage(error), "error");
    }, {
      enableHighAccuracy: true,
      timeout: 10000,
      maximumAge: 0
    });
  }

  function copyShareUrl(url) {
    var navigatorObject = root.navigator || {};
    if (
      navigatorObject.clipboard
      && typeof navigatorObject.clipboard.writeText === "function"
    ) {
      return navigatorObject.clipboard.writeText(url);
    }
    return new Promise(function (resolve, reject) {
      var textarea = root.document.createElement("textarea");
      textarea.value = url;
      textarea.readOnly = true;
      textarea.setAttribute("aria-hidden", "true");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      root.document.body.appendChild(textarea);
      textarea.select();
      try {
        if (!root.document.execCommand("copy")) {
          throw new Error("copy_failed");
        }
        resolve();
      } catch (error) {
        reject(error);
      } finally {
        textarea.remove();
      }
    });
  }

  function shareCurrentMap() {
    var shareUrl = buildMapShareUrl(
      state.snapshot,
      root.location && root.location.href
    );
    if (!shareUrl) {
      showMapFeedback("Không thể tạo liên kết, hãy thử lại.", "error");
      return;
    }
    var navigatorObject = root.navigator || {};
    if (typeof navigatorObject.share === "function") {
      try {
        Promise.resolve(navigatorObject.share({
          title: "Radar BĐS Maps",
          url: shareUrl
        })).catch(function (error) {
          if (!error || error.name !== "AbortError") {
            showMapFeedback("Không thể chia sẻ, hãy thử lại.", "error");
          }
        });
      } catch (error) {
        showMapFeedback("Không thể chia sẻ, hãy thử lại.", "error");
      }
      return;
    }
    copyShareUrl(shareUrl).then(function () {
      showMapFeedback("Đã sao chép", "success");
    }).catch(function () {
      showMapFeedback("Không thể sao chép, hãy thử lại.", "error");
    });
  }

  function mountMapActionControls(L) {
    var MapActions = L.Control.extend({
      options: { position: "topleft" },
      onAdd: function () {
        var container = L.DomUtil.create(
          "div",
          "leaflet-bar listing-map-map-actions"
        );
        var locate = L.DomUtil.create(
          "button",
          "listing-map-control-button listing-map-locate-button",
          container
        );
        locate.type = "button";
        locate.title = "Vị trí của tôi";
        locate.setAttribute("aria-label", "Vị trí của tôi");
        locate.setAttribute("aria-busy", "false");
        locate.innerHTML = '<span aria-hidden="true">⌖</span>';
        var share = L.DomUtil.create(
          "button",
          "listing-map-control-button listing-map-share-button",
          container
        );
        share.type = "button";
        share.title = "Chia sẻ";
        share.setAttribute("aria-label", "Chia sẻ");
        share.innerHTML = '<span aria-hidden="true">↗</span>';
        var feedback = L.DomUtil.create(
          "div",
          "listing-map-feedback",
          container
        );
        feedback.hidden = true;
        feedback.setAttribute("role", "status");
        feedback.setAttribute("aria-live", "polite");
        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);
        L.DomEvent.on(locate, "click", requestUserLocation);
        L.DomEvent.on(share, "click", shareCurrentMap);
        state.locationButton = locate;
        state.shareButton = share;
        state.mapFeedbackElement = feedback;
        return container;
      }
    });
    state.mapActionControl = new MapActions();
    state.mapActionControl.addTo(state.map);
  }

  function initMap(L) {
    var canvas = element("listingMapCanvas");
    if (!canvas) throw new Error("Missing listing map canvas");
    if (state.map) {
      clearUserLocation();
      state.map.remove();
    }
    state.map = L.map(canvas, mapOptions());
    var definitions = mapBaseLayers();
    state.baseLayers = {
      street: L.tileLayer(definitions.street.url, definitions.street),
      satellite: L.tileLayer(
        definitions.satellite.url,
        definitions.satellite
      )
    };
    state.activeBaseLayer = "street";
    state.baseLayers.street.addTo(state.map);
    L.control.layers({
      "Bản đồ đường phố": state.baseLayers.street,
      "Ảnh vệ tinh": state.baseLayers.satellite
    }, null, { position: "topright", collapsed: false }).addTo(state.map);
    state.map.on("baselayerchange", function (event) {
      var selected = event.layer === state.baseLayers.satellite
        ? "satellite"
        : "street";
      state.activeBaseLayer = selected;
      emitTrack("listing_map_base_layer_changed", {
        mode: state.snapshot && state.snapshot.mode,
        base_layer_id: selected,
        layer_ids: [selected]
      });
    });
    state.baseLayers.satellite.on("tileerror", function () {
      if (state.activeBaseLayer === "satellite") {
        activateBaseLayer("street");
        setStatus(
          "Ảnh vệ tinh không tải được; đã chuyển về bản đồ đường phố.",
          false
        );
      }
    });
    state.markerLayer = L.layerGroup().addTo(state.map);
    state.markerLabelLayer = L.layerGroup().addTo(state.map);
    mountMapActionControls(L);
    state.map.on("zoomend moveend", scheduleMarkerLabelRefresh);
    state.map.setView([11.02, 106.63], 11);
    root.setTimeout(function () {
      if (state.map) state.map.invalidateSize();
    }, 0);
  }

  function groupButton(group) {
    var copy = precisionCopy(group.precision);
    var button = create("button", "listing-map-group-button");
    button.type = "button";
    button.setAttribute(
      "aria-label",
      copy.badge + ": " + group.label + ", "
        + safeCount(group.listing_count) + " tin"
    );
    var header = create("span", "listing-map-group-button-head");
    header.appendChild(create("strong", "", group.label || copy.badge));
    header.appendChild(create(
      "span",
      "listing-map-count-badge",
      safeCount(group.listing_count)
    ));
    button.appendChild(header);
    button.appendChild(create("small", "", copy.badge));
    button.addEventListener("click", function () {
      selectGroup(group);
    });
    return button;
  }

  function isMobileSheet(target) {
    return Boolean(target && target.id === "listingMapMobileSheet");
  }

  function setMobileSheetExpanded(expanded) {
    var model = mobileSheetModel(
      expanded,
      state.panelView && state.panelView.kind
    );
    var sheet = element("listingMapMobileSheet");
    state.sheetExpanded = model.expanded;
    if (!sheet) return;
    sheet.classList.toggle("is-expanded", model.expanded);
    sheet.dataset.state = model.state;
    Array.prototype.forEach.call(
      sheet.querySelectorAll("[data-listing-map-sheet-toggle]"),
      function (toggle) {
        toggle.setAttribute("aria-expanded", model.ariaExpanded);
        toggle.textContent = model.label;
      }
    );
  }

  function appendSheetHandle(shell) {
    var handle = create("div", "listing-map-sheet-handle");
    handle.setAttribute("aria-hidden", "true");
    shell.appendChild(handle);
  }

  function createSheetToggle() {
    var model = mobileSheetModel(
      state.sheetExpanded,
      state.panelView && state.panelView.kind
    );
    var toggle = create(
      "button",
      "listing-map-sheet-toggle",
      model.label
    );
    toggle.type = "button";
    toggle.dataset.listingMapSheetToggle = "true";
    toggle.setAttribute("aria-expanded", model.ariaExpanded);
    toggle.addEventListener("click", function () {
      setMobileSheetExpanded(!state.sheetExpanded);
    });
    return toggle;
  }

  function createSelectedGroupBackButton() {
    var button = create(
      "button",
      "listing-map-back",
      selectedSheetActionModel("items").backLabel
    );
    button.type = "button";
    button.addEventListener("click", function () {
      state.selectedGroup = null;
      setPanelView("directory");
    });
    return button;
  }

  function appendSelectedSheetHeader(shell, back) {
    appendSheetHandle(shell);
    var actions = create("div", "listing-map-sheet-actions");
    actions.appendChild(back);
    actions.appendChild(createSheetToggle());
    shell.appendChild(actions);
  }

  function renderGroupDirectoryInto(target, payload) {
    if (!target) return;
    var summary = payload.summary || {};
    cancelDirectoryRender();
    clearElement(target);
    var shell = create("div", "listing-map-directory");
    if (isMobileSheet(target)) {
      appendSheetHandle(shell);
      shell.appendChild(createSheetToggle());
    }
    var stats = create("div", "listing-map-summary-grid");
    [
      ["Đã định vị", safeCount(summary.mapped)],
      ["Chưa định vị", safeCount(summary.unmapped_count)],
      ["Theo đường", safeCount(summary.road_count)],
      ["Theo khu vực", safeCount(summary.landmark_count)],
      ["Theo phường", safeCount(summary.ward_count)]
    ].forEach(function (entry) {
      var card = create("div", "listing-map-summary-card");
      card.appendChild(create("span", "", entry[0]));
      card.appendChild(create("strong", "", entry[1]));
      stats.appendChild(card);
    });
    shell.appendChild(stats);
    var heading = create(
      "h3",
      "listing-map-directory-title",
      "Chọn một vị trí để xem tin"
    );
    shell.appendChild(heading);
    var list = create("div", "listing-map-group-list");
    var model = panelRenderModel(
      isMobileViewport(),
      payload.locations || [],
      state.directoryVisibleCount
    );
    if (model.groups.length) {
      appendDirectoryGroups(list, model.groups);
    } else {
      list.appendChild(create(
        "p",
        "listing-map-empty",
        "Bộ lọc hiện tại chưa có lô đất xác định được vị trí."
      ));
    }
    shell.appendChild(list);
    if (model.remaining > 0) {
      var more = create(
        "button",
        "listing-map-show-more",
        "Xem thêm " + model.remaining + " vị trí"
      );
      more.type = "button";
      more.addEventListener("click", function () {
        var scrollTop = target.scrollTop;
        state.directoryVisibleCount = model.nextVisible;
        renderActiveView();
        var nextTarget = activePanel();
        if (nextTarget) nextTarget.scrollTop = scrollTop;
      });
      shell.appendChild(more);
    }
    target.appendChild(shell);
  }

  function makeTooltip(group) {
    var wrapper = create("div", "listing-map-tooltip");
    wrapper.appendChild(create(
      "strong",
      "",
      group.label || precisionCopy(group.precision).badge
    ));
    wrapper.appendChild(create(
      "span",
      "",
      precisionCopy(group.precision).badge + " · "
        + safeCount(group.listing_count) + " tin"
    ));
    return wrapper;
  }

  function cancelMarkerRender() {
    state.markerGeneration += 1;
    if (state.markerFrameId !== null) {
      if (typeof root.cancelAnimationFrame === "function") {
        root.cancelAnimationFrame(state.markerFrameId);
      } else {
        root.clearTimeout(state.markerFrameId);
      }
    }
    state.markerFrameId = null;
    state.markerRenderCount = 0;
  }

  function cancelMarkerLabelRefresh() {
    if (state.markerLabelFrameId !== null) {
      if (typeof root.cancelAnimationFrame === "function") {
        root.cancelAnimationFrame(state.markerLabelFrameId);
      } else {
        root.clearTimeout(state.markerLabelFrameId);
      }
    }
    state.markerLabelFrameId = null;
  }

  function clearMarkerLabels() {
    cancelMarkerLabelRefresh();
    if (state.markerLabelLayer) state.markerLabelLayer.clearLayers();
  }

  function scheduleMarkerBatch(callback) {
    if (typeof root.requestAnimationFrame === "function") {
      state.markerFrameId = root.requestAnimationFrame(callback);
      return;
    }
    state.markerFrameId = root.setTimeout(callback, 0);
  }

  function markerLabelHtml(model) {
    if (model.kind === "count") {
      return '<span class="listing-map-marker-label-count-text">'
        + model.line1 + "</span>";
    }
    return (
      '<span class="listing-map-marker-label-main">' + model.line1 + '</span>'
      + '<span class="listing-map-marker-label-sub">' + model.line2 + '</span>'
    );
  }

  function refreshMarkerLabels() {
    if (!state.map || !state.markerLabelLayer || !root.L) return;
    state.markerLabelLayer.clearLayers();
    var zoom = state.map.getZoom();

    var occupied = [];
    var size = typeof state.map.getSize === "function"
      ? state.map.getSize()
      : { x: 0, y: 0 };
    var candidates = state.markerLabelGroups.map(function (group) {
      return { group: group, model: markerLabelModel(group, zoom) };
    }).filter(function (candidate) {
      return candidate.model.visible;
    }).sort(function (left, right) {
      return left.model.priority - right.model.priority;
    });
    candidates.forEach(function (candidate) {
      var group = candidate.group;
      var model = candidate.model;
      var lat = Number(group.lat);
      var lng = Number(group.lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
      var point = state.map.latLngToContainerPoint([lat, lng]);
      var rect = markerLabelRect(point, model);
      if (
        size.x
        && (
          rect.right < -model.width
          || rect.left > size.x + model.width
          || rect.bottom < -model.height
          || rect.top > size.y + model.height
        )
      ) {
        return;
      }
      if (labelRectCollides(rect, occupied, MARKER_LABEL_COLLISION_GAP)) {
        return;
      }
      occupied.push(rect);
      root.L.marker([lat, lng], {
        interactive: false,
        keyboard: false,
        zIndexOffset: 1000,
        icon: root.L.divIcon({
          className: markerLabelClassName(group, model),
          html: markerLabelHtml(model),
          iconSize: [model.width, model.height],
          iconAnchor: [model.width / 2, model.anchorY]
        })
      }).addTo(state.markerLabelLayer);
    });
  }

  function scheduleMarkerLabelRefresh() {
    if (!state.open || !state.map || !state.markerLabelLayer) return;
    cancelMarkerLabelRefresh();
    var callback = function () {
      state.markerLabelFrameId = null;
      refreshMarkerLabels();
    };
    if (typeof root.requestAnimationFrame === "function") {
      state.markerLabelFrameId = root.requestAnimationFrame(callback);
      return;
    }
    state.markerLabelFrameId = root.setTimeout(callback, 0);
  }

  function addMarker(group) {
    var lat = Number(group.lat);
    var lng = Number(group.lng);
    var marker = root.L.circleMarker(
      [lat, lng],
      markerStyle(group.precision)
    );
    marker.bindTooltip(makeTooltip(group));
    marker.on("click", function () {
      selectGroup(group);
    });
    marker.on("add", function () {
      var markerElement = marker.getElement();
      if (!markerElement) return;
      markerElement.setAttribute("tabindex", "0");
      markerElement.setAttribute("role", "button");
      markerElement.setAttribute(
        "aria-label",
        precisionCopy(group.precision).badge + ", "
          + safeCount(group.listing_count) + " tin"
      );
      markerElement.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectGroup(group);
        }
      });
    });
    marker.addTo(state.markerLayer);
  }

  function setSummaryStatus(payload) {
    var summary = (payload && payload.summary) || {};
    setStatus(
      "Đã định vị " + safeCount(summary.mapped) + "/"
        + safeCount(summary.total) + " tin; "
        + safeCount(summary.unmapped_count) + " tin chưa đủ vị trí.",
      false
    );
  }

  function renderMarkerBatch(context) {
    if (!canContinueMarkerRender(
      state.open,
      context.generation,
      state.markerGeneration,
      Boolean(state.markerLayer)
    )) return;

    var batch = nextBatch(
      context.groups.length,
      context.index,
      MARKER_BATCH_SIZE
    );
    for (; context.index < batch.end; context.index += 1) {
      addMarker(context.groups[context.index]);
    }
    state.markerRenderCount = context.index;

    if (!batch.done) {
      setStatus(
        "Đang hiển thị " + context.index + "/"
          + context.groups.length + " vị trí...",
        true
      );
      scheduleMarkerBatch(function () {
        renderMarkerBatch(context);
      });
      return;
    }
    state.markerFrameId = null;
    setSummaryStatus(state.summary);
    scheduleMarkerLabelRefresh();
  }

  function renderMarkers(payload) {
    if (!state.map || !state.markerLayer) return;
    cancelMarkerRender();
    state.markerLayer.clearLayers();
    clearMarkerLabels();
    var bounds = [];
    var groups = (payload.locations || []).filter(function (group) {
      var lat = Number(group.lat);
      var lng = Number(group.lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return false;
      bounds.push([lat, lng]);
      return true;
    });
    state.markerLabelGroups = groups.slice();
    if (bounds.length) {
      state.map.fitBounds(bounds, {
        padding: [38, 38],
        maxZoom: 16
      });
      state.map.setZoom(closerInitialZoom(state.map.getZoom()), {
        animate: false
      });
    } else {
      state.map.setView([11.02, 106.63], 11);
    }
    var context = {
      generation: state.markerGeneration,
      groups: groups,
      index: 0
    };
    renderMarkerBatch(context);
  }

  function validListingId(item) {
    var id = Number(item && item.id);
    return Number.isInteger(id) && id > 0 ? id : null;
  }

  function itemModalProxy(targetRoot, item) {
    var win = targetRoot || root;
    var doc = win && win.document;
    if (!doc || typeof doc.createElement !== "function") return null;
    var proxy = doc.createElement("button");
    proxy.dataset.id = String(item.id || "");
    proxy.dataset.title = String(item.title || "");
    proxy.dataset.primary = String(item.thumbnail || "");
    proxy.dataset.price = String(item.price_ty || "");
    proxy.dataset.area = String(item.area_m2 || "");
    proxy.dataset.ward = String(item.ward || "");
    proxy.dataset.road = String(item.road_name || "");
    proxy.dataset.ptype = String(item.prop_type || "");
    proxy.dataset.propLabel = String(item.prop_type_label || "");
    proxy.dataset.mos = String(item.mos_pct || 0);
    proxy.dataset.mosPctDisplay = String(item.mos_pct || 0);
    proxy.dataset.source = String(item.source || "");
    proxy.dataset.time = String(item.days_ago || "");
    proxy.dataset.cardDateReason = String(item.card_date_reason || "posted");
    return proxy;
  }

  function openListingFromMap(targetRoot, item) {
    var win = targetRoot || root;
    if (!validListingId(item) || !win || typeof win.openListingModal !== "function") {
      return false;
    }
    var proxy = itemModalProxy(win, item);
    if (!proxy) return false;
    win.openListingModal(proxy);
    return true;
  }

  function openItem(item) {
    openListingFromMap(root, item);
  }

  function renderItemsInto(target, group, payload) {
    if (!target) return;
    cancelDirectoryRender();
    clearElement(target);
    var shell = create("div", "listing-map-items");
    var back = createSelectedGroupBackButton();
    if (isMobileSheet(target)) {
      appendSelectedSheetHeader(shell, back);
    } else {
      shell.appendChild(back);
    }
    shell.appendChild(create("h3", "", group.label));
    shell.appendChild(create(
      "p",
      "listing-map-precision-copy",
      precisionCopy(group.precision).badge + ". "
        + precisionCopy(group.precision).detail
    ));
    var list = create("div", "listing-map-item-list");
    (payload.items || []).forEach(function (item) {
      var card = create("button", "listing-map-item-card");
      card.type = "button";
      if (item.thumbnail) {
        var image = create("img", "listing-map-item-thumb");
        image.src = item.thumbnail;
        image.alt = "";
        image.loading = "lazy";
        card.appendChild(image);
      }
      var content = create("span", "listing-map-item-content");
      content.appendChild(create("strong", "", item.title || "Tin rao"));
      content.appendChild(create(
        "span",
        "listing-map-item-meta",
        [
          item.price_ty ? item.price_ty + " tỷ" : "Chưa rõ giá",
          item.area_m2 ? item.area_m2 + " m²" : "Chưa rõ diện tích",
          item.prop_type_label || "",
          item.ward || "",
          item.road_name || ""
        ].filter(Boolean).join(" · ")
      ));
      if (state.snapshot.mode === "signals") {
        content.appendChild(create(
          "span",
          "listing-map-item-mos",
          "MOS " + Number(item.mos_pct || 0).toFixed(1) + "%"
        ));
      }
      if (item.days_ago !== null && item.days_ago !== undefined) {
        content.appendChild(create(
          "small",
          "",
          cardDateText(item)
        ));
      }
      card.appendChild(content);
      card.addEventListener("click", function () {
        openItem(item);
      });
      list.appendChild(card);
    });
    if (!list.childNodes.length) {
      list.appendChild(create(
        "p",
        "listing-map-empty",
        "Không còn tin phù hợp trong nhóm này."
      ));
    }
    shell.appendChild(list);
    target.appendChild(shell);
    if (isMobileSheet(target)) target.scrollTop = 0;
  }

  function renderItemsLoadingInto(target, group) {
    if (!target) return;
    cancelDirectoryRender();
    clearElement(target);
    var shell = create("div", "listing-map-panel-loading");
    if (isMobileSheet(target)) {
      appendSelectedSheetHeader(shell, createSelectedGroupBackButton());
    }
    shell.appendChild(create("strong", "", group.label));
    shell.appendChild(create("span", "", "Đang tải các lô đất..."));
    target.appendChild(shell);
    if (isMobileSheet(target)) target.scrollTop = 0;
  }

  function renderItemsErrorInto(target, group) {
    if (isMobileSheet(target)) {
      cancelDirectoryRender();
      clearElement(target);
      var shell = create("div", "listing-map-error");
      appendSelectedSheetHeader(shell, createSelectedGroupBackButton());
      shell.appendChild(create(
        "strong",
        "",
        "Không tải được các lô đất tại vị trí này."
      ));
      var retry = create(
        "button",
        "listing-map-retry",
        selectedSheetActionModel("items-error").retryLabel
      );
      retry.type = "button";
      retry.addEventListener("click", function () {
        emitTrack("listing_map_retry", {
          mode: state.snapshot && state.snapshot.mode,
          precision: group.precision,
          listing_count: group.listing_count
        });
        selectGroup(group);
      });
      shell.appendChild(retry);
      target.appendChild(shell);
      target.scrollTop = 0;
      return;
    }
    renderRetry(
      target,
      "Không tải được các lô đất tại vị trí này.",
      function () { selectGroup(group); },
      {
        mode: state.snapshot && state.snapshot.mode,
        precision: group.precision,
        listing_count: group.listing_count
      }
    );
    if (isMobileSheet(target)) target.scrollTop = 0;
  }

  function renderSummaryErrorInto(target) {
    renderRetry(
      target,
      "Không tải được dữ liệu bản đồ.",
      requestSummary,
      { mode: state.snapshot && state.snapshot.mode }
    );
  }

  function renderLibraryErrorInto(target) {
    renderRetry(
      target,
      "Bản đồ chưa tải được. Danh sách tin vẫn hoạt động bình thường.",
      function () { startMapLoad(state.snapshot); },
      { mode: state.snapshot && state.snapshot.mode }
    );
  }

  function renderActiveView() {
    var target = activePanel();
    clearElement(inactivePanel());
    if (!target) return;
    var view = state.panelView || { kind: "directory" };
    if (isMobileViewport()) {
      setMobileSheetExpanded(sheetExpandedForView(
        view.kind,
        state.sheetExpanded
      ));
    }
    if (view.kind === "items") {
      renderItemsInto(target, view.group, view.payload || { items: [] });
      return;
    }
    if (view.kind === "items-loading") {
      renderItemsLoadingInto(target, view.group);
      return;
    }
    if (view.kind === "items-error") {
      renderItemsErrorInto(target, view.group);
      return;
    }
    if (view.kind === "summary-error") {
      renderSummaryErrorInto(target);
      return;
    }
    if (view.kind === "library-error") {
      renderLibraryErrorInto(target);
      return;
    }
    renderGroupDirectoryInto(target, state.summary || {
      summary: {}, locations: []
    });
  }

  function setPanelView(kind, group, payload) {
    state.panelView = {
      kind: kind,
      group: group || null,
      payload: payload || null
    };
    renderActiveView();
  }

  function selectGroup(group) {
    if (!state.open || !state.snapshot) return;
    state.selectedGroup = group;
    setMobileSheetExpanded(true);
    itemSequence += 1;
    var sequence = itemSequence;
    if (state.itemController) state.itemController.abort();
    state.itemController = new AbortController();
    var controller = state.itemController;
    var url = buildItemsUrl(
      state.snapshot,
      group.location_key,
      1,
      20
    );
    if (!url) return;
    setPanelView("items-loading", group);
    emitTrack("listing_map_group_selected", {
      mode: state.snapshot.mode,
      precision: group.precision,
      listing_count: group.listing_count,
      base_layer_id: state.activeBaseLayer,
      layer_ids: [state.activeBaseLayer]
    });
    fetchJson(url, controller).then(function (payload) {
      if (!state.open || sequence !== itemSequence) return;
      setPanelView("items", group, payload);
    }).catch(function (error) {
      if (error && error.name === "AbortError") return;
      if (!state.open || sequence !== itemSequence) return;
      setPanelView("items-error", group);
    });
  }

  function renderSummary(payload) {
    state.summary = payload;
    setPanelView("directory");
    renderMarkers(payload);
  }

  function requestSummary() {
    if (!state.open || !state.snapshot) return Promise.resolve();
    summarySequence += 1;
    var sequence = summarySequence;
    if (state.summaryController) state.summaryController.abort();
    state.summaryController = new AbortController();
    var controller = state.summaryController;
    setStatus("Đang tải các vị trí phù hợp...", true);
    return fetchJson(buildSummaryUrl(state.snapshot), controller)
      .then(function (payload) {
        if (!state.open || sequence !== summarySequence) return;
        renderSummary(payload);
      })
      .catch(function (error) {
        if (error && error.name === "AbortError") return;
        if (!state.open || sequence !== summarySequence) return;
        setStatus("Không tải được dữ liệu vị trí.", false);
        setPanelView("summary-error");
      });
  }

  function captureDashboardState() {
    var activeTab = root.document.querySelector(".tab-content.active");
    state.previousTab = activeTab
      ? activeTab.id.replace(/^tab-/, "")
      : "signals";
    var nestedScroll = state.previousTab === "all"
      ? activeTab && activeTab.querySelector(".table-scroll")
      : null;
    state.scrollElement = nestedScroll || activeTab;
    state.scrollTop = state.scrollElement
      ? state.scrollElement.scrollTop
      : 0;
    state.previousFocus = root.document.activeElement;
  }

  function startMapLoad(safe) {
    return loadLeaflet().then(function (L) {
      if (!state.open) return;
      initMap(L);
      return requestSummary();
    }).catch(function () {
      if (!state.open) return;
      setStatus("Không thể tải thư viện bản đồ.", false);
      setPanelView("library-error");
      return undefined;
    });
  }

  function open(snapshot, options) {
    options = options || {};
    var safe = normalizedSnapshot(snapshot);
    if (!safe) return Promise.reject(new Error("Unsupported map mode"));
    var workspace = element("listingMapWorkspace");
    if (!workspace) return Promise.reject(new Error("Missing map workspace"));

    if (state.open) {
      close({ reason: "replace", skipHistory: true, restore: false });
    }
    captureDashboardState();
    state.open = true;
    state.initialSharedOpen = Boolean(options.initialSharedOpen);
    state.snapshot = safe;
    state.workspace = workspace;
    state.summary = null;
    state.selectedGroup = null;
    state.panelView = { kind: "directory", group: null, payload: null };
    state.directoryVisibleCount = DIRECTORY_BATCH_SIZE;
    setMobileSheetExpanded(false);
    workspace.hidden = false;
    root.document.body.classList.add("listing-map-open");
    var launcher = element("listingMapLauncher");
    if (launcher) launcher.setAttribute("aria-expanded", "true");
    var closeButton = element("listingMapClose");
    if (closeButton) closeButton.focus();

    if (!options.fromPopstate && !state.initialSharedOpen) {
      root.history.pushState(
        { radarListingMap: true },
        "",
        root.location.href
      );
      state.historyPushed = true;
    }
    emitTrack("listing_map_opened", {
      mode: safe.mode,
      base_layer_id: "street",
      layer_ids: ["street"]
    });

    return startMapLoad(safe);
  }

  function close(options) {
    options = options || {};
    if (!state.open) return;
    var snapshot = state.snapshot;
    var wasInitialSharedOpen = state.initialSharedOpen;
    var reason = options.reason || "button";
    var closingBaseLayer = state.activeBaseLayer;
    state.open = false;
    summarySequence += 1;
    itemSequence += 1;
    if (state.summaryController) state.summaryController.abort();
    if (state.itemController) state.itemController.abort();
    state.summaryController = null;
    state.itemController = null;
    cancelDirectoryRender();
    cancelMarkerRender();
    clearMarkerLabels();
    if (state.markerLayer) state.markerLayer.clearLayers();
    clearUserLocation();
    if (state.map) state.map.remove();
    state.map = null;
    state.markerLayer = null;
    state.markerLabelLayer = null;
    state.markerLabelGroups = [];
    state.baseLayers = {};
    state.activeBaseLayer = "street";
    clearPanels();
    setStatus("", false);
    if (state.workspace) state.workspace.hidden = true;
    setMobileSheetExpanded(false);
    root.document.body.classList.remove("listing-map-open");
    var launcher = element("listingMapLauncher");
    if (launcher) launcher.setAttribute("aria-expanded", "false");

    if (options.restore !== false) {
      var activeTab = root.document.querySelector(".tab-content.active");
      var activeTabId = activeTab
        ? activeTab.id.replace(/^tab-/, "")
        : "";
      if (
        activeTabId !== state.previousTab
        && typeof root.switchTab === "function"
      ) {
        root.switchTab(state.previousTab, null);
      }
      if (state.scrollElement) {
        state.scrollElement.scrollTop = state.scrollTop;
      }
      if (
        state.previousFocus
        && root.document.contains(state.previousFocus)
        && typeof state.previousFocus.focus === "function"
      ) {
        state.previousFocus.focus();
      }
    }
    emitTrack("listing_map_closed", {
      mode: snapshot && snapshot.mode,
      close_reason: reason,
      base_layer_id: closingBaseLayer,
      layer_ids: [closingBaseLayer]
    });
    var shouldConsumeHistory = (
      state.historyPushed
      && !options.fromPopstate
      && !options.skipHistory
      && root.history.state
      && root.history.state.radarListingMap
    );
    var shouldReplaceSharedUrl = (
      wasInitialSharedOpen
      && !options.fromPopstate
      && !options.skipHistory
    );
    state.historyPushed = false;
    state.initialSharedOpen = false;
    state.snapshot = null;
    state.summary = null;
    state.selectedGroup = null;
    state.panelView = { kind: "directory", group: null, payload: null };
    if (shouldReplaceSharedUrl) {
      root.history.replaceState(
        root.history.state,
        "",
        urlWithoutMapFlag(root.location.href)
      );
    } else if (shouldConsumeHistory) {
      root.history.back();
    }
  }

  function focusableElements() {
    if (!state.workspace) return [];
    return Array.prototype.slice.call(state.workspace.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), '
      + 'select:not([disabled]), textarea:not([disabled]), '
      + '[tabindex]:not([tabindex="-1"])'
    )).filter(function (node) {
      return !node.hidden && node.getAttribute("aria-hidden") !== "true";
    });
  }

  function isSignalModalOpen() {
    var doc = root && root.document;
    if (!doc) return false;
    var modal = doc.getElementById("signalModal");
    if (!modal) return false;
    return modal.classList.contains("show")
      || modal.style.display === "flex"
      || modal.style.display === "block";
  }

  function shouldCloseMapOnPopstate(event, isOpen) {
    if (!isOpen) return false;
    var nextState = event && event.state ? event.state : {};
    if (nextState.radarListingMap || nextState.signalModal) return false;
    return true;
  }

  function onKeydown(event) {
    if (!state.open || isSignalModalOpen()) return;
    if (event.key === "Escape") {
      event.preventDefault();
      close({ reason: "escape" });
      return;
    }
    if (event.key !== "Tab") return;
    var focusable = focusableElements();
    if (!focusable.length) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (event.shiftKey && root.document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && root.document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function bind(doc, win) {
    if (bound || !doc || !win) return;
    bound = true;
    state.mediaQuery = typeof win.matchMedia === "function"
      ? win.matchMedia(MOBILE_MEDIA_QUERY)
      : { matches: false };
    state.mediaQueryHandler = function () {
      if (!state.open) return;
      renderActiveView();
      root.setTimeout(function () {
        if (state.map) state.map.invalidateSize();
      }, 0);
    };
    if (typeof state.mediaQuery.addEventListener === "function") {
      state.mediaQuery.addEventListener("change", state.mediaQueryHandler);
    } else if (typeof state.mediaQuery.addListener === "function") {
      state.mediaQuery.addListener(state.mediaQueryHandler);
    }
    doc.addEventListener("keydown", onKeydown);
    win.addEventListener("popstate", function (event) {
      if (shouldCloseMapOnPopstate(event, state.open)) {
        close({
          reason: "browser_back",
          fromPopstate: true,
          skipHistory: true
        });
      }
    });
  }

  return {
    normalizeMode: normalizeMode,
    buildSummaryUrl: buildSummaryUrl,
    buildItemsUrl: buildItemsUrl,
    buildMapShareUrl: buildMapShareUrl,
    urlWithoutMapFlag: urlWithoutMapFlag,
    normalizeBaseLayer: normalizeBaseLayer,
    cardDateText: cardDateText,
    mapBaseLayers: mapBaseLayers,
    mapOptions: mapOptions,
    safeTrackingContext: safeTrackingContext,
    precisionCopy: precisionCopy,
    normalizeAccuracyRadius: normalizeAccuracyRadius,
    locationTargetZoom: locationTargetZoom,
    geolocationErrorMessage: geolocationErrorMessage,
    isCurrentLocationCallback: isCurrentLocationCallback,
    activePanelId: activePanelId,
    directoryWindow: directoryWindow,
    panelRenderModel: panelRenderModel,
    markerLabelModel: markerLabelModel,
    markerLabelRect: markerLabelRect,
    markerLabelClassName: markerLabelClassName,
    closerInitialZoom: closerInitialZoom,
    labelRectCollides: labelRectCollides,
    batchRanges: batchRanges,
    nextBatch: nextBatch,
    canContinueMarkerRender: canContinueMarkerRender,
    mobileSheetModel: mobileSheetModel,
    sheetExpandedForView: sheetExpandedForView,
    selectedSheetActionModel: selectedSheetActionModel,
    openListingFromMap: openListingFromMap,
    shouldCloseMapOnPopstate: shouldCloseMapOnPopstate,
    loadLeaflet: loadLeaflet,
    open: open,
    close: close,
    bind: bind
  };
});

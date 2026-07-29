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
  var LOCATION_KEY_PATTERN = /^(exact|road|ward):[a-z0-9:-]+$/;
  var SAFE_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/;
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
    baseLayers: {},
    activeBaseLayer: "street",
    summaryController: null,
    itemController: null,
    previousFocus: null,
    previousTab: "signals",
    scrollElement: null,
    scrollTop: 0,
    historyPushed: false,
    summary: null,
    selectedGroup: null
  };

  function normalizeMode(value) {
    var mode = String(value || "").toLowerCase();
    return VALID_MODES.indexOf(mode) >= 0 ? mode : null;
  }

  function normalizeBaseLayer(value) {
    var layer = String(value || "").toLowerCase();
    return VALID_BASE_LAYERS.indexOf(layer) >= 0 ? layer : "street";
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
      ward: {
        badge: "Theo trung tâm phường",
        detail: "Tin chưa đủ tên đường nên dùng điểm đại diện cấp phường."
      }
    };
    return copies[value] || {
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

  function safeCount(value) {
    var number = Number(value);
    return Number.isFinite(number) && number >= 0 ? Math.round(number) : 0;
  }

  function safeTrackingContext(input) {
    input = input || {};
    var output = {};
    var mode = normalizeMode(input.mode);
    if (mode) output.mode = mode;
    if (["exact", "road", "ward"].indexOf(input.precision) >= 0) {
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
      "listing_map_retry",
      "listing_map_official_gis_opened"
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

  function panelTargets() {
    return [
      element("listingMapPanel"),
      element("listingMapMobileSheet")
    ].filter(Boolean);
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

  function initMap(L) {
    var canvas = element("listingMapCanvas");
    if (!canvas) throw new Error("Missing listing map canvas");
    if (state.map) state.map.remove();
    state.map = L.map(canvas, {
      zoomControl: true,
      scrollWheelZoom: true
    });
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

  function renderGroupDirectory(payload) {
    var summary = payload.summary || {};
    panelTargets().forEach(function (target) {
      clearElement(target);
      var shell = create("div", "listing-map-directory");
      var stats = create("div", "listing-map-summary-grid");
      [
        ["Đã định vị", safeCount(summary.mapped)],
        ["Chưa định vị", safeCount(summary.unmapped_count)],
        ["Theo đường", safeCount(summary.road_count)],
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
      (payload.locations || []).forEach(function (group) {
        list.appendChild(groupButton(group));
      });
      if (!list.childNodes.length) {
        list.appendChild(create(
          "p",
          "listing-map-empty",
          "Bộ lọc hiện tại chưa có lô đất xác định được vị trí."
        ));
      }
      shell.appendChild(list);
      target.appendChild(shell);
    });
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

  function renderMarkers(payload) {
    if (!state.map || !state.markerLayer) return;
    state.markerLayer.clearLayers();
    var bounds = [];
    (payload.locations || []).forEach(function (group) {
      var lat = Number(group.lat);
      var lng = Number(group.lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
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
      bounds.push([lat, lng]);
    });
    if (bounds.length) {
      state.map.fitBounds(bounds, {
        padding: [38, 38],
        maxZoom: 16
      });
    } else {
      state.map.setView([11.02, 106.63], 11);
    }
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

  function renderItems(group, payload) {
    panelTargets().forEach(function (target) {
      clearElement(target);
      var shell = create("div", "listing-map-items");
      var back = create(
        "button",
        "listing-map-back",
        "← Tất cả vị trí"
      );
      back.type = "button";
      back.addEventListener("click", function () {
        renderGroupDirectory(state.summary || {
          summary: {},
          locations: []
        });
      });
      shell.appendChild(back);
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
            Number(item.days_ago) <= 0
              ? "Hôm nay"
              : Number(item.days_ago) + " ngày trước"
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
    });
  }

  function renderItemsLoading(group) {
    panelTargets().forEach(function (target) {
      clearElement(target);
      var shell = create("div", "listing-map-panel-loading");
      shell.appendChild(create("strong", "", group.label));
      shell.appendChild(create("span", "", "Đang tải các lô đất..."));
      target.appendChild(shell);
    });
  }

  function selectGroup(group) {
    if (!state.open || !state.snapshot) return;
    state.selectedGroup = group;
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
    renderItemsLoading(group);
    emitTrack("listing_map_group_selected", {
      mode: state.snapshot.mode,
      precision: group.precision,
      listing_count: group.listing_count,
      base_layer_id: state.activeBaseLayer,
      layer_ids: [state.activeBaseLayer]
    });
    fetchJson(url, controller).then(function (payload) {
      if (!state.open || sequence !== itemSequence) return;
      renderItems(group, payload);
    }).catch(function (error) {
      if (error && error.name === "AbortError") return;
      if (!state.open || sequence !== itemSequence) return;
      panelTargets().forEach(function (target) {
        renderRetry(
          target,
          "Không tải được các lô đất tại vị trí này.",
          function () { selectGroup(group); },
          {
            mode: state.snapshot.mode,
            precision: group.precision,
            listing_count: group.listing_count
          }
        );
      });
    });
  }

  function renderSummary(payload) {
    state.summary = payload;
    renderMarkers(payload);
    renderGroupDirectory(payload);
    var summary = payload.summary || {};
    setStatus(
      "Đã định vị " + safeCount(summary.mapped) + "/"
        + safeCount(summary.total) + " tin; "
        + safeCount(summary.unmapped_count) + " tin chưa đủ vị trí.",
      false
    );
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
        panelTargets().forEach(function (target) {
          renderRetry(
            target,
            "Không tải được dữ liệu bản đồ.",
            requestSummary,
            { mode: state.snapshot.mode }
          );
        });
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
      panelTargets().forEach(function (target) {
        renderRetry(
          target,
          "Bản đồ chưa tải được. Danh sách tin vẫn hoạt động bình thường.",
          function () { startMapLoad(safe); },
          { mode: safe.mode }
        );
      });
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
    state.snapshot = safe;
    state.workspace = workspace;
    state.summary = null;
    state.selectedGroup = null;
    workspace.hidden = false;
    root.document.body.classList.add("listing-map-open");
    var launcher = element("listingMapLauncher");
    if (launcher) launcher.setAttribute("aria-expanded", "true");
    var closeButton = element("listingMapClose");
    if (closeButton) closeButton.focus();

    if (!options.fromPopstate) {
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
    var reason = options.reason || "button";
    var closingBaseLayer = state.activeBaseLayer;
    state.open = false;
    summarySequence += 1;
    itemSequence += 1;
    if (state.summaryController) state.summaryController.abort();
    if (state.itemController) state.itemController.abort();
    state.summaryController = null;
    state.itemController = null;
    if (state.markerLayer) state.markerLayer.clearLayers();
    if (state.map) state.map.remove();
    state.map = null;
    state.markerLayer = null;
    state.baseLayers = {};
    state.activeBaseLayer = "street";
    panelTargets().forEach(clearElement);
    setStatus("", false);
    if (state.workspace) state.workspace.hidden = true;
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
    state.historyPushed = false;
    state.snapshot = null;
    state.summary = null;
    state.selectedGroup = null;
    if (shouldConsumeHistory) root.history.back();
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
    doc.addEventListener("keydown", onKeydown);
    var officialGisLink = doc.getElementById("listingMapOfficialGisLink");
    if (officialGisLink) {
      officialGisLink.addEventListener("click", function () {
        emitTrack("listing_map_official_gis_opened", {
          mode: state.snapshot && state.snapshot.mode
        });
      });
    }
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
    normalizeBaseLayer: normalizeBaseLayer,
    mapBaseLayers: mapBaseLayers,
    safeTrackingContext: safeTrackingContext,
    precisionCopy: precisionCopy,
    openListingFromMap: openListingFromMap,
    shouldCloseMapOnPopstate: shouldCloseMapOnPopstate,
    loadLeaflet: loadLeaflet,
    open: open,
    close: close,
    bind: bind
  };
});

(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root && root.document) {
    root.RadarBinhDuongMap = api;
    var start = function () {
      api.init(root.document, root);
    };
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
      start();
    }
  }
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";

  var VALID_LAYERS = ["legacy", "current"];
  var VALID_BASE_LAYERS = ["street", "satellite"];
  var SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

  function normalizeLayer(value) {
    return VALID_LAYERS.indexOf(String(value || "")) !== -1
      ? String(value)
      : "legacy";
  }

  function normalizeBaseLayer(value) {
    return VALID_BASE_LAYERS.indexOf(String(value || "")) !== -1
      ? String(value)
      : "street";
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
          "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, "
          + "and the GIS User Community"
        )
      }
    };
  }

  function parseMapHash(hash, validSlugs) {
    var decoded;
    try {
      decoded = decodeURIComponent(String(hash || ""));
    } catch (error) {
      return { layer: "legacy", areaSlug: null };
    }
    var match = decoded.match(
      /^#layer-(legacy|current)(?:\/area-([a-z0-9]+(?:-[a-z0-9]+)*))?$/
    );
    if (!match) return { layer: "legacy", areaSlug: null };

    var layer = match[1];
    var areaSlug = match[2] || null;
    if (
      areaSlug
      && validSlugs
      && Array.isArray(validSlugs[layer])
      && validSlugs[layer].indexOf(areaSlug) === -1
    ) {
      return { layer: "legacy", areaSlug: null };
    }
    return { layer: layer, areaSlug: areaSlug };
  }

  function formatMapHash(layer, areaSlug) {
    var normalized = normalizeLayer(layer);
    var safeSlug = String(areaSlug || "");
    if (!SLUG_PATTERN.test(safeSlug)) {
      return "#layer-" + normalized;
    }
    return "#layer-" + normalized + "/area-" + safeSlug;
  }

  function buildTrackingContext(layer, feature, target) {
    var properties = (feature && feature.properties) || {};
    return {
      layer: normalizeLayer(layer),
      area_slug: SLUG_PATTERN.test(String(properties.slug || ""))
        ? String(properties.slug)
        : "",
      target: String(target || "")
    };
  }

  function filterFeatureCollection(payload, layer) {
    var normalized = normalizeLayer(layer);
    var features = payload && Array.isArray(payload.features)
      ? payload.features
      : [];
    return {
      type: "FeatureCollection",
      features: features.filter(function (feature) {
        var properties = (feature && feature.properties) || {};
        var geometry = (feature && feature.geometry) || {};
        return (
          feature
          && feature.type === "Feature"
          && properties.layer === normalized
          && SLUG_PATTERN.test(String(properties.slug || ""))
          && (geometry.type === "Polygon" || geometry.type === "MultiPolygon")
        );
      })
    };
  }

  function matchesExpectedSlugs(collection, expectedSlugs) {
    var actual = ((collection && collection.features) || []).map(function (feature) {
      return String((feature.properties || {}).slug || "");
    }).sort();
    var expected = (Array.isArray(expectedSlugs) ? expectedSlugs : [])
      .map(String)
      .slice()
      .sort();
    return (
      actual.length === expected.length
      && actual.every(function (slug, index) {
        return slug === expected[index];
      })
    );
  }

  function emitTrack(win, action, context) {
    if (!win || typeof win.CustomEvent !== "function") return;
    try {
      win.dispatchEvent(new win.CustomEvent("radar:track", {
        detail: { action: action, context: context || {} }
      }));
    } catch (error) {
      // Analytics must never block map interaction.
    }
  }

  function mapOptions() {
    return {
      scrollWheelZoom: true,
      zoomControl: true
    };
  }

  function fullscreenElement(doc) {
    if (!doc) return null;
    return doc.fullscreenElement || doc.webkitFullscreenElement || null;
  }

  function toggleMapFullscreen(element, doc) {
    if (!element || !doc) return "unavailable";

    if (fullscreenElement(doc) === element) {
      var exit = doc.exitFullscreen || doc.webkitExitFullscreen;
      if (typeof exit !== "function") return "unavailable";
      var exitResult = exit.call(doc);
      if (exitResult && typeof exitResult.catch === "function") {
        exitResult.catch(function () {});
      }
      return "exit";
    }

    var enter = element.requestFullscreen || element.webkitRequestFullscreen;
    if (typeof enter !== "function") return "unavailable";
    var enterResult = enter.call(element);
    if (enterResult && typeof enterResult.catch === "function") {
      enterResult.catch(function () {});
    }
    return "enter";
  }

  function handleFullscreenEscape(event, element, doc) {
    if (
      !event
      || event.key !== "Escape"
      || fullscreenElement(doc) !== element
    ) {
      return false;
    }
    toggleMapFullscreen(element, doc);
    return true;
  }

  function init(doc, win) {
    var root = doc.querySelector("[data-binh-duong-map]");
    if (!root) return;

    var canvas = root.querySelector("[data-binh-duong-map-canvas]");
    var status = root.querySelector("[data-binh-duong-map-status]");
    var fallback = root.querySelector("[data-binh-duong-map-fallback]");
    var retryButton = root.querySelector("[data-binh-duong-map-retry]");
    var fullscreenTarget = root.querySelector(
      "[data-binh-duong-map-fullscreen-target]"
    );
    var fullscreenButton = root.querySelector(
      "[data-binh-duong-map-fullscreen]"
    );
    var fullscreenLabel = root.querySelector("[data-map-fullscreen-label]");
    var layerButtons = Array.prototype.slice.call(
      root.querySelectorAll("[data-map-layer]")
    );
    var baseLayerButtons = Array.prototype.slice.call(
      root.querySelectorAll("[data-map-base-layer]")
    );
    var areaButtons = Array.prototype.slice.call(
      doc.querySelectorAll("[data-map-area-button]")
    );
    var directoryItems = Array.prototype.slice.call(
      doc.querySelectorAll("[data-map-directory-item]")
    );
    var searchInput = doc.querySelector("[data-map-area-search]");
    var searchStatus = doc.querySelector("[data-map-search-status]");
    var searchReset = doc.querySelector("[data-map-search-reset]");
    var searchEmpty = doc.querySelector("[data-map-search-empty]");
    var copyButton = root.querySelector("[data-map-copy-link]");
    var mobileCta = doc.querySelector("[data-map-mobile-cta]");
    var hero = doc.querySelector(".bd-map-hero");

    var validSlugs = { legacy: [], current: [] };
    areaButtons.forEach(function (button) {
      var layer = normalizeLayer(button.getAttribute("data-layer"));
      var slug = button.getAttribute("data-area-slug") || "";
      if (SLUG_PATTERN.test(slug) && validSlugs[layer].indexOf(slug) === -1) {
        validSlugs[layer].push(slug);
      }
    });

    var urls = {
      legacy: root.getAttribute("data-legacy-geojson") || "",
      current: root.getAttribute("data-current-geojson") || ""
    };
    var datasets = { legacy: null, current: null };
    var map = null;
    var baseTileLayer = null;
    var activeBaseLayer = "street";
    var boundaryLayer = null;
    var featureLayers = {};
    var activeState = { layer: "legacy", areaSlug: null };
    var searchTimer = null;
    var copyResetTimer = null;

    function normalizeSearchValue(value) {
      var text = String(value || "").toLowerCase();
      if (typeof text.normalize === "function") {
        text = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
      }
      return text.replace(/\s+/g, " ").trim();
    }

    function filterDirectoryItems() {
      var query = normalizeSearchValue(searchInput && searchInput.value);
      var visibleCount = 0;
      directoryItems.forEach(function (item) {
        var haystack = normalizeSearchValue(item.textContent || "");
        var matched = !query || haystack.indexOf(query) !== -1;
        item.hidden = !matched;
        if (matched) visibleCount += 1;
      });
      if (searchStatus) {
        searchStatus.textContent = query
          ? "Tìm thấy " + visibleCount + " khu vực phù hợp."
          : "Đang hiển thị " + directoryItems.length + " khu vực.";
      }
      if (searchEmpty) searchEmpty.hidden = visibleCount !== 0;
    }

    function copySelectionLink() {
      if (!copyButton) return;
      var hash = win.location.hash || formatMapHash(activeState.layer, activeState.areaSlug);
      var url = win.location.origin + win.location.pathname + hash;
      var done = function () {
        copyButton.textContent = "Đã sao chép";
        copyButton.setAttribute("aria-label", "Đã sao chép liên kết khu vực");
        if (copyResetTimer) win.clearTimeout(copyResetTimer);
        copyResetTimer = win.setTimeout(function () {
          copyButton.textContent = "Sao chép liên kết khu vực";
          copyButton.setAttribute("aria-label", "Sao chép liên kết khu vực");
        }, 1800);
      };
      var failed = function () {
        copyButton.textContent = "Không sao chép được";
        if (copyResetTimer) win.clearTimeout(copyResetTimer);
        copyResetTimer = win.setTimeout(function () {
          copyButton.textContent = "Sao chép liên kết khu vực";
        }, 1800);
      };
      if (win.navigator && win.navigator.clipboard && win.navigator.clipboard.writeText) {
        win.navigator.clipboard.writeText(url).then(done).catch(failed);
        return;
      }
      try {
        var textarea = doc.createElement("textarea");
        textarea.value = url;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.left = "-9999px";
        doc.body.appendChild(textarea);
        textarea.select();
        if (!doc.execCommand("copy")) throw new Error("copy_failed");
        doc.body.removeChild(textarea);
        done();
      } catch (error) {
        failed();
      }
    }

    function updateMobileCta(visible) {
      if (!mobileCta) return;
      mobileCta.classList.toggle("is-visible", visible);
      mobileCta.setAttribute("aria-hidden", visible ? "false" : "true");
    }

    if (mobileCta && hero && typeof win.IntersectionObserver === "function") {
      new win.IntersectionObserver(function (entries) {
        updateMobileCta(!entries[0].isIntersecting);
      }, { threshold: 0 }).observe(hero);
    } else if (mobileCta && hero) {
      var syncMobileCta = function () {
        updateMobileCta(hero.getBoundingClientRect().bottom <= 0);
      };
      win.addEventListener("scroll", syncMobileCta, { passive: true });
      syncMobileCta();
    }

    function setStatus(message) {
      if (status) status.textContent = message;
    }

    function setFallback(visible) {
      if (fallback) fallback.hidden = !visible;
      if (canvas) canvas.setAttribute("aria-hidden", visible ? "true" : "false");
    }

    function layerDefault(layer, key, fallbackValue) {
      return root.getAttribute("data-" + layer + "-" + key) || fallbackValue;
    }

    function syncFullscreenState() {
      var active = fullscreenElement(doc) === fullscreenTarget;
      if (fullscreenButton) {
        fullscreenButton.setAttribute("aria-pressed", active ? "true" : "false");
        fullscreenButton.setAttribute(
          "aria-label",
          active ? "Thoát chế độ toàn màn hình" : "Mở bản đồ toàn màn hình"
        );
      }
      if (fullscreenLabel) {
        fullscreenLabel.textContent = active ? "Thoát toàn màn hình" : "Toàn màn hình";
      }
      root.classList.toggle("is-map-fullscreen", active);
      if (map) {
        win.setTimeout(function () {
          map.invalidateSize();
        }, 80);
      }
    }

    function fetchJson(url) {
      return win.fetch(url, {
        credentials: "same-origin",
        headers: { Accept: "application/geo+json, application/json" }
      }).then(function (response) {
        if (!response.ok) throw new Error("geojson_http_" + response.status);
        return response.json();
      });
    }

    function featureFor(layer, slug) {
      var collection = datasets[layer];
      if (!collection || !slug) return null;
      return collection.features.find(function (feature) {
        return feature.properties.slug === slug;
      }) || null;
    }

    function updateLayerButtons(layer) {
      layerButtons.forEach(function (button) {
        var selected = button.getAttribute("data-map-layer") === layer;
        button.setAttribute("aria-pressed", selected ? "true" : "false");
        button.classList.toggle("is-active", selected);
      });
      root.setAttribute("data-active-layer", layer);
    }

    function updateBaseLayerButtons(baseLayer) {
      baseLayerButtons.forEach(function (button) {
        var selected = button.getAttribute("data-map-base-layer") === baseLayer;
        button.setAttribute("aria-pressed", selected ? "true" : "false");
        button.classList.toggle("is-active", selected);
      });
      root.setAttribute("data-active-base-layer", baseLayer);
    }

    function updateDirectorySelection(layer, areaSlug) {
      directoryItems.forEach(function (item) {
        var selected = (
          item.getAttribute("data-map-directory-item") === layer
          && item.getAttribute("data-area-slug") === areaSlug
        );
        item.classList.toggle("is-selected", selected);
      });
      areaButtons.forEach(function (button) {
        var selected = (
          button.getAttribute("data-layer") === layer
          && button.getAttribute("data-area-slug") === areaSlug
        );
        button.setAttribute("aria-pressed", selected ? "true" : "false");
      });
    }

    function updateSelectionPanel(layer, feature) {
      var properties = (feature && feature.properties) || {};
      var name = root.querySelector("[data-map-selection-name]");
      var type = root.querySelector("[data-map-selection-type]");
      var summary = root.querySelector("[data-map-selection-summary]");
      var group = root.querySelector("[data-map-selection-group]");
      var formerRow = root.querySelector("[data-map-selection-former-row]");
      var former = root.querySelector("[data-map-selection-former]");
      var cta = root.querySelector("[data-map-selection-cta]");

      if (!feature) {
        if (name) name.textContent = layer === "current"
          ? layerDefault("current", "selection-name", "36 phường, xã sau sắp xếp")
          : layerDefault("legacy", "selection-name", "Toàn tỉnh Bình Dương cũ");
        if (type) type.textContent = layer === "current"
          ? layerDefault("current", "selection-type", "Địa giới tham khảo sau năm 2025")
          : layerDefault("legacy", "selection-type", "9 đơn vị cấp huyện trước sắp xếp");
        if (summary) summary.textContent = (
          "Chọn một ranh trên bản đồ hoặc tên khu vực trong danh sách để xem thông tin chi tiết."
        );
        if (group) group.textContent = "Toàn khu vực";
        if (formerRow) formerRow.hidden = true;
        if (former) former.textContent = "";
        if (cta) {
          cta.href = layerDefault(layer, "cta-href", "/?tab=signals");
          cta.textContent = layerDefault(layer, "cta-label", "Xem tin đang bán");
        }
        return;
      }

      if (name) name.textContent = properties.name || "Khu vực đã chọn";
      if (type) type.textContent = properties.unit_type || "";
      if (summary) summary.textContent = properties.summary || "";
      if (group) group.textContent = properties.group || properties.name || "";
      if (formerRow) formerRow.hidden = !properties.former_units;
      if (former) former.textContent = properties.former_units || "";
      if (cta) {
        cta.href = properties.dashboard_href || "/?tab=signals";
        cta.textContent = properties.dashboard_label || "Xem tin đang bán";
      }
    }

    function baseStyle(layer) {
      var color = layer === "legacy" ? "#0f766e" : "#0369a1";
      return {
        color: color,
        fillColor: color,
        fillOpacity: 0.14,
        opacity: 0.95,
        weight: 2
      };
    }

    function selectedStyle() {
      return {
        color: "#0f172a",
        fillColor: "#14b8a6",
        fillOpacity: 0.38,
        opacity: 1,
        weight: 4
      };
    }

    function fitBounds(layer, options) {
      if (!map || !layer || typeof layer.getBounds !== "function") return;
      var bounds = layer.getBounds();
      if (!bounds || !bounds.isValid || !bounds.isValid()) return;
      map.fitBounds(bounds, options || { padding: [24, 24], maxZoom: 12 });
    }

    function drawLayer(layer, areaSlug) {
      if (!map || !datasets[layer]) return;
      if (boundaryLayer) map.removeLayer(boundaryLayer);
      featureLayers = {};
      boundaryLayer = win.L.geoJSON(datasets[layer], {
        style: function () {
          return baseStyle(layer);
        },
        onEachFeature: function (feature, leafletLayer) {
          var slug = feature.properties.slug;
          featureLayers[slug] = leafletLayer;
          leafletLayer.bindTooltip(feature.properties.name || "", {
            sticky: true,
            direction: "top"
          });
          leafletLayer.on("click", function () {
            selectArea(layer, slug, {
              updateHash: true,
              track: true,
              scroll: false
            });
          });
        }
      }).addTo(map);

      fitBounds(boundaryLayer, { padding: [28, 28], maxZoom: 11 });
      if (areaSlug && featureLayers[areaSlug]) {
        featureLayers[areaSlug].setStyle(selectedStyle());
        fitBounds(featureLayers[areaSlug], { padding: [38, 38], maxZoom: 13 });
      }
    }

    function renderState(state) {
      var layer = normalizeLayer(state.layer);
      var areaSlug = state.areaSlug || null;
      var feature = featureFor(layer, areaSlug);
      if (areaSlug && !feature) areaSlug = null;
      activeState = { layer: layer, areaSlug: areaSlug };

      updateLayerButtons(layer);
      drawLayer(layer, areaSlug);
      updateDirectorySelection(layer, areaSlug);
      updateSelectionPanel(layer, feature);
      setStatus(
        feature
          ? "Đang xem " + (feature.properties.unit_type || "khu vực") + " " + feature.properties.name + "."
          : layer === "current"
            ? layerDefault("current", "status", "Đang hiển thị 36 phường, xã sau sắp xếp năm 2025.")
            : layerDefault("legacy", "status", "Đang hiển thị 9 huyện, thành phố của Bình Dương cũ.")
      );
    }

    function setHash(nextHash) {
      if (win.location.hash === nextHash) {
        renderState(parseMapHash(nextHash, validSlugs));
      } else {
        win.location.hash = nextHash;
      }
    }

    function selectArea(layer, slug, options) {
      var feature = featureFor(layer, slug);
      if (!feature) return;
      var nextHash = formatMapHash(layer, slug);
      if (options && options.updateHash) {
        setHash(nextHash);
      } else {
        renderState({ layer: layer, areaSlug: slug });
      }
      if (options && options.scroll) {
        var reduceMotion = (
          win.matchMedia
          && win.matchMedia("(prefers-reduced-motion: reduce)").matches
        );
        root.scrollIntoView({
          behavior: reduceMotion ? "auto" : "smooth",
          block: "start"
        });
      }
      if (options && options.track) {
        emitTrack(
          win,
          "binh_duong_map_area_selected",
          buildTrackingContext(
            layer,
            feature,
            feature.properties.dashboard_href || "/?tab=signals"
          )
        );
      }
    }

    function initializeMap() {
      if (!canvas || !win.L) {
        throw new Error("leaflet_unavailable");
      }
      if (!map) {
        map = win.L.map(canvas, mapOptions());
        setBaseLayer(activeBaseLayer, { track: false });
      }
      setFallback(false);
      renderState(parseMapHash(win.location.hash, validSlugs));
      win.setTimeout(function () {
        map.invalidateSize();
        renderState(activeState);
      }, 180);
    }

    function loadMap() {
      setFallback(false);
      setStatus("Đang tải dữ liệu địa giới…");
      return Promise.all([
        fetchJson(urls.legacy),
        fetchJson(urls.current)
      ]).then(function (payloads) {
        datasets.legacy = filterFeatureCollection(payloads[0], "legacy");
        datasets.current = filterFeatureCollection(payloads[1], "current");
        if (
          !matchesExpectedSlugs(datasets.legacy, validSlugs.legacy)
          || !matchesExpectedSlugs(datasets.current, validSlugs.current)
        ) {
          throw new Error("incomplete_geojson");
        }
        initializeMap();
      }).catch(function () {
        setStatus("Chưa tải được bản đồ tương tác. Danh sách khu vực bên dưới vẫn dùng được.");
        setFallback(true);
      });
    }

    function setBaseLayer(baseLayer, options) {
      if (!map || !win.L) return;
      var normalized = normalizeBaseLayer(baseLayer);
      var layers = mapBaseLayers();
      var config = layers[normalized] || layers.street;
      if (baseTileLayer) {
        map.removeLayer(baseTileLayer);
      }
      baseTileLayer = win.L.tileLayer(config.url, {
        maxZoom: config.maxZoom,
        attribution: config.attribution
      }).addTo(map);
      activeBaseLayer = normalized;
      updateBaseLayerButtons(normalized);
      if (options && options.track) {
        emitTrack(
          win,
          "binh_duong_map_base_layer_selected",
          { base_layer: normalized }
        );
      }
    }

    layerButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        var layer = normalizeLayer(button.getAttribute("data-map-layer"));
        setHash(formatMapHash(layer, null));
        emitTrack(
          win,
          "binh_duong_map_layer_selected",
          { layer: layer, area_slug: "", target: "" }
        );
      });
    });

    baseLayerButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        setBaseLayer(button.getAttribute("data-map-base-layer"), { track: true });
      });
    });

    if (searchInput) {
      searchInput.addEventListener("input", function () {
        if (searchTimer) win.clearTimeout(searchTimer);
        searchTimer = win.setTimeout(filterDirectoryItems, 120);
      });
      filterDirectoryItems();
    }

    if (searchReset) {
      searchReset.addEventListener("click", function () {
        if (searchInput) searchInput.value = "";
        filterDirectoryItems();
        if (searchInput) searchInput.focus();
      });
    }

    if (copyButton) {
      copyButton.setAttribute("aria-label", "Sao chép liên kết khu vực");
      copyButton.addEventListener("click", copySelectionLink);
    }

    areaButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        selectArea(
          normalizeLayer(button.getAttribute("data-layer")),
          button.getAttribute("data-area-slug") || "",
          { updateHash: true, track: true, scroll: true }
        );
      });
    });

    if (retryButton) retryButton.addEventListener("click", loadMap);
    if (fullscreenButton && fullscreenTarget) {
      var supportsFullscreen = (
        typeof fullscreenTarget.requestFullscreen === "function"
        || typeof fullscreenTarget.webkitRequestFullscreen === "function"
      );
      fullscreenButton.hidden = !supportsFullscreen;
      if (supportsFullscreen) {
        fullscreenButton.addEventListener("click", function () {
          toggleMapFullscreen(fullscreenTarget, doc);
        });
        doc.addEventListener("keydown", function (event) {
          handleFullscreenEscape(event, fullscreenTarget, doc);
        });
        doc.addEventListener("fullscreenchange", syncFullscreenState);
        doc.addEventListener("webkitfullscreenchange", syncFullscreenState);
        syncFullscreenState();
      }
    }
    win.addEventListener("hashchange", function () {
      renderState(parseMapHash(win.location.hash, validSlugs));
    });

    root.classList.add("is-enhanced");
    loadMap();
  }

  return {
    normalizeLayer: normalizeLayer,
    normalizeBaseLayer: normalizeBaseLayer,
    mapBaseLayers: mapBaseLayers,
    parseMapHash: parseMapHash,
    formatMapHash: formatMapHash,
    buildTrackingContext: buildTrackingContext,
    filterFeatureCollection: filterFeatureCollection,
    matchesExpectedSlugs: matchesExpectedSlugs,
    mapOptions: mapOptions,
    toggleMapFullscreen: toggleMapFullscreen,
    handleFullscreenEscape: handleFullscreenEscape,
    init: init
  };
});

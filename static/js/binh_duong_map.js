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
  var SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

  function normalizeLayer(value) {
    return VALID_LAYERS.indexOf(String(value || "")) !== -1
      ? String(value)
      : "legacy";
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

  function init(doc, win) {
    var root = doc.querySelector("[data-binh-duong-map]");
    if (!root) return;

    var canvas = root.querySelector("[data-binh-duong-map-canvas]");
    var status = root.querySelector("[data-binh-duong-map-status]");
    var fallback = root.querySelector("[data-binh-duong-map-fallback]");
    var retryButton = root.querySelector("[data-binh-duong-map-retry]");
    var layerButtons = Array.prototype.slice.call(
      root.querySelectorAll("[data-map-layer]")
    );
    var areaButtons = Array.prototype.slice.call(
      doc.querySelectorAll("[data-map-area-button]")
    );
    var directoryItems = Array.prototype.slice.call(
      doc.querySelectorAll("[data-map-directory-item]")
    );
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
    var boundaryLayer = null;
    var featureLayers = {};
    var activeState = { layer: "legacy", areaSlug: null };

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
          ? "36 phường, xã sau sắp xếp"
          : "Toàn tỉnh Bình Dương cũ";
        if (type) type.textContent = layer === "current"
          ? "Địa giới tham khảo sau năm 2025"
          : "9 đơn vị cấp huyện trước sắp xếp";
        if (summary) summary.textContent = (
          "Chọn một ranh trên bản đồ hoặc tên khu vực trong danh sách để xem thông tin chi tiết."
        );
        if (group) group.textContent = "Toàn khu vực";
        if (formerRow) formerRow.hidden = true;
        if (former) former.textContent = "";
        if (cta) {
          cta.href = "/?tab=signals";
          cta.textContent = "Xem tin đang bán";
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
            ? "Đang hiển thị 36 phường, xã sau sắp xếp năm 2025."
            : "Đang hiển thị 9 huyện, thành phố của Bình Dương cũ."
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
        map = win.L.map(canvas, {
          scrollWheelZoom: false,
          zoomControl: true
        });
        win.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 19,
          attribution: (
            '&copy; <a href="https://www.openstreetmap.org/copyright">'
            + "OpenStreetMap</a> contributors"
          )
        }).addTo(map);
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
    win.addEventListener("hashchange", function () {
      renderState(parseMapHash(win.location.hash, validSlugs));
    });

    root.classList.add("is-enhanced");
    loadMap();
  }

  return {
    normalizeLayer: normalizeLayer,
    parseMapHash: parseMapHash,
    formatMapHash: formatMapHash,
    buildTrackingContext: buildTrackingContext,
    filterFeatureCollection: filterFeatureCollection,
    matchesExpectedSlugs: matchesExpectedSlugs,
    init: init
  };
});

(function () {
  function postTrack(action, context) {
    try {
      fetch("/api/track", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action, context: context || {} }),
        keepalive: true
      }).catch(function () {});
    } catch (err) {
      // Tracking must never block map usage.
    }
  }

  function layerColor(feature, fallback) {
    return (feature && feature.properties && feature.properties.color) || fallback || "#0f766e";
  }

  function popupNode(feature) {
    var props = (feature && feature.properties) || {};
    var node = document.createElement("div");
    var title = document.createElement("strong");
    var text = document.createElement("p");
    title.textContent = props.name || "Lớp bản đồ";
    text.textContent = props.description || "Lớp minh họa quy hoạch Radar BDS.";
    node.className = "planning-map-popup";
    node.appendChild(title);
    node.appendChild(text);
    return node;
  }

  function fitLayer(map, layer, options) {
    if (!layer || !map) return;
    if (typeof layer.getBounds === "function") {
      var bounds = layer.getBounds();
      if (bounds && bounds.isValid && bounds.isValid()) {
        map.fitBounds(bounds, options || { padding: [28, 28], maxZoom: 14 });
      }
    } else if (typeof layer.getLatLng === "function") {
      map.setView(layer.getLatLng(), 14);
    }
  }

  function initPlanningMap(mapEl) {
    var panel = mapEl.closest("[data-planning-map-panel]");
    var status = panel ? panel.querySelector("[data-planning-map-status]") : null;
    var geojsonUrl = mapEl.getAttribute("data-geojson");
    var pagePath = mapEl.getAttribute("data-page-path") || window.location.pathname;
    var mapTitle = mapEl.getAttribute("data-map-title") || document.title;

    if (!geojsonUrl || !panel) return;
    if (!window.L) {
      if (status) status.textContent = "Không tải được thư viện bản đồ.";
      return;
    }

    var map = L.map(mapEl, {
      scrollWheelZoom: false,
      zoomControl: true
    });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    var layerGroups = {};
    var visibleLayers = {};
    var featureIndex = {};
    var allFeatureLayers = [];

    function ensureGroup(layerId) {
      if (!layerGroups[layerId]) {
        layerGroups[layerId] = L.layerGroup();
        visibleLayers[layerId] = true;
      }
      return layerGroups[layerId];
    }

    function registerFeature(feature, layer) {
      var props = feature.properties || {};
      var keys = [props.focusKey, props.name].filter(Boolean);
      keys.forEach(function (key) {
        featureIndex[String(key).toLowerCase()] = layer;
      });
    }

    fetch(geojsonUrl)
      .then(function (response) {
        if (!response.ok) throw new Error("geojson");
        return response.json();
      })
      .then(function (data) {
        (data.features || []).forEach(function (feature) {
          var layerId = (feature.properties && feature.properties.layer) || "route";
          var group = ensureGroup(layerId);
          var geoLayer = L.geoJSON(feature, {
            style: function (item) {
              var color = layerColor(item, "#0f766e");
              return {
                color: color,
                fillColor: color,
                fillOpacity: layerId === "impact" || layerId === "boundary" || layerId === "industrial" ? 0.16 : 0.08,
                weight: layerId === "route" ? 5 : 2,
                opacity: 0.92
              };
            },
            pointToLayer: function (item, latlng) {
              return L.circleMarker(latlng, {
                radius: layerId === "signals" ? 7 : 8,
                color: "#ffffff",
                weight: 2,
                fillColor: layerColor(item, "#0369a1"),
                fillOpacity: 0.95
              });
            },
            onEachFeature: function (item, layer) {
              layer.bindPopup(popupNode(item));
              registerFeature(item, layer);
            }
          });
          geoLayer.addTo(group);
          allFeatureLayers.push(geoLayer);
        });

        Object.keys(layerGroups).forEach(function (layerId) {
          var input = panel.querySelector('[data-map-layer="' + layerId + '"]');
          visibleLayers[layerId] = !input || input.checked;
          if (visibleLayers[layerId]) layerGroups[layerId].addTo(map);
        });

        var combined = L.featureGroup(allFeatureLayers);
        fitLayer(map, combined, { padding: [32, 32], maxZoom: 13 });
        window.setTimeout(function () {
          map.invalidateSize();
          fitLayer(map, combined, { padding: [32, 32], maxZoom: 13 });
        }, 250);
        window.setTimeout(function () {
          map.invalidateSize();
          fitLayer(map, combined, { padding: [32, 32], maxZoom: 13 });
        }, 900);
        if (status) status.hidden = true;
      })
      .catch(function () {
        if (status) status.textContent = "Chưa tải được lớp GeoJSON. Vui lòng tải lại trang.";
      });

    panel.querySelectorAll("[data-map-layer]").forEach(function (input) {
      input.addEventListener("change", function () {
        var layerId = input.getAttribute("data-map-layer");
        var group = layerGroups[layerId];
        if (!group) return;
        if (input.checked) {
          group.addTo(map);
        } else {
          map.removeLayer(group);
        }
        postTrack("map_layer_toggled", {
          layer: layerId,
          checked: input.checked,
          page: pagePath,
          map: mapTitle
        });
      });
    });

    var fullscreenButton = panel.querySelector("[data-map-fullscreen]");
    if (fullscreenButton) {
      fullscreenButton.addEventListener("click", function () {
        panel.classList.toggle("is-map-fullscreen");
        document.body.classList.toggle("planning-map-fullscreen-open", panel.classList.contains("is-map-fullscreen"));
        fullscreenButton.textContent = panel.classList.contains("is-map-fullscreen") ? "Thu nhỏ" : "Toàn màn hình";
        window.setTimeout(function () {
          map.invalidateSize();
          if (allFeatureLayers.length) fitLayer(map, L.featureGroup(allFeatureLayers), { padding: [32, 32], maxZoom: 13 });
        }, 120);
        postTrack("map_fullscreen_clicked", { page: pagePath, map: mapTitle });
      });
    }

    document.querySelectorAll("[data-map-focus]").forEach(function (button) {
      button.addEventListener("click", function () {
        var key = String(button.getAttribute("data-map-focus") || "").toLowerCase();
        var layer = featureIndex[key];
        if (layer) {
          fitLayer(map, layer, { padding: [42, 42], maxZoom: 14 });
          if (typeof layer.openPopup === "function") layer.openPopup();
        }
      });
    });
  }

  function initAreaCtas() {
    document.querySelectorAll("[data-map-area-cta]").forEach(function (link) {
      link.addEventListener("click", function () {
        postTrack("map_area_cta_clicked", {
          page: window.location.pathname,
          target: link.getAttribute("href") || "",
          context: link.getAttribute("data-cta-context") || ""
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initAreaCtas();
    document.querySelectorAll("[data-planning-map]").forEach(initPlanningMap);
  });
})();

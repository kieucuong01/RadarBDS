(function (root, factory) {
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root && root.document) root.RadarDetailLocationMap = api;
})(typeof window !== 'undefined' ? window : null, function (root) {
  'use strict';

  var leafletPromise = null;
  var PRECISION_COPY = {
    exact: {
      title: 'Vị trí chính xác',
      note: 'Điểm được lấy trực tiếp từ nguồn tin. Hãy đối chiếu giấy tờ trước khi giao dịch.'
    },
    road: {
      title: 'Vị trí theo tên đường',
      note: 'Marker là điểm đại diện theo tên đường, không phải vị trí chính xác của thửa đất.'
    },
    ward: {
      title: 'Vị trí theo tâm phường',
      note: 'Marker đặt tại tâm phường vì tin chưa đủ dữ liệu đường; không phải vị trí chính xác của thửa đất.'
    }
  };

  function precisionCopy(value) {
    var item = PRECISION_COPY[String(value || '').toLowerCase()];
    return item ? { title: item.title, note: item.note } : null;
  }

  function normalizeLocation(value) {
    if (!value || typeof value !== 'object') return null;
    var lat = Number(value.lat);
    var lng = Number(value.lng);
    var precision = String(value.precision || '').toLowerCase();
    if (
      !Number.isFinite(lat) || lat < -90 || lat > 90
      || !Number.isFinite(lng) || lng < -180 || lng > 180
      || !precisionCopy(precision)
    ) {
      return null;
    }
    return {
      lat: lat,
      lng: lng,
      precision: precision,
      label: String(value.label || ''),
      resolverVersion: String(value.resolver_version || value.resolverVersion || '')
    };
  }

  function vendorConfig() {
    return (root && root.RADAR_MAP_VENDOR) || {};
  }

  function appendStyle(doc, config) {
    var existing = doc.querySelector('link[data-radar-leaflet-style]');
    if (existing) return Promise.resolve(existing);
    return new Promise(function (resolve, reject) {
      var link = doc.createElement('link');
      link.rel = 'stylesheet';
      link.href = config.url;
      link.dataset.radarLeafletStyle = 'true';
      if (config.integrity) {
        link.integrity = config.integrity;
        link.crossOrigin = '';
      }
      link.onload = function () { resolve(link); };
      link.onerror = function () { reject(new Error('Leaflet stylesheet failed to load')); };
      doc.head.appendChild(link);
    });
  }

  function appendScript(doc, config) {
    if (root && root.L) return Promise.resolve(root.L);
    var existing = doc.querySelector('script[data-radar-leaflet-script]');
    if (existing) {
      return new Promise(function (resolve, reject) {
        existing.addEventListener('load', function () { resolve(root.L); }, { once: true });
        existing.addEventListener('error', function () {
          reject(new Error('Leaflet script failed to load'));
        }, { once: true });
      });
    }
    return new Promise(function (resolve, reject) {
      var script = doc.createElement('script');
      script.src = config.url;
      script.async = true;
      script.dataset.radarLeafletScript = 'true';
      if (config.integrity) {
        script.integrity = config.integrity;
        script.crossOrigin = '';
      }
      script.onload = function () {
        if (root.L) resolve(root.L);
        else reject(new Error('Leaflet did not initialize'));
      };
      script.onerror = function () { reject(new Error('Leaflet script failed to load')); };
      doc.body.appendChild(script);
    });
  }

  function loadLeaflet() {
    if (!root || !root.document) return Promise.reject(new Error('Leaflet requires a browser'));
    if (root.L) return Promise.resolve(root.L);
    if (leafletPromise) return leafletPromise;
    var config = vendorConfig();
    if (!config.leafletScript || !config.leafletStyle) {
      return Promise.reject(new Error('Missing Leaflet vendor configuration'));
    }
    leafletPromise = Promise.all([
      appendStyle(root.document, config.leafletStyle),
      appendScript(root.document, config.leafletScript)
    ]).then(function () {
      return root.L;
    }).catch(function (error) {
      leafletPromise = null;
      throw error;
    });
    return leafletPromise;
  }

  function setCopy(section, title, note, label) {
    var target = section.querySelector('[data-location-copy]');
    if (!target) return;
    target.textContent = '';
    var strong = section.ownerDocument.createElement('strong');
    strong.textContent = title;
    var small = section.ownerDocument.createElement('span');
    small.textContent = label ? label + '. ' + note : note;
    target.appendChild(strong);
    target.appendChild(small);
  }

  function unmount(section) {
    if (!section) return;
    if (section._radarDetailMap) {
      section._radarDetailMap.remove();
      section._radarDetailMap = null;
    }
  }

  function mount(options) {
    options = options || {};
    var section = options.root;
    if (!section || typeof section.querySelector !== 'function') {
      return Promise.resolve(null);
    }
    unmount(section);
    var location = normalizeLocation(options.location);
    var canvas = section.querySelector('[data-location-map]');
    var retry = section.querySelector('[data-location-retry]');
    section.classList.toggle('is-location-empty', !location);
    if (!location) {
      setCopy(
        section,
        'Chưa xác định được vị trí đủ tin cậy',
        'Radar BDS không đặt marker khi dữ liệu vị trí chưa đạt yêu cầu.',
        ''
      );
      if (canvas) canvas.hidden = true;
      if (retry) retry.hidden = true;
      return Promise.resolve(null);
    }

    var copy = precisionCopy(location.precision);
    setCopy(section, copy.title, copy.note, location.label);
    if (canvas) canvas.hidden = false;
    if (retry) retry.hidden = true;

    return loadLeaflet().then(function (L) {
      if (!canvas || !canvas.isConnected) return null;
      var street = L.tileLayer(
        'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        {
          maxZoom: 19,
          attribution: '&copy; OpenStreetMap contributors'
        }
      );
      var satellite = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        {
          maxZoom: 19,
          attribution: 'Tiles &copy; Esri'
        }
      );
      var initial = options.initialLayer === 'satellite' ? satellite : street;
      var map = L.map(canvas, {
        center: [location.lat, location.lng],
        zoom: location.precision === 'exact' ? 17 : (location.precision === 'road' ? 15 : 13),
        layers: [initial],
        scrollWheelZoom: false
      });
      L.control.layers({ 'Đường phố': street, 'Vệ tinh': satellite }, null, {
        position: 'topright',
        collapsed: true
      }).addTo(map);
      L.marker([location.lat, location.lng], {
        title: copy.title,
        alt: copy.title
      }).addTo(map).bindTooltip(location.label || copy.title);
      section._radarDetailMap = map;
      setTimeout(function () {
        if (section._radarDetailMap) section._radarDetailMap.invalidateSize();
      }, 0);
      return map;
    }).catch(function () {
      setCopy(
        section,
        'Không tải được bản đồ vị trí',
        'Thông tin độ chính xác vẫn được giữ nguyên. Bạn có thể thử lại.',
        location.label
      );
      if (retry) {
        retry.hidden = false;
        retry.onclick = function () { mount(options); };
      }
      return null;
    });
  }

  return {
    precisionCopy: precisionCopy,
    normalizeLocation: normalizeLocation,
    loadLeaflet: loadLeaflet,
    mount: mount,
    unmount: unmount
  };
});

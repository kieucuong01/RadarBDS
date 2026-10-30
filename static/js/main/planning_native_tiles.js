(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarPlanningNativeTiles = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';
  var emptyImage = 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
  var pools = new WeakMap(), completed = new WeakMap();
  // 64 RGBA tiles use at most 16 MiB of pixel storage per window. Source changes
  // and coordinates have independent keys; failed/incomplete tiles never enter it.
  function tileCache(env) {
    var entries = completed.get(env);
    if (!entries) { entries = new Map(); completed.set(env, entries); }
    return entries;
  }
  function schedule(env, start) {
    var pool = pools.get(env);
    if (!pool) { pool = {active:0, queue:[]}; pools.set(env, pool); }
    function drain() {
      while (pool.active < 4 && pool.queue.length) {
        var next = pool.queue.shift(); next.running = true; pool.active++; next.start();
      }
    }
    var job = {start:start, running:false, released:false};
    pool.queue.push(job); drain();
    return function () {
      if (job.released) return;
      job.released = true;
      if (job.running) pool.active--;
      else pool.queue.splice(pool.queue.indexOf(job), 1);
      drain();
    };
  }
  function url(template, coords) {
    return template.replace(/\{([zxy])\}/g, function (_, key) { return String(coords[key]); });
  }
  function create(L, env, manifest, options) {
    if (!L.GridLayer || !L.GridLayer.extend || !manifest.source_tiles) return L.tileLayer(manifest.tile_template, options);
    var pending = new Set();
    var Layer = L.GridLayer.extend({
      createTile: function (coords, done) {
        var tile = env.document.createElement('canvas');
        tile.width = tile.height = 256;
        tile.setAttribute('role', 'presentation');
        var context = tile.getContext('2d'), images = [], stopped = false, settled = false, fallback = false, timer, release;
        var foreground, background;
        var entries = tileCache(env), clock = env.Date || Date;
        var key = JSON.stringify([manifest.tile_template, manifest.source_tiles.primary, manifest.source_tiles.supplement, coords.z, coords.x, coords.y]);
        function clearImages() {
          images.forEach(function (img) { img.onload = img.onerror = null; img.src = emptyImage; });
          images = []; foreground = background = null;
        }
        function finish(error, transport) {
          if (stopped || settled) return;
          settled = true; pending.delete(tile);
          env.clearTimeout(timer);
          tile.setAttribute('data-planning-transport', error ? 'error' : transport);
          if (!error && transport !== 'memory') {
            var now = clock.now();
            entries.forEach(function (entry, id) { if (entry.expires <= now) entries.delete(id); });
            entries.delete(key); entries.set(key, {tile:tile, expires:now + 180000});
            while (entries.size > 64) entries.delete(entries.keys().next().value);
          }
          clearImages(); delete tile.cancelPlanningLoad;
          if (release) release(); done(error || null, tile);
        }
        tile.cancelPlanningLoad = function () {
          stopped = true; pending.delete(tile); env.clearTimeout(timer); clearImages(); if (release) release();
        };
        pending.add(tile);
        var cached = entries.get(key);
        if (cached && cached.expires > clock.now() && context) {
          entries.delete(key); entries.set(key, cached);
          context.drawImage(cached.tile, 0, 0);
          timer = env.setTimeout(function () { finish(null, 'memory'); }, 0);
          return tile;
        }
        if (cached) entries.delete(key);
        function load(template, success, failure) {
          var img = env.document.createElement('img'); images.push(img);
          img.alt = ''; img.decoding = 'async';
          img.onload = function () {
            if (stopped || settled) return;
            if (img.naturalWidth !== 256 || img.naturalHeight !== 256) { failure(); return; }
            success(img);
          };
          img.onerror = function () { if (!stopped && !settled) failure(); };
          img.src = url(template, coords);
        }
        function gateway() {
          if (stopped || settled || fallback) return;
          fallback = true; env.clearTimeout(timer); clearImages();
          timer = env.setTimeout(function () { finish(new Error('Planning tile timed out'), 'gateway'); }, 15000);
          load(manifest.tile_template, function (img) {
            if (!context) { finish(new Error('Canvas unavailable'), 'gateway'); return; }
            context.clearRect(0, 0, 256, 256); context.drawImage(img, 0, 0);
            finish(null, 'gateway');
          }, function () { finish(new Error('Planning tile unavailable'), 'gateway'); });
        }
        function paint() {
          if (stopped || settled || fallback || !foreground || !background) return;
          // Apply layer opacity once to the composite, matching the gateway's source order.
          context.clearRect(0, 0, 256, 256);
          context.drawImage(background, 0, 0); context.drawImage(foreground, 0, 0);
          finish(null, 'direct');
        }
        // Share four active tiles across layers; queued tiles do not time out before they start.
        release = schedule(env, function () {
          if (!context) { gateway(); return; }
          timer = env.setTimeout(gateway, 8000);
          load(manifest.source_tiles.primary, function (img) { foreground = img; paint(); }, gateway);
          load(manifest.source_tiles.supplement, function (img) { background = img; paint(); }, gateway);
        });
        return tile;
      }
    });
    var layer = new Layer(options);
    layer.on('tileunload', function (event) { if (event.tile.cancelPlanningLoad) event.tile.cancelPlanningLoad(); });
    layer.on('remove', function () { Array.from(pending).reverse().forEach(function (tile) { tile.cancelPlanningLoad(); }); });
    return layer;
  }
  return {create: create};
});

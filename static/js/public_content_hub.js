(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root && root.document) {
    root.RadarPublicContentHub = api;
    var start = function () { api.init(root.document, root); };
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
      start();
    }
  }
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";

  function normalizeText(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/đ/g, "d")
      .replace(/Đ/g, "D")
      .toLowerCase()
      .replace(/[-_]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function filterIndexes(items, filters) {
    var selected = filters || {};
    var query = normalizeText(selected.query);
    var facet = normalizeText(selected.facet);
    var topic = normalizeText(selected.topic);
    var type = normalizeText(selected.type);
    var year = String(selected.year || "");
    var days = Math.max(0, Number(selected.days) || 0);
    var cutoff = days ? Date.now() - days * 86400000 : 0;
    var matches = [];

    items.forEach(function (item, index) {
      var publishedAt = Date.parse(item.published || "");
      if (query && normalizeText(item.search).indexOf(query) === -1) return;
      if (facet && normalizeText(item.facet) !== facet) return;
      if (topic && normalizeText(item.topic) !== topic) return;
      if (type && normalizeText(item.type) !== type) return;
      if (year && String(item.year || "") !== year) return;
      if (cutoff && (!Number.isFinite(publishedAt) || publishedAt < cutoff)) return;
      matches.push(index);
    });
    return matches;
  }

  function filterTrackContext(query, resultCount, facet) {
    return {
      query_length: String(query || "").length,
      result_count: Math.max(0, Number(resultCount) || 0),
      facet: String(facet || "").slice(0, 80)
    };
  }

  function emitTrack(win, action, context) {
    if (!win || typeof win.CustomEvent !== "function") return;
    win.dispatchEvent(new win.CustomEvent("radar:track", {
      detail: { action: action, context: context || {} }
    }));
  }

  function init(doc, win) {
    var hub = doc.querySelector("[data-public-content-hub]");
    if (!hub) return;
    var cards = Array.prototype.slice.call(
      hub.querySelectorAll("[data-public-content-card]")
    );
    var search = hub.querySelector("[data-public-content-search]");
    var facet = hub.querySelector("[data-public-content-facet]");
    var topic = hub.querySelector("[data-public-content-topic]");
    var type = hub.querySelector("[data-public-content-type]");
    var year = hub.querySelector("[data-public-content-year]");
    var time = hub.querySelector("[data-public-content-time]");
    var status = hub.querySelector("[data-public-content-results]");
    var empty = hub.querySelector("[data-public-content-empty]");
    var reset = hub.querySelector("[data-public-content-reset]");
    var debounceTimer = 0;
    var items = cards.map(function (card) {
      return {
        search: card.getAttribute("data-content-search") || "",
        facet: card.getAttribute("data-content-facet") || "",
        topic: card.getAttribute("data-content-topic") || "",
        type: card.getAttribute("data-content-type") || "",
        year: card.getAttribute("data-content-year") || "",
        published: card.getAttribute("data-content-published") || ""
      };
    });

    hub.classList.add("is-enhanced");

    function currentFilters() {
      return {
        query: search ? search.value : "",
        facet: facet ? facet.value : "",
        topic: topic ? topic.value : "",
        type: type ? type.value : "",
        year: year ? year.value : "",
        days: time ? time.value : ""
      };
    }

    function render(track) {
      var filters = currentFilters();
      var indexes = filterIndexes(items, filters);
      var visible = new Set(indexes);
      cards.forEach(function (card, index) {
        card.hidden = !visible.has(index);
      });
      if (status) status.textContent = indexes.length + " kết quả";
      if (empty) empty.hidden = indexes.length !== 0;
      if (track) {
        emitTrack(
          win,
          "public_content_filter_used",
          filterTrackContext(filters.query, indexes.length, filters.facet)
        );
      }
    }

    function scheduleRender() {
      win.clearTimeout(debounceTimer);
      debounceTimer = win.setTimeout(function () { render(true); }, 180);
    }

    [search, facet, topic, type, year, time].forEach(function (control) {
      if (!control) return;
      control.addEventListener(
        control === search ? "input" : "change",
        scheduleRender
      );
    });

    if (reset) {
      reset.addEventListener("click", function () {
        [search, facet, topic, type, year, time].forEach(function (control) {
          if (control) control.value = "";
        });
        render(true);
        if (search) search.focus();
      });
    }

    render(false);
  }

  return {
    filterIndexes: filterIndexes,
    filterTrackContext: filterTrackContext,
    init: init,
    normalizeText: normalizeText
  };
});

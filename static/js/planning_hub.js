(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root && root.document) {
    root.RadarPlanningHub = api;
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

  function filterIndexes(items, category) {
    var selected = category || "all";
    var matches = [];
    items.forEach(function (item, index) {
      if (selected === "all" || item.category === selected) {
        matches.push(index);
      }
    });
    return matches;
  }

  function categoryFromHash(win, validCategories) {
    var hash = String((win && win.location && win.location.hash) || "");
    if (!hash.startsWith("#cat-")) return "all";
    var category = "all";
    try {
      category = decodeURIComponent(hash.slice(5));
    } catch (error) {
      return "all";
    }
    return validCategories.includes(category) ? category : "all";
  }

  function filterTrackContext(category, resultCount) {
    return {
      category: category || "all",
      result_count: Math.max(0, Number(resultCount) || 0)
    };
  }

  function emitTrack(win, action, context) {
    if (!win || typeof win.CustomEvent !== "function") return;
    win.dispatchEvent(new win.CustomEvent("radar:track", {
      detail: { action: action, context: context || {} }
    }));
  }

  function init(doc, win) {
    var hub = doc.querySelector("[data-planning-hub]");
    if (!hub) return;

    var filters = Array.prototype.slice.call(hub.querySelectorAll("[data-planning-filter]"));
    var cards = Array.prototype.slice.call(hub.querySelectorAll("[data-planning-card]"));
    var status = hub.querySelector("[data-planning-results-status]");
    var emptyState = hub.querySelector("[data-planning-empty]");
    if (!filters.length || !cards.length) return;

    var validCategories = filters.map(function (button) {
      return button.getAttribute("data-planning-filter") || "all";
    });
    var items = cards.map(function (card) {
      return {
        category: card.getAttribute("data-category") || "",
        slug: card.getAttribute("data-planning-slug") || ""
      };
    });
    var activeCategory = categoryFromHash(win, validCategories);

    hub.classList.add("is-enhanced");

    function render() {
      var matchedIndexes = filterIndexes(items, activeCategory);
      var visibleIndexes = new Set(matchedIndexes);
      cards.forEach(function (card, index) {
        card.hidden = !visibleIndexes.has(index);
      });
      filters.forEach(function (button) {
        var active = (button.getAttribute("data-planning-filter") || "all") === activeCategory;
        button.classList.toggle("is-active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
      if (status) {
        status.textContent = matchedIndexes.length
          ? "Đang hiện " + matchedIndexes.length + " / " + cards.length + " chuyên đề"
          : "Chưa có chuyên đề phù hợp";
      }
      if (emptyState) emptyState.hidden = matchedIndexes.length !== 0;
    }

    filters.forEach(function (button) {
      button.addEventListener("click", function () {
        activeCategory = button.getAttribute("data-planning-filter") || "all";
        var matchedCount = filterIndexes(items, activeCategory).length;
        var nextHash = "#cat-" + encodeURIComponent(activeCategory);
        if (win.location.hash === nextHash) {
          render();
        } else {
          win.location.hash = nextHash;
        }
        emitTrack(
          win,
          "planning_hub_filter_selected",
          filterTrackContext(activeCategory, matchedCount)
        );
      });
    });

    hub.querySelectorAll("[data-planning-card-link]").forEach(function (link) {
      link.addEventListener("click", function () {
        var card = link.closest("[data-planning-card]");
        emitTrack(win, "planning_hub_card_clicked", {
          category: card ? card.getAttribute("data-category") || "" : "",
          slug: card ? card.getAttribute("data-planning-slug") || "" : "",
          target: link.getAttribute("href") || ""
        });
      });
    });

    win.addEventListener("hashchange", function () {
      activeCategory = categoryFromHash(win, validCategories);
      render();
    });

    render();
  }

  return {
    categoryFromHash: categoryFromHash,
    filterIndexes: filterIndexes,
    filterTrackContext: filterTrackContext,
    init: init
  };
});

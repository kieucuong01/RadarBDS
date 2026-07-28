(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root && root.document) {
    root.RadarNewsHub = api;
    const start = () => api.init(root.document, root);
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
      start();
    }
  }
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";

  const DEFAULT_BATCH_SIZE = 8;

  function normalizeVietnamese(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/đ/g, "d")
      .replace(/Đ/g, "D")
      .toLowerCase()
      .trim();
  }

  function filterArticles(items, category, query) {
    const normalizedQuery = normalizeVietnamese(query);
    const selectedCategory = category || "all";
    const matches = [];
    items.forEach(function (item, index) {
      const categoryMatches = selectedCategory === "all" || item.category === selectedCategory;
      const queryMatches = !normalizedQuery || normalizeVietnamese(item.searchText).includes(normalizedQuery);
      if (categoryMatches && queryMatches) matches.push(index);
    });
    return matches;
  }

  function nextVisibleCount(current, total, batchSize) {
    const size = Math.max(1, Number(batchSize) || DEFAULT_BATCH_SIZE);
    return Math.min(Math.max(0, Number(current) || 0) + size, Math.max(0, Number(total) || 0));
  }

  function emitTrack(win, action, context) {
    if (!win || typeof win.CustomEvent !== "function") return;
    win.dispatchEvent(new win.CustomEvent("radar:track", {
      detail: { action: action, context: context || {} }
    }));
  }

  function categoryFromHash(win, validCategories) {
    const hash = String((win && win.location && win.location.hash) || "");
    if (!hash.startsWith("#cat-")) return "all";
    let category = "all";
    try {
      category = decodeURIComponent(hash.slice(5));
    } catch (error) {
      return "all";
    }
    return validCategories.includes(category) ? category : "all";
  }

  function init(doc, win) {
    const hub = doc.querySelector("[data-news-hub]");
    if (!hub) return;

    const search = hub.querySelector("[data-news-search]");
    const cards = Array.from(hub.querySelectorAll("[data-news-card]"));
    const categoryLinks = Array.from(hub.querySelectorAll("[data-news-category]"));
    const status = hub.querySelector("[data-news-results-status]");
    const loadMore = hub.querySelector("[data-news-load-more]");
    const loadMoreRow = hub.querySelector("[data-news-load-more-row]");
    const emptyState = hub.querySelector("[data-news-empty-state]");
    const reset = hub.querySelector("[data-news-reset]");
    const validCategories = categoryLinks.map(function (link) {
      return link.dataset.newsCategory;
    });
    const items = cards.map(function (card) {
      return {
        category: card.dataset.newsCategoryKey || "",
        searchText: card.dataset.newsSearchText || ""
      };
    });

    let activeCategory = categoryFromHash(win, validCategories);
    let visibleCount = DEFAULT_BATCH_SIZE;
    let debounceTimer = null;

    hub.classList.add("is-enhanced");
    if (loadMoreRow) loadMoreRow.hidden = false;

    function render() {
      const query = search ? search.value : "";
      const matchedIndexes = filterArticles(items, activeCategory, query);
      const visibleIndexes = new Set(matchedIndexes.slice(0, visibleCount));

      cards.forEach(function (card, index) {
        card.hidden = !visibleIndexes.has(index);
      });

      categoryLinks.forEach(function (link) {
        const isActive = link.dataset.newsCategory === activeCategory;
        link.classList.toggle("is-active", isActive);
        if (isActive) {
          link.setAttribute("aria-current", "true");
        } else {
          link.removeAttribute("aria-current");
        }
      });

      const visibleNow = Math.min(visibleCount, matchedIndexes.length);
      if (status) {
        status.textContent = matchedIndexes.length
          ? `Đang hiện ${visibleNow} / ${matchedIndexes.length} bài phân tích`
          : "Không có bài phù hợp";
      }
      if (emptyState) emptyState.hidden = matchedIndexes.length !== 0;
      if (loadMore) loadMore.hidden = matchedIndexes.length === 0 || visibleNow >= matchedIndexes.length;
    }

    categoryLinks.forEach(function (link) {
      link.addEventListener("click", function (event) {
        event.preventDefault();
        activeCategory = link.dataset.newsCategory || "all";
        visibleCount = DEFAULT_BATCH_SIZE;
        const nextHash = `#cat-${encodeURIComponent(activeCategory)}`;
        if (win.location.hash === nextHash) {
          render();
        } else {
          win.location.hash = nextHash;
        }
        emitTrack(win, "news_hub_category_selected", {
          category: activeCategory,
          result_count: filterArticles(items, activeCategory, search ? search.value : "").length
        });
      });
    });

    if (search) {
      search.addEventListener("input", function () {
        visibleCount = DEFAULT_BATCH_SIZE;
        win.clearTimeout(debounceTimer);
        debounceTimer = win.setTimeout(render, 180);
      });
      search.addEventListener("change", function () {
        emitTrack(win, "news_hub_search_used", {
          query_length: normalizeVietnamese(search.value).length,
          result_count: filterArticles(items, activeCategory, search.value).length
        });
      });
    }

    if (loadMore) {
      loadMore.addEventListener("click", function () {
        const total = filterArticles(items, activeCategory, search ? search.value : "").length;
        visibleCount = nextVisibleCount(visibleCount, total, DEFAULT_BATCH_SIZE);
        render();
        emitTrack(win, "news_hub_load_more", {
          category: activeCategory,
          visible_count: visibleCount,
          result_count: total
        });
      });
    }

    if (reset) {
      reset.addEventListener("click", function () {
        if (search) search.value = "";
        activeCategory = "all";
        visibleCount = DEFAULT_BATCH_SIZE;
        win.history.replaceState(null, "", `${win.location.pathname}${win.location.search}#cat-all`);
        render();
        if (search) search.focus();
      });
    }

    win.addEventListener("hashchange", function () {
      activeCategory = categoryFromHash(win, validCategories);
      visibleCount = DEFAULT_BATCH_SIZE;
      render();
    });

    render();
  }

  return {
    categoryFromHash: categoryFromHash,
    filterArticles: filterArticles,
    init: init,
    nextVisibleCount: nextVisibleCount,
    normalizeVietnamese: normalizeVietnamese
  };
});

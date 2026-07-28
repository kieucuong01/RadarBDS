(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var searchInput = document.getElementById("reportSearchInput");
    var wardSelect = document.getElementById("reportWardSelect");
    var periodSelect = document.getElementById("reportPeriodSelect");
    var status = document.getElementById("reportFilterStatus");
    var empty = document.getElementById("reportEmptyState");
    var cards = Array.prototype.slice.call(
      document.querySelectorAll("[data-report-card]")
    );
    var cityButtons = Array.prototype.slice.call(
      document.querySelectorAll("[data-filter-city]")
    );
    var activeCity = "all";
    var restoring = false;

    function normalize(value) {
      return (value || "")
        .toString()
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "");
    }

    function allowedValue(select, value, fallback) {
      if (!select) return fallback;
      return Array.prototype.some.call(select.options, function (option) {
        return option.value === value;
      })
        ? value
        : fallback;
    }

    function allowedCity(value) {
      return cityButtons.some(function (button) {
        return !button.disabled && button.dataset.filterCity === value;
      })
        ? value
        : "all";
    }

    function setCity(value) {
      activeCity = allowedCity(value);
      cityButtons.forEach(function (button) {
        var active = button.dataset.filterCity === activeCity;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    }

    function syncWardOptions() {
      if (!wardSelect) return;
      Array.prototype.slice.call(wardSelect.options).forEach(function (option) {
        var optionCity = option.dataset.city || "all";
        option.hidden =
          activeCity !== "all" &&
          optionCity !== "all" &&
          optionCity !== activeCity;
      });
      var selected = wardSelect.options[wardSelect.selectedIndex];
      if (selected && selected.hidden) wardSelect.value = "all";
    }

    function safeFilterContext() {
      var selectedWard =
        wardSelect && wardSelect.options[wardSelect.selectedIndex];
      return {
        city: activeCity,
        ward_slug:
          (selectedWard && selectedWard.dataset.wardKey) || "all",
        period: periodSelect ? periodSelect.value : "all",
        source_surface: "report_hub"
      };
    }

    function trackFilter() {
      window.dispatchEvent(
        new CustomEvent("radar:track", {
          detail: {
            action: "report_filter_used",
            context: safeFilterContext()
          }
        })
      );
    }

    function syncUrl() {
      if (restoring) return;
      var params = new URLSearchParams(window.location.search);
      var ward = wardSelect ? wardSelect.value : "all";
      var period = periodSelect ? periodSelect.value : "all";
      var search = searchInput ? searchInput.value.trim() : "";
      [
        ["city", activeCity],
        ["ward", ward],
        ["period", period],
        ["q", search]
      ].forEach(function (pair) {
        if (!pair[1] || pair[1] === "all") params.delete(pair[0]);
        else params.set(pair[0], pair[1]);
      });
      var queryString = params.toString();
      window.history.replaceState(
        null,
        "",
        window.location.pathname + (queryString ? "?" + queryString : "")
      );
    }

    function applyReportFilters(options) {
      var query = normalize(searchInput ? searchInput.value : "");
      var ward = wardSelect ? wardSelect.value : "all";
      var period = periodSelect ? periodSelect.value : "all";
      var visible = 0;
      cards.forEach(function (card) {
        var matchesCity =
          activeCity === "all" || card.dataset.city === activeCity;
        var matchesWard =
          ward === "all" || card.dataset.ward === ward;
        var matchesPeriod =
          period === "all" || card.dataset.period === period;
        var matchesQuery =
          !query ||
          normalize(card.dataset.search || card.innerText).indexOf(query) !== -1;
        var show =
          matchesCity && matchesWard && matchesPeriod && matchesQuery;
        card.hidden = !show;
        if (show) visible += 1;
      });
      if (status) {
        status.textContent =
          "Đang hiển thị " + visible + "/" + cards.length + " báo cáo cũ hơn.";
      }
      if (empty) empty.hidden = visible !== 0;
      syncUrl();
      if (options && options.track) trackFilter();
    }

    function restoreFromUrl() {
      restoring = true;
      var params = new URLSearchParams(window.location.search);
      setCity(params.get("city") || "all");
      syncWardOptions();
      if (wardSelect) {
        wardSelect.value = allowedValue(
          wardSelect,
          params.get("ward") || "all",
          "all"
        );
      }
      if (periodSelect) {
        periodSelect.value = allowedValue(
          periodSelect,
          params.get("period") || "all",
          "all"
        );
      }
      if (searchInput) searchInput.value = (params.get("q") || "").slice(0, 100);
      restoring = false;
      applyReportFilters();
    }

    cityButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        if (button.disabled) return;
        setCity(button.dataset.filterCity || "all");
        syncWardOptions();
        applyReportFilters({ track: true });
      });
    });
    if (searchInput) {
      searchInput.addEventListener("input", function () {
        applyReportFilters({ track: true });
      });
    }
    if (wardSelect) {
      wardSelect.addEventListener("change", function () {
        applyReportFilters({ track: true });
      });
    }
    if (periodSelect) {
      periodSelect.addEventListener("change", function () {
        applyReportFilters({ track: true });
      });
    }
    window.addEventListener("popstate", restoreFromUrl);
    restoreFromUrl();
  });
})();

(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("reportFilterForm");
    if (!form) return;
    var ward = document.getElementById("reportWardSelect");
    var period = document.getElementById("reportPeriodSelect");

    function track(city) {
      var selected = ward && ward.options[ward.selectedIndex];
      window.dispatchEvent(new CustomEvent("radar:track", {
        detail: {
          action: "report_filter_used",
          context: {
            city: city || form.elements.city.value,
            ward_slug: (selected && selected.dataset.wardKey) || "all",
            period: period ? period.value : "all",
            source_surface: "report_hub"
          }
        }
      }));
    }

    // Native GET navigation searches every page and works without JavaScript.
    form.addEventListener("submit", function () {
      track();
      Array.prototype.forEach.call(form.elements, function (input) {
        if (input.name && (!input.value.trim() || (input.name !== "q" && input.value === "all"))) {
          input.disabled = true;
        }
      });
    });
    [ward, period].forEach(function (select) {
      if (select) select.addEventListener("change", function () {
        form.requestSubmit();
      });
    });
    document.querySelectorAll("a[data-filter-city]").forEach(function (link) {
      link.addEventListener("click", function () { track(link.dataset.filterCity); });
    });
    // A back/forward cache restore must leave the native form usable.
    window.addEventListener("pageshow", function () {
      Array.prototype.forEach.call(form.elements, function (input) {
        input.disabled = false;
      });
    });
  });
})();

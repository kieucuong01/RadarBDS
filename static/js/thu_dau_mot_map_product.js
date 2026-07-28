(function (factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined") {
    window.RadarThuDauMotMapProduct = api;
  }
})(function () {
  "use strict";

  function setEdition(root, edition) {
    var normalized = edition === "current" ? "current" : "legacy";
    root.querySelectorAll("[data-product-edition]").forEach(function (button) {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.productEdition === normalized)
      );
    });
    root.querySelectorAll("[data-product-preview]").forEach(function (preview) {
      preview.hidden = preview.dataset.productPreview !== normalized;
    });
  }

  function emitTrack(win, action, context) {
    if (!win || typeof win.CustomEvent !== "function") return;
    try {
      win.dispatchEvent(new win.CustomEvent("radar:track", {
        detail: { action: action, context: context || {} }
      }));
    } catch (error) {
      // Analytics must never block the product-page interaction.
    }
  }

  function init(doc, win) {
    var root = doc.querySelector("[data-thu-dau-mot-map-product]");
    if (!root) return;

    root.querySelectorAll("[data-product-edition]").forEach(function (button) {
      button.addEventListener("click", function () {
        var edition = button.dataset.productEdition === "current"
          ? "current"
          : "legacy";
        setEdition(root, edition);
        emitTrack(win, "thu_dau_mot_map_preview_selected", {
          edition: edition,
          source_surface: "preview_switch"
        });
      });
    });

    var purchase = root.querySelector("[data-product-purchase]");
    if (purchase) {
      purchase.addEventListener("click", function () {
        if (purchase.disabled || purchase.getAttribute("aria-disabled") === "true") {
          return;
        }
        emitTrack(win, "thu_dau_mot_map_purchase_clicked", {
          source_surface: "product_offer"
        });
      });
    }

    var dashboard = root.querySelector("[data-product-dashboard]");
    if (dashboard) {
      dashboard.addEventListener("click", function () {
        emitTrack(win, "thu_dau_mot_map_dashboard_clicked", {
          source_surface: "bottom_dashboard"
        });
      });
    }

    setEdition(root, "legacy");
  }

  if (typeof document !== "undefined" && typeof window !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        init(document, window);
      }, { once: true });
    } else {
      init(document, window);
    }
  }

  return {
    setEdition: setEdition,
    init: init
  };
});

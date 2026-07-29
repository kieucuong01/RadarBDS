(function () {
  "use strict";

  function initSeoHeader() {
    const header = document.querySelector(".seo-header");
    if (!header) return;

    const mobileToggle = header.querySelector("#seoNavToggle");
    const primaryNav = header.querySelector("#seoPrimaryNav");
    const groups = Array.from(header.querySelectorAll(".seo-nav-group"));
    const emitTrack = function (action, context) {
      if (typeof window.CustomEvent !== "function") return;
      window.dispatchEvent(new window.CustomEvent("radar:track", {
        detail: { action: action, context: context || {} }
      }));
    };
    const closeAll = function (exceptGroup) {
      groups.forEach(function (group) {
        if (group === exceptGroup) return;
        const button = group.querySelector(".seo-nav-tab");
        if (button) button.setAttribute("aria-expanded", "false");
      });
    };
    const closeMobileNav = function (returnFocus) {
      if (!mobileToggle) return;
      mobileToggle.setAttribute("aria-expanded", "false");
      closeAll(null);
      if (returnFocus) mobileToggle.focus();
    };

    if (mobileToggle && primaryNav) {
      mobileToggle.addEventListener("click", function () {
        const willOpen =
          mobileToggle.getAttribute("aria-expanded") !== "true";
        mobileToggle.setAttribute(
          "aria-expanded",
          willOpen ? "true" : "false"
        );
        if (!willOpen) closeAll(null);
        if (willOpen) {
          emitTrack("public_header_menu_opened", { group: "mobile_navigation" });
        }
      });
    }

    groups.forEach(function (group) {
      const button = group.querySelector(".seo-nav-tab");
      const menu = group.querySelector(".seo-nav-menu");
      if (!button || !menu) return;

      button.addEventListener("click", function () {
        const willOpen = button.getAttribute("aria-expanded") !== "true";
        closeAll(willOpen ? group : null);
        button.setAttribute("aria-expanded", willOpen ? "true" : "false");
        if (willOpen) {
          emitTrack("public_header_menu_opened", {
            group: button.getAttribute("data-nav-group") || ""
          });
        }
      });

      menu.querySelectorAll("a").forEach(function (link) {
        link.addEventListener("click", function () {
          closeAll(null);
          closeMobileNav(false);
          emitTrack("public_header_item_clicked", {
            group: button.getAttribute("data-nav-group") || "",
            target: link.getAttribute("href") || ""
          });
        });
      });
    });

    document.addEventListener("click", function (event) {
      if (!header.contains(event.target)) closeMobileNav(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      const expanded = header.querySelector(
        '.seo-nav-tab[aria-expanded="true"]'
      );
      if (expanded) {
        closeAll(null);
        expanded.focus();
        return;
      }
      if (
        mobileToggle
        && mobileToggle.getAttribute("aria-expanded") === "true"
      ) {
        closeMobileNav(true);
      }
    });

    header.querySelectorAll(".seo-nav-link").forEach(function (link) {
      link.addEventListener("click", function () {
        closeMobileNav(false);
        emitTrack("public_header_item_clicked", {
          group: "direct",
          target: link.getAttribute("href") || ""
        });
      });
    });

    const breakpoint = window.matchMedia("(max-width: 820px)");
    const resetForBreakpoint = function () {
      closeAll(null);
      if (!breakpoint.matches && mobileToggle) {
        mobileToggle.setAttribute("aria-expanded", "false");
      }
    };
    if (typeof breakpoint.addEventListener === "function") {
      breakpoint.addEventListener("change", resetForBreakpoint);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSeoHeader, { once: true });
  } else {
    initSeoHeader();
  }
})();

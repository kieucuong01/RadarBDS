(function () {
  "use strict";

  function initSeoHeader() {
    const header = document.querySelector(".seo-header");
    if (!header) return;

    const groups = Array.from(header.querySelectorAll(".seo-nav-group"));
    const closeAll = function (exceptGroup) {
      groups.forEach(function (group) {
        if (group === exceptGroup) return;
        const button = group.querySelector(".seo-nav-tab");
        if (button) button.setAttribute("aria-expanded", "false");
      });
    };

    groups.forEach(function (group) {
      const button = group.querySelector(".seo-nav-tab");
      const menu = group.querySelector(".seo-nav-menu");
      if (!button || !menu) return;

      button.addEventListener("click", function () {
        const willOpen = button.getAttribute("aria-expanded") !== "true";
        closeAll(willOpen ? group : null);
        button.setAttribute("aria-expanded", willOpen ? "true" : "false");
      });

      group.addEventListener("keydown", function (event) {
        if (event.key !== "Escape") return;
        button.setAttribute("aria-expanded", "false");
        button.focus();
      });
    });

    document.addEventListener("click", function (event) {
      if (!header.contains(event.target)) closeAll(null);
    });

    const activeGroup = header.querySelector(".seo-nav-group.is-active");
    if (activeGroup && window.matchMedia("(max-width: 820px)").matches) {
      window.requestAnimationFrame(function () {
        activeGroup.scrollIntoView({ block: "nearest", inline: "center" });
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSeoHeader, { once: true });
  } else {
    initSeoHeader();
  }
})();

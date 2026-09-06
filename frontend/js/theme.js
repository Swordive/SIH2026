// Wires up any dark-mode toggle button on the page (marked with the
// data-theme-toggle attribute). The theme itself is already applied
// before first paint by the tiny inline script in <head> -- this file
// only needs to handle clicks and keep other tabs in sync.

(function () {
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("theme", theme);
    } catch (e) {
      /* localStorage unavailable (private mode, etc.) -- theme just
         won't persist across reloads, which is fine. */
    }
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark"
      ? "dark"
      : "light";
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        applyTheme(currentTheme() === "dark" ? "light" : "dark");
      });
    });
  });

  // If the user flips the toggle in another tab, follow along here too.
  window.addEventListener("storage", function (e) {
    if (e.key === "theme" && e.newValue) {
      document.documentElement.setAttribute("data-theme", e.newValue);
    }
  });
})();

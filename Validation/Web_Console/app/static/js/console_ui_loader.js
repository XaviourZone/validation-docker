/* Deterministic Validation UI extension loader.
   The core console engine is intentionally kept separate from operator UI
   extensions. Extensions are loaded after console.js and after DOM exists. */
(function () {
  "use strict";

  const extensions = [
    ["/static/js/forwarder.js", "forwarder"],
    ["/static/js/router_admin.js", "router-admin"],
    ["/static/js/database_admin.js", "database-admin"],
    ["/static/js/console_polish.js", "minimal-ui"]
  ];

  function loadExtension(url, key) {
    window.__validationLoadedScripts = window.__validationLoadedScripts || {};
    if (window.__validationLoadedScripts[key]) {
      return Promise.resolve();
    }

    return new Promise(resolve => {
      const script = document.createElement("script");
      script.src = url + "?v=20260918-r4";
      script.async = false;
      script.dataset.validationExtension = key;
      script.onload = () => {
        window.__validationLoadedScripts[key] = true;
        resolve();
      };
      script.onerror = () => {
        console.error("Validation UI extension failed:", url);
        resolve();
      };
      document.head.appendChild(script);
    });
  }

  async function boot() {
    for (const [url, key] of extensions) {
      await loadExtension(url, key);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, {once: true});
  } else {
    boot();
  }
})();
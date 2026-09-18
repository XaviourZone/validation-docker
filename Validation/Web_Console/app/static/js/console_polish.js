/* Final operator UI overrides.
   Kept intentionally small and non-invasive: the existing console.js remains
   the application engine; this file only removes decorative/unused controls
   and provides robust folder dialogs. */
(function () {
  "use strict";

  const style = document.createElement("style");
  style.id = "validation-minimal-ui";
  style.textContent = `
    :root {
      --ui-radius: 4px;
    }
    .radar-logo { display:none !important; }
    .sidebar-header { gap:8px !important; }
    .sidebar-header h2 { margin:0 !important; font-size:17px !important; }
    .sidebar-header span { font-size:10px !important; }
    .module-card, .kpi-card, .panel, .router-header-panel {
      box-shadow:none !important;
      border-radius:var(--ui-radius) !important;
    }
    .module-card:hover, .btn:hover, .refresh-btn:hover {
      transform:none !important;
      box-shadow:none !important;
    }
    .router-status-row { display:none !important; }
    #btn-start-router, #btn-new-parser { display:none !important; }

    /* Compact operator tables */
    .data-table th, .data-table td { padding:7px 8px !important; }
    .panel-header { padding:10px 12px !important; }
    .panel-body { padding:12px !important; }
    .kpi-grid { gap:10px !important; }
    .kpi-card { min-height:0 !important; padding:12px !important; }
    .kpi-value { font-size:22px !important; }

    .pans-config-row {
      display:flex; gap:10px; align-items:flex-end;
    }
    .pans-config-field { flex:1; min-width:0; }
    .pans-folder-line { display:flex; gap:8px; }
    .pans-folder-line .form-input { flex:1; }
    .pans-config-panel .form-hint { font-size:10px; }

    @media(max-width:760px) {
      .pans-config-row { flex-direction:column; align-items:stretch; }
    }
  `;
  document.head.appendChild(style);

  const api = (url, options) => fetch(
    url,
    Object.assign({ headers: { "Content-Type": "application/json" } }, options || {})
  ).then(async r => {
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || d.message || `HTTP ${r.status}`);
    return d;
  });

  function patchRouterBrowse() {
    const target = document.getElementById("src-folder");
    const button = document.getElementById("router-browse-folder");
    if (!target || !button || button.dataset.patched === "1") return;
    button.dataset.patched = "1";
    button.onclick = () => openFolderBrowser(target);
  }

  function openFolderBrowser(target) {
    const old = document.getElementById("validation-folder-browser");
    if (old) old.remove();

    const modal = document.createElement("div");
    modal.id = "validation-folder-browser";
    modal.className = "modal-backdrop active";
    modal.style.zIndex = "10050";
    modal.innerHTML = `
      <div class="modal-container" style="max-width:760px;">
        <div class="modal-header">
          <div class="modal-title">Select input folder</div>
          <button class="modal-close-btn" id="vfb-close">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">Selected folder</label>
            <input id="vfb-path" class="form-input" readonly>
          </div>
          <div style="display:flex;gap:8px;margin-bottom:10px;">
            <button class="btn btn-secondary" id="vfb-up">Up</button>
            <button class="btn btn-primary" id="vfb-select">Select this folder</button>
          </div>
          <div id="vfb-list" style="max-height:420px;overflow:auto;border:1px solid var(--border-color);border-radius:4px;"></div>
          <div id="vfb-error" style="color:var(--accent-rose);margin-top:8px;"></div>
        </div>
      </div>`;
    document.body.appendChild(modal);

    const pathEl = document.getElementById("vfb-path");
    const listEl = document.getElementById("vfb-list");
    const errEl = document.getElementById("vfb-error");

    document.getElementById("vfb-close").onclick = () => modal.remove();
    document.getElementById("vfb-select").onclick = () => {
      const value = pathEl.value.trim();
      if (value) {
        target.value = value;
        target.dispatchEvent(new Event("input", {bubbles:true}));
        target.dispatchEvent(new Event("change", {bubbles:true}));
      }
      modal.remove();
    };
    document.getElementById("vfb-up").onclick = async () => {
      const current = pathEl.value;
      if (!current) return;
      try {
        const d = await browse(current);
        if (d.parent && d.parent !== current) await browse(d.parent);
      } catch (_) {}
    };

    async function browse(path) {
      try {
        const url = path
          ? `/api/router/filesystem/browse?path=${encodeURIComponent(path)}`
          : "/api/router/filesystem/browse";
        const d = await api(url);

        if (d.roots) {
          pathEl.value = "";
          render(d.roots);
        } else {
          pathEl.value = d.path || "";
          render(d.entries || []);
        }
        errEl.textContent = "";
        return d;
      } catch (e) {
        errEl.textContent = e.message;
        listEl.innerHTML = "";
        return {};
      }
    }

    function render(entries) {
      listEl.innerHTML = "";
      if (!entries.length) {
        listEl.innerHTML = '<div style="padding:12px;color:var(--text-muted)">No readable folders</div>';
        return;
      }
      for (const item of entries) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "btn btn-secondary";
        b.style.cssText = "display:block;width:100%;text-align:left;margin:3px 0;";
        b.disabled = item.readable === false;
        b.textContent = "📁 " + item.name;
        b.onclick = () => browse(item.path);
        listEl.appendChild(b);
      }
    }

    browse(target.value.trim());
  }

  function patchForwarder() {
    const view = document.getElementById("view-forwarder");
    if (!view) return;

    // Add Destination must always be operable even when the panel is rendered
    // after navigation to the Forwarder page.
    const add = document.getElementById("fw-add");
    if (add && add.dataset.validationBound !== "1") {
      add.dataset.validationBound = "1";
      add.addEventListener("click", () => {
        // forwarder.js already owns the modal/opening function.
      });
    }

    const modal = document.getElementById("fw-modal");
    const save = document.getElementById("fw-save");
    if (modal && save) {
      const name = document.getElementById("fw-name");
      if (name) name.disabled = !!document.getElementById("fw-editing-name")?.value;
    }
  }

  function clean() {
    const routerStatus = document.querySelector("#view-router .router-status-row");
    if (routerStatus) routerStatus.remove();

    const startRouter = document.getElementById("btn-start-router");
    if (startRouter) startRouter.remove();

    const addParser = document.getElementById("btn-new-parser");
    if (addParser) addParser.remove();

    const routerKpi = document.getElementById("kpi-router-status");
    if (routerKpi) {
      const card = routerKpi.closest(".kpi-card");
      if (card) card.remove();
    }
  }

  function boot() {
    clean();
    patchRouterBrowse();
    patchForwarder();

    setTimeout(() => { clean(); patchRouterBrowse(); patchForwarder(); }, 250);
    setTimeout(() => { clean(); patchRouterBrowse(); patchForwarder(); }, 750);
    setTimeout(() => { clean(); patchRouterBrowse(); patchForwarder(); }, 1500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  document.addEventListener("click", e => {
    const nav = e.target.closest(".nav-item");
    if (nav) setTimeout(() => { clean(); patchRouterBrowse(); patchForwarder(); }, 100);
  });

  window.validationUiPatch = { patchRouterBrowse, patchForwarder };
})();

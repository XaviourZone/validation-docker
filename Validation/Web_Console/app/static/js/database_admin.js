/* Database administration UI. PANS is a live XML folder watcher. */
(function () {
  "use strict";
  const api = (url, options) => fetch(url, Object.assign({headers:{"Content-Type":"application/json"}}, options || {})).then(async r => {
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || d.message || `HTTP ${r.status}`);
    return d;
  });

  function view() { return document.getElementById("view-database"); }

  function makePanel() {
    const v = view();
    if (!v || document.getElementById("pans-live-config")) return;
    const panel = document.createElement("div");
    panel.id = "pans-live-config";
    panel.className = "panel pans-config-panel";
    panel.innerHTML = `
      <div class="panel-header">
        <div>
          <span class="panel-title">PANS XML SOURCE</span>
          <div class="panel-subtitle">Live folder monitored by the PANS importer</div>
        </div>
        <span id="pans-watch-status" class="status-pill stopped">NOT CONFIGURED</span>
      </div>
      <div class="panel-body">
        <div class="pans-config-row">
          <div class="pans-config-field">
            <label class="form-label">XML Source Folder</label>
            <div class="pans-folder-line">
              <input id="pans-input-folder" class="form-input" type="text" readonly>
              <button type="button" class="btn btn-secondary" id="pans-browse">Browse…</button>
            </div>
            <div class="form-hint">New XML files in this folder are continuously detected and imported.</div>
          </div>
          <button type="button" class="btn btn-primary" id="pans-save">Save Folder</button>
        </div>
        <div id="pans-config-message" class="form-hint" style="margin-top:10px;"></div>
      </div>`;
    v.insertBefore(panel, v.firstElementChild || null);
    document.getElementById("pans-browse").onclick = () => openBrowser(document.getElementById("pans-input-folder"));
    document.getElementById("pans-save").onclick = saveFolder;
    loadConfig();
  }

  async function loadConfig() {
    try {
      const d = await api("/api/database/pans/config");
      document.getElementById("pans-input-folder").value = d.input_dir || "";
      const pill = document.getElementById("pans-watch-status");
      pill.textContent = d.input_dir ? "CONFIGURED" : "NOT CONFIGURED";
      pill.className = `status-pill ${d.input_dir ? "running" : "stopped"}`;
    } catch (e) { setMessage(e.message, true); }
  }

  async function saveFolder() {
    const folder = document.getElementById("pans-input-folder").value.trim();
    if (!folder) return setMessage("Select a PANS XML source folder first.", true);
    try {
      await api("/api/database/pans/config", {method:"POST", body:JSON.stringify({input_dir:folder})});
      setMessage("PANS source folder saved. The importer will restart and watch it continuously.");
      await loadConfig();
    } catch (e) { setMessage(e.message, true); }
  }

  function setMessage(message, error) {
    const el = document.getElementById("pans-config-message");
    if (el) { el.textContent = message; el.style.color = error ? "var(--accent-rose)" : "var(--text-secondary)"; }
  }

  function openBrowser(target) {
    let modal = document.getElementById("database-folder-browser");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "database-folder-browser";
      modal.className = "modal-backdrop active";
      modal.style.zIndex = "10100";
      modal.innerHTML = `<div class="modal-container" style="max-width:780px;">
        <div class="modal-header"><div class="modal-title">Select PANS XML folder</div><button class="modal-close-btn" id="dfb-close">✕</button></div>
        <div class="modal-body">
          <div class="form-group"><label class="form-label">Selected folder</label><input id="dfb-path" class="form-input" readonly></div>
          <div style="display:flex;gap:8px;margin-bottom:10px;"><button class="btn btn-secondary" id="dfb-up">Up</button><button class="btn btn-primary" id="dfb-select">Select this folder</button></div>
          <div id="dfb-list" style="max-height:420px;overflow:auto;border:1px solid var(--border-color);border-radius:6px;"></div>
          <div id="dfb-error" style="color:var(--accent-rose);margin-top:8px;"></div>
        </div></div>`;
      document.body.appendChild(modal);
      document.getElementById("dfb-close").onclick = () => modal.remove();
      document.getElementById("dfb-select").onclick = () => { target.value = document.getElementById("dfb-path").value; modal.remove(); };
      document.getElementById("dfb-up").onclick = async () => {
        const current = document.getElementById("dfb-path").value;
        const d = await browse(current);
        if (d.parent) browse(d.parent);
      };
    }
    const current = target.value.trim();
    browse(current);
    async function browse(path) {
      try {
        const url = `/api/database/filesystem/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`;
        const d = await api(url);
        if (d.roots) {
          document.getElementById("dfb-path").value = "";
          renderList((d.roots || []).map(x => ({...x, name:x.name})));
        } else {
          document.getElementById("dfb-path").value = d.path;
          renderList(d.entries || []);
        }
        document.getElementById("dfb-error").textContent = "";
        return d;
      } catch (e) { document.getElementById("dfb-error").textContent = e.message; return {}; }
    }
    function renderList(entries) {
      const list = document.getElementById("dfb-list"); list.innerHTML = "";
      if (!entries.length) { list.innerHTML = `<div style="padding:12px;color:var(--text-muted);">No readable folders</div>`; return; }
      entries.forEach(e => {
        const b = document.createElement("button");
        b.type = "button"; b.className = "btn btn-secondary";
        b.style.cssText = "display:block;width:100%;text-align:left;margin:3px 0;";
        b.disabled = e.readable === false;
        b.textContent = `📁 ${e.name}`;
        b.onclick = () => browse(e.path);
        list.appendChild(b);
      });
    }
  }

  function boot() {
    makePanel();
    setTimeout(makePanel, 400);
    setTimeout(makePanel, 1200);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
  document.addEventListener("click", e => {
    const nav = e.target.closest("[data-tab='database']");
    if (nav) setTimeout(makePanel, 50);
  });
})();

(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }

  async function requestJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error || data.success === false) {
      throw new Error(data.error || data.message || ("HTTP " + response.status));
    }
    return data;
  }

  function setFeedback(id, message, type) {
    const el = byId(id);
    if (!el) return;
    el.textContent = message || "";
    el.className = "database-feedback" + (type ? " " + type : "");
  }

  function setBusy(id, busy, text) {
    const button = byId(id);
    if (!button) return;
    if (busy) {
      if (!button.dataset.originalText) button.dataset.originalText = button.innerHTML;
      button.disabled = true;
      button.innerHTML = '<span class="loading-inline">' + (text || "Working…") + '</span>';
    } else {
      button.disabled = false;
      if (button.dataset.originalText) {
        button.innerHTML = button.dataset.originalText;
        delete button.dataset.originalText;
      }
    }
  }

  const selectedFolders = {wrs: null, pans: null};

  function renderWrsConfig(data) {
    const folder = byId("db-wrs-folder");
    const datasets = byId("db-wrs-datasets");
    const decode = byId("db-wrs-decode");
    if (folder) folder.value = data.input_dir || "";
    if (datasets) datasets.textContent = data.datasets_dir || "Not found";
    if (decode) decode.textContent = data.decode_dir || "Not found";
    setFeedback(
      "db-wrs-feedback",
      data.valid_structure
        ? "WRS folder structure is valid."
        : "Select a WRS folder containing Datasets and Decode files.",
      data.valid_structure ? "success" : "warning"
    );
  }

  function renderPansConfig(data) {
    const folder = byId("db-pans-folder");
    if (folder) folder.value = data.input_dir || "";
  }

  async function loadReferenceConfigs() {
    try { renderWrsConfig(await requestJson("/api/database/wrs/config")); } catch (_) {}
    try { renderPansConfig(await requestJson("/api/database/pans/config")); } catch (_) {}
  }

  function folderName(files) {
    const first = files && files[0];
    const rel = first && (first.webkitRelativePath || "");
    if (rel) return rel.split("/")[0] || first.name;
    return first ? first.name : "";
  }

  function setSelectedFolder(kind, input) {
    const files = Array.from(input?.files || []);
    if (!files.length) {
      selectedFolders[kind] = null;
      return;
    }

    selectedFolders[kind] = files;
    const name = folderName(files);
    const inputId = kind === "wrs" ? "db-wrs-folder" : "db-pans-folder";
    const folder = byId(inputId);
    if (folder) folder.value = name + "  •  " + files.length.toLocaleString() + " files";

    const feedbackId = kind === "wrs" ? "db-wrs-feedback" : "db-pans-feedback";
    setFeedback(feedbackId, "Folder selected. Click upload to load it into Validation.", "success");
  }

  function openNativeFolderPicker(kind) {
    const picker = byId(kind === "wrs" ? "db-wrs-folder-picker" : "db-pans-folder-picker");
    if (!picker) return;
    picker.value = "";
    picker.click();
  }

  async function uploadFolder(kind) {
    const files = selectedFolders[kind];
    const feedbackId = kind === "wrs" ? "db-wrs-feedback" : "db-pans-feedback";
    const buttonId = kind === "wrs" ? "btn-wrs-save-folder" : "btn-pans-save-folder";

    if (!files || !files.length) {
      setFeedback(feedbackId, "Select a folder from this computer first.", "error");
      return null;
    }

    const session = (window.crypto && crypto.randomUUID)
      ? crypto.randomUUID().replace(/-/g, "")
      : (Date.now().toString(36) + Math.random().toString(36).slice(2));

    const total = files.length;
    let uploaded = 0;
    let totalBytes = 0;

    setBusy(buttonId, true, "Uploading…");

    try {
      for (const file of files) {
        const relative = file.webkitRelativePath || file.name;
        const form = new FormData();
        form.append("file", file, file.name);
        form.append("relative_path", relative);

        await requestJson(
          "/api/database/folder/upload?kind=" + encodeURIComponent(kind) +
          "&session=" + encodeURIComponent(session),
          {method: "POST", body: form}
        );

        uploaded += 1;
        totalBytes += file.size || 0;
        setFeedback(
          feedbackId,
          "Uploading " + uploaded.toLocaleString() + " / " + total.toLocaleString() +
          " files (" + formatBytes(totalBytes) + ")…",
          "warning"
        );
      }

      const data = await requestJson(
        "/api/database/folder/finalize?kind=" + encodeURIComponent(kind) +
        "&session=" + encodeURIComponent(session),
        {method: "POST"}
      );

      if (kind === "wrs") {
        renderWrsConfig(data);
      } else {
        renderPansConfig(data);
      }

      setFeedback(feedbackId, data.message || "Folder uploaded and configured.", "success");
      selectedFolders[kind] = null;
      const picker = byId(kind === "wrs" ? "db-wrs-folder-picker" : "db-pans-folder-picker");
      if (picker) picker.value = "";
      if (window.consoleApp?.refresh) window.consoleApp.refresh();
      return data;
    } catch (error) {
      setFeedback(feedbackId, "Upload failed: " + error.message, "error");
      return null;
    } finally {
      setBusy(buttonId, false);
    }
  }

  function formatBytes(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = bytes;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }
    return value.toFixed(index ? 1 : 0) + " " + units[index];
  }

  async function updateWrs() {
    const data = await uploadFolder("wrs");
    if (!data) return;

    setBusy("btn-wrs-update", true, "Updating…");
    try {
      const refresh = await requestJson("/api/database/wrs/refresh", {method: "POST"});
      setFeedback("db-wrs-feedback", refresh.message || "WRS update started.", "success");
      if (window.consoleApp?.refresh) window.consoleApp.refresh();
    } catch (error) {
      setFeedback("db-wrs-feedback", error.message, "error");
    } finally {
      setBusy("btn-wrs-update", false);
    }
  }

  function updateFileLabel(inputId, labelId) {
    const input = byId(inputId);
    const label = byId(labelId);
    if (input && label) {
      label.textContent = input.files.length ? input.files[0].name : "No file selected";
    }
  }

  async function uploadNsc() {
    const east = byId("db-nsc-east-file");
    const west = byId("db-nsc-west-file");

    if ((!east || !east.files.length) && (!west || !west.files.length)) {
      setFeedback("db-nsc-feedback", "Select NSC EAST and/or NSC WEST file.", "error");
      return;
    }

    const form = new FormData();
    if (east?.files.length) form.append("east", east.files[0], east.files[0].name);
    if (west?.files.length) form.append("west", west.files[0], west.files[0].name);

    setBusy("btn-nsc-upload", true, "Uploading…");
    try {
      const data = await requestJson("/api/database/nsc/upload", {method: "POST", body: form});
      setFeedback("db-nsc-feedback", data.message || "NSC update started.", "success");
      if (east) east.value = "";
      if (west) west.value = "";
      updateFileLabel("db-nsc-east-file", "db-nsc-east-name");
      updateFileLabel("db-nsc-west-file", "db-nsc-west-name");
      if (window.consoleApp?.refresh) window.consoleApp.refresh();
    } catch (error) {
      setFeedback("db-nsc-feedback", error.message, "error");
    } finally {
      setBusy("btn-nsc-upload", false);
    }
  }

  const tableViewerState = {db: "", table: "", offset: 0, limit: 50, total: 0};

  async function openTableData(db, table, offset = 0) {
    if (!db || !table) return;
    tableViewerState.db = db;
    tableViewerState.table = table;
    tableViewerState.offset = offset;

    const modal = byId("database-table-modal");
    const title = byId("database-table-title");
    const meta = byId("database-table-meta");
    const tableEl = byId("database-table-view");
    const empty = byId("database-table-empty");
    const pageEl = byId("database-table-page");
    const prev = byId("database-table-prev");
    const next = byId("database-table-next");

    if (!modal || !tableEl) return;
    if (title) title.textContent = db + " / " + table;
    modal.classList.add("open");
    document.body.classList.add("modal-open");
    if (meta) meta.textContent = "Loading…";
    if (empty) empty.style.display = "none";
    if (tableEl.querySelector("thead")) tableEl.querySelector("thead").innerHTML = "";
    if (tableEl.querySelector("tbody")) tableEl.querySelector("tbody").innerHTML = "";

    try {
      const data = await requestJson(
        "/api/database/table?db=" + encodeURIComponent(db.toLowerCase()) +
        "&table=" + encodeURIComponent(table) +
        "&limit=" + tableViewerState.limit +
        "&offset=" + tableViewerState.offset
      );
      tableViewerState.total = Number(data.total || 0);

      const thead = tableEl.querySelector("thead");
      const tbody = tableEl.querySelector("tbody");
      const columns = data.columns || [];
      if (thead) {
        thead.innerHTML = "<tr>" + columns.map((col) => "<th></th>").join("") + "</tr>";
        [...thead.querySelectorAll("th")].forEach((th, i) => { th.textContent = columns[i]; });
      }

      if (tbody) {
        tbody.innerHTML = "";
        (data.rows || []).forEach((row) => {
          const tr = document.createElement("tr");
          columns.forEach((col) => {
            const td = document.createElement("td");
            td.style.fontFamily = "var(--font-mono)";
            td.style.fontSize = "11px";
            const value = row[col];
            td.textContent = value === null || value === undefined ? "" : String(value);
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
      }

      if (empty) empty.style.display = data.rows && data.rows.length ? "none" : "block";
      const first = tableViewerState.total ? tableViewerState.offset + 1 : 0;
      const last = Math.min(tableViewerState.offset + tableViewerState.limit, tableViewerState.total);
      if (meta) meta.textContent = "Rows " + first.toLocaleString() + "–" + last.toLocaleString() + " of " + tableViewerState.total.toLocaleString();
      if (pageEl) pageEl.textContent = "Page " + (Math.floor(tableViewerState.offset / tableViewerState.limit) + 1);
      if (prev) prev.disabled = tableViewerState.offset <= 0;
      if (next) next.disabled = tableViewerState.offset + tableViewerState.limit >= tableViewerState.total;
    } catch (error) {
      if (meta) meta.textContent = "Unable to load table: " + error.message;
      if (empty) {
        empty.textContent = "Unable to load table data.";
        empty.style.display = "block";
      }
    }
  }

  function closeTableData() {
    const modal = byId("database-table-modal");
    if (modal) modal.classList.remove("open");
    document.body.classList.remove("modal-open");
  }

  function initTableViewer() {
    byId("btn-db-view-data")?.addEventListener("click", () => {
      const selected = byId("db-view-table")?.value || "";
      if (!selected) {
        setFeedback("db-nsc-feedback", "Select a database table first.", "error");
        return;
      }
      const parts = selected.split("|");
      openTableData(parts[0], parts.slice(1).join("|"));
    });

    byId("database-table-close")?.addEventListener("click", closeTableData);
    byId("database-table-prev")?.addEventListener("click", () => {
      openTableData(tableViewerState.db, tableViewerState.table, Math.max(0, tableViewerState.offset - tableViewerState.limit));
    });
    byId("database-table-next")?.addEventListener("click", () => {
      openTableData(tableViewerState.db, tableViewerState.table, tableViewerState.offset + tableViewerState.limit);
    });
  }

  function init() {
    initTableViewer();
    loadReferenceConfigs();

    byId("btn-wrs-browse")?.addEventListener("click", () => openNativeFolderPicker("wrs"));
    byId("btn-pans-browse")?.addEventListener("click", () => openNativeFolderPicker("pans"));

    byId("db-wrs-folder-picker")?.addEventListener("change", function () {
      setSelectedFolder("wrs", this);
    });
    byId("db-pans-folder-picker")?.addEventListener("change", function () {
      setSelectedFolder("pans", this);
    });

    byId("btn-wrs-save-folder")?.addEventListener("click", () => uploadFolder("wrs"));
    byId("btn-wrs-update")?.addEventListener("click", updateWrs);
    byId("btn-pans-save-folder")?.addEventListener("click", () => uploadFolder("pans"));

    byId("db-nsc-east-file")?.addEventListener("change", () => updateFileLabel("db-nsc-east-file", "db-nsc-east-name"));
    byId("db-nsc-west-file")?.addEventListener("change", () => updateFileLabel("db-nsc-west-file", "db-nsc-west-name"));
    byId("btn-nsc-upload")?.addEventListener("click", uploadNsc);

    document.querySelectorAll('.nav-item[data-tab="database"]').forEach((el) => {
      el.addEventListener("click", () => loadReferenceConfigs());
    });
  }

  window.databaseTableViewer = { open: openTableData, close: closeTableData };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

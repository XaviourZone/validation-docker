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

  function renderWrsConfig(data) {
    const folder = byId("db-wrs-folder");
    const datasets = byId("db-wrs-datasets");
    const decode = byId("db-wrs-decode");
    if (folder) folder.value = data.input_dir || "";
    if (datasets) datasets.textContent = data.datasets_dir || "Not found";
    if (decode) decode.textContent = data.decode_dir || "Not found";
    setFeedback("db-wrs-feedback",
      data.valid_structure ? "WRS folder structure is valid." : "Select a WRS folder containing Datasets and Decode files.",
      data.valid_structure ? "success" : "warning");
  }

  function renderPansConfig(data) {
    const folder = byId("db-pans-folder");
    if (folder) folder.value = data.input_dir || "";
  }

  async function loadReferenceConfigs() {
    try { renderWrsConfig(await requestJson("/api/database/wrs/config")); } catch (_) {}
    try { renderPansConfig(await requestJson("/api/database/pans/config")); } catch (_) {}
  }

  async function saveFolder(kind) {
    const inputId = kind === "wrs" ? "db-wrs-folder" : "db-pans-folder";
    const feedbackId = kind === "wrs" ? "db-wrs-feedback" : "db-pans-feedback";
    const buttonId = kind === "wrs" ? "btn-wrs-save-folder" : "btn-pans-save-folder";
    const folder = (byId(inputId)?.value || "").trim();

    if (!folder) {
      setFeedback(feedbackId, "Select a folder first.", "error");
      return false;
    }

    setBusy(buttonId, true, "Saving…");
    try {
      const data = await requestJson("/api/database/" + kind + "/config", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({input_dir: folder})
      });
      setFeedback(feedbackId, data.message || "Folder saved.", "success");
      if (kind === "wrs") renderWrsConfig(data);
      return true;
    } catch (error) {
      setFeedback(feedbackId, error.message, "error");
      return false;
    } finally {
      setBusy(buttonId, false);
    }
  }

  async function updateWrs() {
    if (!await saveFolder("wrs")) return;
    setBusy("btn-wrs-update", true, "Updating…");
    try {
      const data = await requestJson("/api/database/wrs/refresh", {method: "POST"});
      setFeedback("db-wrs-feedback", data.message || "WRS update started.", "success");
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
    if (input && label) label.textContent = input.files.length ? input.files[0].name : "No file selected";
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

  function init() {
    loadReferenceConfigs();

    byId("btn-wrs-save-folder")?.addEventListener("click", () => saveFolder("wrs"));
    byId("btn-wrs-update")?.addEventListener("click", updateWrs);
    byId("btn-pans-save-folder")?.addEventListener("click", () => saveFolder("pans"));

    byId("db-nsc-east-file")?.addEventListener("change", () => updateFileLabel("db-nsc-east-file", "db-nsc-east-name"));
    byId("db-nsc-west-file")?.addEventListener("change", () => updateFileLabel("db-nsc-west-file", "db-nsc-west-name"));
    byId("btn-nsc-upload")?.addEventListener("click", uploadNsc);

    document.querySelectorAll('.nav-item[data-tab="database"]').forEach((el) => {
      el.addEventListener("click", () => loadReferenceConfigs());
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

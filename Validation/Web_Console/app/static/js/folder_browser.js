(function () {
  "use strict";

  const modal = document.getElementById("folder-browser-modal");
  const list = document.getElementById("folder-browser-list");
  const current = document.getElementById("folder-browser-current");
  const error = document.getElementById("folder-browser-error");
  const parentBtn = document.getElementById("folder-browser-parent");
  const selectBtn = document.getElementById("folder-browser-select");
  const cancelBtn = document.getElementById("folder-browser-cancel");
  const closeBtn = document.getElementById("folder-browser-close");
  const titleEl = modal ? modal.querySelector(".modal-title") : null;
  let currentPath = "";
  let targetInput = null;

  function showError(message) {
    if (!error) return;
    error.textContent = message || "";
    error.style.display = message ? "block" : "none";
  }

  function openModal(button) {
    if (!modal) return;
    const targetId = button && button.getAttribute("data-folder-browser-target");
    targetInput = targetId ? document.getElementById(targetId) : document.getElementById("src-folder");
    if (!targetInput) return;
    const customTitle = button && button.getAttribute("data-folder-browser-title");
    if (titleEl) titleEl.textContent = customTitle || "Select Input Folder";
    modal.classList.add("open");
    document.body.classList.add("modal-open");
    showError("");
    loadDirectory(targetInput.value || "");
  }

  function closeModal() {
    if (modal) modal.classList.remove("open");
    document.body.classList.remove("modal-open");
    targetInput = null;
    currentPath = "";
  }

  async function loadDirectory(path) {
    showError("");
    try {
      const url = path ? "/api/router/filesystem/browse?path=" + encodeURIComponent(path) : "/api/router/filesystem/browse";
      const response = await fetch(url);
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || "Unable to browse directory");

      if (data.roots) {
        currentPath = "";
        if (current) current.textContent = "Select a permitted root";
        if (parentBtn) parentBtn.disabled = true;
        renderEntries(data.roots);
        return;
      }

      currentPath = data.path || path;
      if (current) current.textContent = currentPath || "/";
      if (parentBtn) parentBtn.disabled = !data.parent || data.parent === currentPath;
      renderEntries(data.entries || []);
    } catch (e) {
      showError(e.message);
    }
  }

  function renderEntries(entries) {
    if (!list) return;
    list.innerHTML = "";
    if (!entries.length) {
      list.innerHTML = '<div class="folder-browser-empty">No folders found.</div>';
      return;
    }
    entries.forEach((entry) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "folder-browser-entry";
      row.disabled = entry.readable === false;
      row.innerHTML = '<span class="folder-icon">📁</span><span>' + escapeHtml(entry.name || entry.path) + '</span>';
      row.addEventListener("dblclick", () => {
        if (entry.readable !== false) loadDirectory(entry.path);
      });
      row.addEventListener("click", () => {
        if (entry.readable === false) return;
        list.querySelectorAll(".folder-browser-entry.selected").forEach(el => el.classList.remove("selected"));
        row.classList.add("selected");
        row.dataset.path = entry.path;
      });
      list.appendChild(row);
    });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (c) {
      return ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[c];
    });
  }

  document.querySelectorAll("[data-folder-browser-target]").forEach((button) => {
    button.addEventListener("click", () => openModal(button));
  });

  if (parentBtn) parentBtn.addEventListener("click", () => {
    if (!currentPath) return;
    const normalized = currentPath.replace(/[\/]$/, "");
    const parent = normalized.replace(/[\/][^\/]*$/, "") || (currentPath.includes("\") ? currentPath.slice(0, 3) : "/");
    loadDirectory(parent);
  });

  if (selectBtn) selectBtn.addEventListener("click", () => {
    const selected = list && list.querySelector(".folder-browser-entry.selected");
    const value = (selected && selected.dataset.path) || currentPath;
    if (value && targetInput) {
      targetInput.value = value;
      targetInput.dispatchEvent(new Event("input", {bubbles: true}));
      targetInput.dispatchEvent(new Event("change", {bubbles: true}));
      closeModal();
    } else {
      showError("Select a folder before continuing.");
    }
  });

  if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
  if (closeBtn) closeBtn.addEventListener("click", closeModal);
  if (modal) modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
})();

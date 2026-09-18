/**
 * VALIDATION MARITIME OPERATIONS CONSOLE — OPERATOR ENGINE
 * Pure Vanilla JavaScript (Zero External Libraries / Zero CDN Dependencies)
 */

(function () {
  "use strict";

  // State Management
  const state = {
    currentTab: "dashboard",
    pollIntervalMs: 3000,
    pollTimer: null,
    isPollingActive: true,
    parserDestinations: {},
    sources: [],
    confirmCallback: null,
  };

  // DOM Elements Cache
  const dom = {
    utcClock: document.getElementById("utc-clock"),
    systemHealthBadge: document.getElementById("system-health-badge"),
    topbarTitle: document.getElementById("topbar-title"),
    moduleCardsContainer: document.getElementById("module-cards-container"),
    routerStatusBadge: document.getElementById("router-status-badge"),
    routerUptime: document.getElementById("router-uptime"),
    routerThroughput: document.getElementById("router-throughput"),
    routerQueueDepth: document.getElementById("router-queue-depth"),
    routerAckCount: document.getElementById("router-ack-count"),
    routerFailCount: document.getElementById("router-fail-count"),
    routerRetryCount: document.getElementById("router-retry-count"),
    sourcesTableBody: document.getElementById("sources-table-body"),
    activityList: document.getElementById("activity-list"),
    errorList: document.getElementById("error-list"),
    toastContainer: document.getElementById("toast-container"),
    navItems: document.querySelectorAll(".nav-item"),
    viewTabs: document.querySelectorAll(".view-tab"),

    // Source Configuration Modal
    modalSourceConfig: document.getElementById("modal-source-config"),
    btnModalClose: document.getElementById("btn-modal-close"),
    btnModalCancel: document.getElementById("btn-modal-cancel"),
    btnModalValidate: document.getElementById("btn-modal-validate"),
    btnModalSave: document.getElementById("btn-modal-save"),
    btnAddSource: document.getElementById("btn-add-source"),
    modalTitleText: document.getElementById("modal-title-text"),
    modalFeedbackAlert: document.getElementById("modal-feedback-alert"),

    // Form inputs
    srcIsNew: document.getElementById("src-is-new"),
    srcName: document.getElementById("src-name"),
    srcDesc: document.getElementById("src-desc"),
    srcEnabled: document.getElementById("src-enabled"),
    srcType: document.getElementById("src-type"),
    btnTypeFile: document.getElementById("btn-type-file"),
    btnTypeTcp: document.getElementById("btn-type-tcp"),
    containerFieldsFile: document.getElementById("container-fields-file"),
    containerFieldsTcp: document.getElementById("container-fields-tcp"),
    srcFolder: document.getElementById("src-folder"),
    srcPatterns: document.getElementById("src-patterns"),
    srcStability: document.getElementById("src-stability"),
    srcPoll: document.getElementById("src-poll"),
    srcRemoteHost: document.getElementById("src-remote-host"),
    srcRemotePort: document.getElementById("src-remote-port"),
    srcFraming: document.getElementById("src-framing"),
    srcMaxLine: document.getElementById("src-max-line"),
    srcReconInit: document.getElementById("src-recon-init"),
    srcReconMax: document.getElementById("src-recon-max"),
    srcParser: document.getElementById("src-parser"),
    srcDerivedDestination: document.getElementById("src-derived-destination"),
    srcPreviewText: document.getElementById("src-preview-text"),
    previewBadge: document.getElementById("preview-badge"),

    // Confirmation Modal
    modalConfirmation: document.getElementById("modal-confirmation"),
    confirmTitle: document.getElementById("confirm-title"),
    confirmMessage: document.getElementById("confirm-message"),
    confirmSubtext: document.getElementById("confirm-subtext"),
    btnConfirmClose: document.getElementById("btn-confirm-close"),
    btnConfirmCancel: document.getElementById("btn-confirm-cancel"),
    btnConfirmProceed: document.getElementById("btn-confirm-proceed"),
  };

  // Initialize Application
  function init() {
    setupNavigation();
    setupClock();
    setupControls();
    setupModalListeners();
    fetchParserDestinations();
    fetchDashboardData();
    startPolling();

    // Pause polling when browser tab is inactive to save CPU
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        stopPolling();
      } else {
        fetchDashboardData();
        startPolling();
      }
    });
  }

  // Navigation Setup
  function setupNavigation() {
    dom.navItems.forEach((item) => {
      item.addEventListener("click", (e) => {
        e.preventDefault();
        const tabTarget = item.getAttribute("data-tab");
        if (!tabTarget) return;
        switchTab(tabTarget);
      });
    });
  }

  function switchTab(tabId) {
    state.currentTab = tabId;

    dom.navItems.forEach((item) => {
      item.classList.toggle("active", item.getAttribute("data-tab") === tabId);
    });

    dom.viewTabs.forEach((tab) => {
      tab.classList.toggle("active", tab.id === `view-${tabId}`);
    });

    const titleMap = {
      dashboard: "Validation Pipeline Dashboard",
      router: "Data Router Service — Ingestion & Transport",
      parser: "Data Parser Service — AIS & Stream Decoding",
      forwarder: "Downstream Forwarder",
      system: "System Configuration & Telemetry",
      logs: "Live Event Logs",
    };
    if (dom.topbarTitle) {
      dom.topbarTitle.textContent = titleMap[tabId] || "Validation Console";
    }

    fetchDashboardData();
  }

  // Live UTC Clock
  function setupClock() {
    function updateClock() {
      const now = new Date();
      if (dom.utcClock) {
        dom.utcClock.textContent = now.toISOString().replace("T", " ").substring(0, 19) + " UTC";
      }
    }
    updateClock();
    setInterval(updateClock, 1000);
  }

  // Polling Loop
  function startPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(fetchDashboardData, state.pollIntervalMs);
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  // Fetch Parser Destinations
  async function fetchParserDestinations() {
    try {
      const res = await fetch("/api/router/parser-destinations");
      if (res.ok) {
        state.parserDestinations = await res.json();
        populateParserDropdown();
      }
    } catch (err) {
      console.warn("Could not fetch parser destinations:", err);
    }
  }

  function populateParserDropdown() {
    if (!dom.srcParser) return;
    const currentVal = dom.srcParser.value;
    dom.srcParser.innerHTML = "";

    const parsers = Object.keys(state.parserDestinations);
    parsers.forEach((pName) => {
      const opt = document.createElement("option");
      opt.value = pName;
      const dest = state.parserDestinations[pName];
      opt.textContent = `${pName} (${dest.host}:${dest.port})`;
      dom.srcParser.appendChild(opt);
    });

    if (currentVal && parsers.includes(currentVal)) {
      dom.srcParser.value = currentVal;
    }
    onParserChange();
  }

  function onParserChange() {
    if (!dom.srcParser || !dom.srcDerivedDestination) return;
    const pName = dom.srcParser.value;
    const dest = state.parserDestinations[pName];
    if (dest) {
      dom.srcDerivedDestination.value = `${dest.host}:${dest.port} (${dest.framing || "ndjson"})`;
    } else {
      dom.srcDerivedDestination.value = "Unknown destination";
    }
    updateEffectivePreview();
  }

  // Fetch Primary Telemetry and Data
  async function fetchDashboardData() {
    try {
      const [sysRes, rtrStatusRes, rtrMetricsRes, rtrSrcRes, qRes, actRes, errRes, dbRes] = await Promise.allSettled([
        fetch("/api/system/status").then((r) => (r.ok ? r.json() : null)),
        fetch("/api/router/status").then((r) => (r.ok ? r.json() : null)),
        fetch("/api/router/metrics").then((r) => (r.ok ? r.json() : null)),
        fetch("/api/router/sources").then((r) => (r.ok ? r.json() : null)),
        fetch("/api/router/queue").then((r) => (r.ok ? r.json() : null)),
        fetch("/api/router/activity?limit=30").then((r) => (r.ok ? r.json() : null)),
        fetch("/api/router/errors?limit=15").then((r) => (r.ok ? r.json() : null)),
        fetch("/api/database/status").then((r) => (r.ok ? r.json() : null)),
      ]);

      if (sysRes.status === "fulfilled" && sysRes.value) {
        renderSystemStatus(sysRes.value);
      }

      if (rtrStatusRes.status === "fulfilled" && rtrStatusRes.value) {
        renderRouterTelemetry(rtrStatusRes.value);
      }

      if (rtrSrcRes.status === "fulfilled" && rtrSrcRes.value) {
        state.sources = rtrSrcRes.value;
        renderSourcesTable(rtrSrcRes.value);
      }

      if (actRes.status === "fulfilled" && actRes.value) {
        renderActivity(actRes.value);
      }

      if (errRes.status === "fulfilled" && errRes.value) {
        renderErrors(errRes.value);
      }

      if (dbRes.status === "fulfilled" && dbRes.value) {
        renderDatabaseTelemetry(dbRes.value);
      }

      // Fetch parser telemetry if on parser tab
      if (state.currentTab === "parser") {
        fetchParserData();
      }
    } catch (err) {
      console.error("Error polling dashboard data:", err);
    }
  }

  async function fetchParserData() {
    try {
      const res = await fetch("/api/parser/status");
      if (res.ok) {
        const data = await res.json();
        renderParserTelemetry(data);
      }
    } catch (err) {
      console.warn("Error fetching parser telemetry:", err);
    }
  }

  function renderParserTelemetry(data) {
    const reachable = data.reachable;
    const badge = document.getElementById("parser-service-badge");
    const uptimeEl = document.getElementById("parser-service-uptime");
    const msgRecvEl = document.getElementById("p-msg-received");
    const recProdEl = document.getElementById("p-rec-produced");
    const throuEl = document.getElementById("p-throughput");
    const rejEl = document.getElementById("p-rejected");
    const lastErrEl = document.getElementById("p-last-error");

    const metrics = data.metrics || {};
    const sources = metrics.sources || {};
    const recordsBySource = metrics.records_by_source || {};

    if (badge) {
      badge.textContent = reachable ? "RUNNING" : "STOPPED";
      badge.className = `status-pill ${reachable ? "running" : "stopped"}`;
    }
    if (uptimeEl) uptimeEl.textContent = "Uptime: " + formatUptime(metrics.uptime_seconds);
    if (msgRecvEl) msgRecvEl.textContent = metrics.messages_received || 0;
    if (recProdEl) recProdEl.textContent = metrics.total_records_produced || 0;
    if (throuEl) throuEl.textContent = `${metrics.processing_rate_records_sec || 0.0} rec/s`;
    if (rejEl) rejEl.textContent = metrics.messages_rejected || metrics.parse_errors || 0;
    if (lastErrEl) lastErrEl.textContent = metrics.last_error ? metrics.last_error.substring(0, 35) + "..." : "No errors";

    const updateSrc = (idPrefix, key) => {
      const envEl = document.getElementById(`p-${idPrefix}-env`);
      const recEl = document.getElementById(`p-${idPrefix}-rec`);
      if (envEl) envEl.textContent = sources[key] || 0;
      if (recEl) recEl.textContent = recordsBySource[key] || 0;
    };

    updateSrc("sais-ior", "SAIS_IOR");
    updateSrc("sais-global", "SAIS_GLOBAL");
    updateSrc("msis", "MSIS");
    updateSrc("lrit", "LRIT");
    updateSrc("vatms-east", "VATMS_EAST");
    updateSrc("vatms-west", "VATMS_WEST");
    updateSrc("nais", "NAIS");
  }

  // Render System Health & Pipeline Cards
  function renderSystemStatus(data) {
    if (dom.systemHealthBadge) {
      dom.systemHealthBadge.textContent = data.overall_status || "UNKNOWN";
      dom.systemHealthBadge.className = `status-pill ${getBadgeClass(data.overall_health)}`;
    }

    if (!dom.moduleCardsContainer) return;
    dom.moduleCardsContainer.innerHTML = "";

    (data.modules || []).forEach((mod) => {
      const card = document.createElement("div");
      card.className = "module-card";
      const badgeClass = getBadgeClass(mod.status);
      card.innerHTML = `
        <div>
          <div class="module-card-header">
            <span class="stage-badge">STAGE ${mod.stage}</span>
            <span class="status-pill ${badgeClass}">${mod.status}</span>
          </div>
          <div class="module-name">${mod.name}</div>
          <div class="module-desc">${mod.description}</div>
        </div>
        <div class="module-card-footer">
          <span style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono);">
            ${mod.implemented ? "Uptime: " + formatUptime(mod.uptime) : "Pending Integration"}
          </span>
          ${mod.implemented ? `<button class="btn btn-secondary" onclick="window.consoleApp.switchTab('${mod.id}')" style="padding: 4px 8px; font-size: 11px;">Inspect</button>` : `<span style="font-size: 11px; color: var(--text-muted);">-</span>`}
        </div>
      `;
      dom.moduleCardsContainer.appendChild(card);
    });
  }

  // Render Router Telemetry
  function renderRouterTelemetry(data) {
    const reachable = data.reachable;
    const totals = (data.metrics && data.metrics.totals) || {};
    const qHealth = data.queue_health || {};

    const serviceStatus = data.service_status || (reachable ? "RUNNING" : "STOPPED");
    const statusClass = getBadgeClass(serviceStatus);

    if (dom.routerStatusBadge) {
      dom.routerStatusBadge.textContent = serviceStatus;
      dom.routerStatusBadge.className = `status-pill ${statusClass}`;
    }

    const routerPagePill = document.getElementById("router-page-status-pill");
    if (routerPagePill) {
      routerPagePill.textContent = `● ${serviceStatus}`;
      routerPagePill.className = `status-pill ${statusClass}`;
    }

    const startBtn = document.getElementById("btn-start-router");
    if (startBtn) {
      if (serviceStatus === "RUNNING") {
        startBtn.style.display = "none";
      } else if (serviceStatus === "STARTING") {
        startBtn.style.display = "inline-flex";
        startBtn.disabled = true;
        startBtn.innerHTML = `<span style="display: inline-block; animation: spin 1s infinite linear;">⟳</span> Starting...`;
      } else {
        startBtn.style.display = "inline-flex";
        startBtn.disabled = false;
        startBtn.innerHTML = `<span>▶ Start Service</span>`;
      }
    }

    if (dom.routerUptime) {
      dom.routerUptime.textContent = formatUptime(data.metrics ? data.metrics.uptime_seconds : 0);
    }
    if (dom.routerThroughput) {
      dom.routerThroughput.innerHTML = `${totals.throughput_msg_per_sec || 0.0} <span class="unit">msg/s</span>`;
    }
    if (dom.routerQueueDepth) {
      dom.routerQueueDepth.innerHTML = `${qHealth.current_depth || 0} <span class="unit">/ ${qHealth.max_capacity || 10000}</span>`;
    }
    if (dom.routerAckCount) {
      dom.routerAckCount.textContent = totals.acknowledged || 0;
    }
    if (dom.routerFailCount) {
      dom.routerFailCount.textContent = totals.failed || 0;
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // SOURCES TABLE — STATIC, FIXED-LAYOUT RENDERING
  //
  // Design contract:
  //   • createSourceRow(src) builds ONE <tr> with 10 permanent cells.
  //     It is called ONCE per source, when the source first appears.
  //     The row's non-volatile cells (name, type, input config, parser,
  //     destination, action Edit/Delete) are written once and never touched
  //     again by the polling loop.
  //
  //   • renderSourcesTable(sources) on every poll cycle:
  //       - If a source row already exists  →  update only the 5 volatile
  //         cells (enabled, status, last activity, error, toggle button).
  //       - If a source row is missing       →  create it via createSourceRow.
  //       - If a source row is extra         →  remove it.
  //     The table header and colgroup are NEVER touched here.
  //
  //   • All cells always exist, even when their value is empty ("—").
  //     No cell is ever added or removed after first render.
  //
  //   • Long content (Input Config, Error) is clipped via CSS overflow:hidden
  //     and the full value is placed in the native title="" attribute.
  // ─────────────────────────────────────────────────────────────────────────

  /**
   * Build the volatile-cell HTML fragments shared by createSourceRow and the
   * in-place updater so the two always produce identical markup.
   */
  function _srcEnabledHtml(enabled) {
    return enabled
      ? `<span class="src-enabled-badge yes">YES</span>`
      : `<span class="src-enabled-badge no">NO</span>`;
  }

  function _srcStatusHtml(status) {
    const cls = getBadgeClass(status);
    const dot = "●";
    return `<span class="src-status-pill ${cls}">${dot} ${status || "UNKNOWN"}</span>`;
  }

  function _srcActivityHtml(lastActivity) {
    const v = formatTimestamp(lastActivity);
    return v || "—";
  }

  function _srcErrorHtml(lastError) {
    if (!lastError) {
      return `<span class="src-error-ok">—</span>`;
    }
    // Clip at 22 chars; full message available via native title on the cell
    const short = lastError.length > 22 ? lastError.substring(0, 22) + "…" : lastError;
    return `<span class="src-error-msg">${short}</span>`;
  }

  function _srcToggleHtml(sourceName, enabled) {
    return enabled
      ? `<button class="src-btn src-btn-disable" onclick="window.consoleApp.confirmToggleSource('${sourceName}', false)" title="Disable this source">Disable</button>`
      : `<button class="src-btn src-btn-enable"  onclick="window.consoleApp.confirmToggleSource('${sourceName}', true)"  title="Enable this source">Enable</button>`;
  }

  /**
   * Create one complete <tr> for a source.
   * This is called ONCE per source. The row is permanently keyed by
   * data-source-id. Non-volatile cells are written here and never touched
   * again by the polling loop.
   */
  function createSourceRow(src) {
    const tr = document.createElement("tr");
    tr.setAttribute("data-source-id", src.source_name);

    const destDisplay = src.destination_port
      ? `127.0.0.1:${src.destination_port}`
      : (src.destination || "—");

    const inputCfg = src.input_config || "—";

    // 10 cells in fixed order — cells are addressed by index in the updater
    tr.innerHTML = `
      <td class="src-cell-name" title="${src.source_name}">${src.source_name}</td>
      <td class="src-cell-vol-enabled">${_srcEnabledHtml(src.enabled)}</td>
      <td><span class="src-type-badge">${src.type || "?"}</span></td>
      <td class="src-cell-mono" title="${inputCfg}">${inputCfg}</td>
      <td><span class="src-parser-badge" title="${src.parser}">${src.parser}</span></td>
      <td class="src-cell-dest" title="${destDisplay}">${destDisplay}</td>
      <td class="src-cell-vol-status">${_srcStatusHtml(src.status)}</td>
      <td class="src-cell-mono src-cell-vol-activity">${_srcActivityHtml(src.last_activity)}</td>
      <td class="src-cell-vol-error" title="${src.last_error || ""}">${_srcErrorHtml(src.last_error)}</td>
      <td class="src-actions-cell">
        <div class="src-action-group">
          <button class="src-btn src-btn-edit"
                  onclick="window.consoleApp.openEditSourceModal('${src.source_name}')"
                  title="Edit source configuration">Edit</button>
          <span class="src-cell-vol-toggle">${_srcToggleHtml(src.source_name, src.enabled)}</span>
          <button class="src-btn src-btn-delete"
                  onclick="window.consoleApp.confirmDeleteSource('${src.source_name}')"
                  title="Delete this source">Delete</button>
        </div>
      </td>
    `;
    return tr;
  }

  /**
   * Update only the 5 volatile cells of an existing row.
   * Column structure, Edit button, Delete button, and all non-volatile
   * cells are untouched — this guarantees zero layout shift.
   */
  function updateSourceRowCells(tr, src) {
    const setCell = (selector, html) => {
      const el = tr.querySelector(selector);
      if (el && el.innerHTML !== html) el.innerHTML = html;
    };
    const setTitle = (selector, title) => {
      const el = tr.querySelector(selector);
      if (el && el.title !== title) el.title = title;
    };
    const setText = (selector, text) => {
      const el = tr.querySelector(selector);
      if (el && el.textContent !== text) el.textContent = text;
    };

    setCell(".src-cell-vol-enabled", _srcEnabledHtml(src.enabled));
    setCell(".src-cell-vol-status",  _srcStatusHtml(src.status));

    // Activity: text-only update avoids innerHTML reparse
    const actEl = tr.querySelector(".src-cell-vol-activity");
    if (actEl) {
      const actStr = _srcActivityHtml(src.last_activity);
      if (actEl.textContent !== actStr) actEl.textContent = actStr;
    }

    // Error: update cell content and native title for full-text tooltip
    setCell(".src-cell-vol-error",   _srcErrorHtml(src.last_error));
    setTitle(".src-cell-vol-error",  src.last_error || "");

    // Toggle button (Enable ↔ Disable)
    setCell(".src-cell-vol-toggle",  _srcToggleHtml(src.source_name, src.enabled));
  }

  /**
   * Main entry point called on every polling cycle.
   *
   * Strategy:
   *   1. Build a map of new sources by name.
   *   2. Walk existing rows — update volatile cells or remove if gone.
   *   3. Append any brand-new sources (preserving declaration order).
   *
   * The table header and colgroup are NEVER touched here.
   */
  function renderSourcesTable(sources) {
    if (!dom.sourcesTableBody) return;

    // ── No sources edge case ──
    if (!sources || sources.length === 0) {
      // Keep the no-sources row stable — only write if currently absent
      const existing = dom.sourcesTableBody.querySelector(".no-sources-row");
      if (!existing) {
        dom.sourcesTableBody.innerHTML =
          `<tr class="no-sources-row"><td colspan="10">No sources configured</td></tr>`;
      }
      return;
    }

    // Remove the placeholder row if it exists
    const placeholder = dom.sourcesTableBody.querySelector(".no-sources-row");
    if (placeholder) placeholder.remove();

    // Build lookup: name → source object (preserves ordering from config)
    const sourceMap = new Map(sources.map((s) => [s.source_name, s]));

    // ── Step 1: Update or remove existing rows ──
    const existingRows = Array.from(
      dom.sourcesTableBody.querySelectorAll("tr[data-source-id]")
    );
    for (const tr of existingRows) {
      const name = tr.getAttribute("data-source-id");
      if (!sourceMap.has(name)) {
        // Source was deleted — remove row
        tr.remove();
      } else {
        // Source still exists — update only volatile cells
        updateSourceRowCells(tr, sourceMap.get(name));
        sourceMap.delete(name); // mark as handled
      }
    }

    // ── Step 2: Append brand-new sources (in config order) ──
    for (const src of sources) {
      if (sourceMap.has(src.source_name)) {
        // Row did not exist yet — create and append
        dom.sourcesTableBody.appendChild(createSourceRow(src));
      }
    }
  }

  // Render Activity Log
  function renderActivity(events) {
    if (!dom.activityList) return;
    if (!events || events.length === 0) {
      dom.activityList.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-muted);">No recent activity recorded</div>`;
      return;
    }

    dom.activityList.innerHTML = events
      .slice(0, 30)
      .map((ev) => {
        const isError = ev.event.includes("failed") || ev.event.includes("lost") || ev.error;
        return `
          <div class="activity-item">
            <div class="activity-left">
              <span class="activity-badge ${isError ? "error" : ""}">${ev.event}</span>
              <span class="activity-msg">
                <strong>${ev.source}</strong> ${ev.filename ? `— <code>${ev.filename}</code>` : ""} ${ev.error ? `<span style="color: var(--accent-rose);">(${ev.error})</span>` : ""}
              </span>
            </div>
            <span class="activity-time">${ev.timestamp || "-"}</span>
          </div>
        `;
      })
      .join("");
  }

  // Render Errors List
  function renderErrors(errors) {
    if (!dom.errorList) return;
    if (!errors || errors.length === 0) {
      dom.errorList.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-muted);">No active delivery errors</div>`;
      return;
    }

    dom.errorList.innerHTML = errors
      .slice(0, 15)
      .map((err) => `
        <div class="activity-item" style="border-left: 3px solid var(--accent-rose);">
          <div class="activity-left">
            <span class="status-pill stopped" style="font-size: 10px;">${err.status || "FAILED"}</span>
            <span class="activity-msg">
              <strong>${err.source}</strong>: ${err.message || "Unknown error"} ${err.filename ? `(${err.filename})` : ""}
            </span>
          </div>
          <span class="activity-time">${formatTimestamp(err.timestamp)}</span>
        </div>
      `)
      .join("");
  }

  // Setup Safe Service Control Buttons
  function setupControls() {
    // Start Router Service button
    const startBtn = document.getElementById("btn-start-router");
    if (startBtn) {
      startBtn.addEventListener("click", async () => {
        startBtn.disabled = true;
        startBtn.innerHTML = `<span style="display: inline-block; animation: spin 1s infinite linear;">⟳</span> Starting...`;

        const routerPagePill = document.getElementById("router-page-status-pill");
        if (routerPagePill) {
          routerPagePill.textContent = "● STARTING";
          routerPagePill.className = "status-pill starting";
        }

        try {
          const res = await fetch("/api/router/start", { method: "POST" });
          const json = await res.json();
          if (res.ok && json.success) {
            showToast(json.message || "Data Router service started", "success");
          } else {
            showToast(json.message || json.error || "Failed to start Data Router", "error");
          }
        } catch (err) {
          showToast(`Start error: ${err.message}`, "error");
        }

        // Poll immediately and check actual service state
        for (let i = 0; i < 5; i++) {
          await new Promise((r) => setTimeout(r, 600));
          await fetchDashboardData();
          const curStatus = dom.routerStatusBadge ? dom.routerStatusBadge.textContent : "";
          if (curStatus === "RUNNING") break;
        }
      });
    }

    // Topbar manual refresh
    const refreshBtn = document.getElementById("btn-manual-refresh");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => {
        fetchDashboardData();
        showToast("Telemetry refreshed", "info");
      });
    }

    setupDatabaseControls();
  }

  function setupDatabaseControls() {
    const postAction = async (url, successMsg) => {
      try {
        const res = await fetch(url, { method: "POST" });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast(data.message || successMsg, "success");
        } else {
          showToast(data.message || data.error || "Operation failed", "error");
        }
      } catch (err) {
        showToast(`Error: ${err.message}`, "error");
      }
      fetchDashboardData();
    };

    const attachAction = (id, url, confirmTitle, confirmMsg, successMsg) => {
      const btn = document.getElementById(id);
      if (!btn) return;
      btn.addEventListener("click", () => {
        showConfirmModal({
          title: confirmTitle,
          message: confirmMsg,
          subtext: "This operation will affect the Validation pipeline.",
          confirmBtnText: "Confirm Action",
          onConfirm: () => postAction(url, successMsg)
        });
      });
    };

    attachAction("btn-wrs-refresh", "/api/database/wrs/refresh", "Refresh WRS Data?", "The WRS database will be rebuilt from files currently in RAW_DATA.", "WRS Refresh Started");
    attachAction("btn-wrs-clear", "/api/database/wrs/clear", "Clear WRS Database?", "This will drop all WRS tables. RAW_DATA files are NOT deleted.", "WRS Database Cleared");
    attachAction("btn-nsc-refresh", "/api/database/nsc/refresh", "Refresh NSC Data?", "The NSC database will be rebuilt from East/West files in RAW_DATA.", "NSC Refresh Started");
    attachAction("btn-nsc-clear", "/api/database/nsc/clear", "Clear NSC Database?", "This will delete all records from nsc_vessels. RAW_DATA files are NOT deleted.", "NSC Database Cleared");
    attachAction("btn-pans-clear", "/api/database/pans/clear", "Clear PANS Database?", "This will drop all PANS tables. The LIVE IMPORTER MUST BE STOPPED FIRST.", "PANS Database Cleared");

    const btnPansStart = document.getElementById("btn-pans-start");
    if (btnPansStart) btnPansStart.addEventListener("click", () => postAction("/api/database/pans/start", "PANS Importer started"));
    const btnPansStop = document.getElementById("btn-pans-stop");
    if (btnPansStop) btnPansStop.addEventListener("click", () => postAction("/api/database/pans/stop", "PANS Importer stopped"));
    const btnPansProcess = document.getElementById("btn-pans-process");
    if (btnPansProcess) btnPansProcess.addEventListener("click", () => postAction("/api/database/pans/process", "PANS one-shot process started"));
  }

  // Setup Modal Listeners (Add/Edit Form & Confirmation)
  function setupModalListeners() {
    if (dom.btnAddSource) {
      dom.btnAddSource.addEventListener("click", () => openAddSourceModal());
    }
    if (dom.btnModalClose) {
      dom.btnModalClose.addEventListener("click", () => closeSourceModal());
    }
    if (dom.btnModalCancel) {
      dom.btnModalCancel.addEventListener("click", () => closeSourceModal());
    }
    if (dom.btnTypeFile) {
      dom.btnTypeFile.addEventListener("click", () => selectSourceType("file"));
    }
    if (dom.btnTypeTcp) {
      dom.btnTypeTcp.addEventListener("click", () => selectSourceType("tcp"));
    }
    if (dom.srcParser) {
      dom.srcParser.addEventListener("change", () => onParserChange());
    }
    if (dom.btnModalValidate) {
      dom.btnModalValidate.addEventListener("click", () => validateSourceForm());
    }
    if (dom.btnModalSave) {
      dom.btnModalSave.addEventListener("click", () => saveSourceForm());
    }

    // Live preview update on form input
    const inputsToWatch = [
      dom.srcName,
      dom.srcDesc,
      dom.srcEnabled,
      dom.srcFolder,
      dom.srcPatterns,
      dom.srcStability,
      dom.srcPoll,
      dom.srcRemoteHost,
      dom.srcRemotePort,
      dom.srcFraming,
      dom.srcMaxLine,
      dom.srcReconInit,
      dom.srcReconMax,
    ];
    inputsToWatch.forEach((el) => {
      if (el) {
        el.addEventListener("input", () => updateEffectivePreview());
        el.addEventListener("change", () => updateEffectivePreview());
      }
    });

    // Confirmation Modal buttons
    if (dom.btnConfirmClose) {
      dom.btnConfirmClose.addEventListener("click", () => closeConfirmModal());
    }
    if (dom.btnConfirmCancel) {
      dom.btnConfirmCancel.addEventListener("click", () => closeConfirmModal());
    }
    if (dom.btnConfirmProceed) {
      dom.btnConfirmProceed.addEventListener("click", () => {
        if (typeof state.confirmCallback === "function") {
          state.confirmCallback();
        }
        closeConfirmModal();
      });
    }
  }

  // Confirmation Modal Runner
  function showConfirmModal({ title, message, subtext, confirmBtnText = "Confirm", onConfirm }) {
    if (!dom.modalConfirmation) return;
    if (dom.confirmTitle) dom.confirmTitle.textContent = title;
    if (dom.confirmMessage) dom.confirmMessage.textContent = message;
    if (dom.confirmSubtext) dom.confirmSubtext.textContent = subtext || "";
    if (dom.btnConfirmProceed) dom.btnConfirmProceed.textContent = confirmBtnText;

    state.confirmCallback = onConfirm;
    dom.modalConfirmation.classList.add("open");
  }

  function closeConfirmModal() {
    if (dom.modalConfirmation) dom.modalConfirmation.classList.remove("open");
    state.confirmCallback = null;
  }

  // Source Modal: Add Mode
  function openAddSourceModal() {
    if (!dom.modalSourceConfig) return;
    clearModalFeedback();

    if (dom.modalTitleText) dom.modalTitleText.textContent = "Add New Data Source";
    if (dom.srcIsNew) dom.srcIsNew.value = "true";
    if (dom.srcName) {
      dom.srcName.value = "";
      dom.srcName.disabled = false;
    }
    if (dom.srcDesc) dom.srcDesc.value = "";
    if (dom.srcEnabled) dom.srcEnabled.checked = true;

    // Reset File fields
    if (dom.srcFolder) dom.srcFolder.value = "";
    if (dom.srcPatterns) dom.srcPatterns.value = "*.csv, *.txt, *";
    if (dom.srcStability) dom.srcStability.value = "1.0";
    if (dom.srcPoll) dom.srcPoll.value = "1.0";

    // Reset TCP fields
    if (dom.srcRemoteHost) dom.srcRemoteHost.value = "127.0.0.1";
    if (dom.srcRemotePort) dom.srcRemotePort.value = "20005";
    if (dom.srcFraming) dom.srcFraming.value = "line";
    if (dom.srcMaxLine) dom.srcMaxLine.value = "65536";
    if (dom.srcReconInit) dom.srcReconInit.value = "2.0";
    if (dom.srcReconMax) dom.srcReconMax.value = "60.0";

    selectSourceType("file");
    populateParserDropdown();
    updateEffectivePreview();

    dom.modalSourceConfig.classList.add("open");
  }

  // Source Modal: Edit Mode
  function openEditSourceModal(sourceName) {
    if (!dom.modalSourceConfig) return;
    clearModalFeedback();

    const src = state.sources.find((s) => s.source_name === sourceName);
    if (!src) {
      showToast(`Source '${sourceName}' not found`, "error");
      return;
    }

    const cfg = src.raw_config || {};

    if (dom.modalTitleText) dom.modalTitleText.textContent = `Edit Data Source: ${sourceName}`;
    if (dom.srcIsNew) dom.srcIsNew.value = "false";
    if (dom.srcName) {
      dom.srcName.value = sourceName;
      dom.srcName.disabled = true; // Key identifier is fixed in edit mode
    }
    if (dom.srcDesc) dom.srcDesc.value = cfg.description || "";
    if (dom.srcEnabled) dom.srcEnabled.checked = cfg.enabled !== false;

    const stype = (cfg.type || src.type || "file").toLowerCase();
    selectSourceType(stype);

    if (stype === "file") {
      if (dom.srcFolder) dom.srcFolder.value = cfg.folder || sourceName;
      const pats = cfg.file_patterns || ["*.csv", "*.txt", "*"];
      if (dom.srcPatterns) dom.srcPatterns.value = Array.isArray(pats) ? pats.join(", ") : pats;
      if (dom.srcStability) dom.srcStability.value = cfg.stability_window_seconds || 1.0;
      if (dom.srcPoll) dom.srcPoll.value = cfg.poll_interval_seconds || 1.0;
    } else {
      if (dom.srcRemoteHost) dom.srcRemoteHost.value = cfg.remote_host || "127.0.0.1";
      if (dom.srcRemotePort) dom.srcRemotePort.value = cfg.remote_port || 20001;
      if (dom.srcFraming) dom.srcFraming.value = cfg.framing || "line";
      if (dom.srcMaxLine) dom.srcMaxLine.value = cfg.max_line_length || 65536;
      if (dom.srcReconInit) dom.srcReconInit.value = cfg.reconnect_initial_delay || 2.0;
      if (dom.srcReconMax) dom.srcReconMax.value = cfg.reconnect_max_delay || 60.0;
    }

    populateParserDropdown();
    if (dom.srcParser && cfg.parser) {
      dom.srcParser.value = cfg.parser;
    }
    onParserChange();
    updateEffectivePreview();

    dom.modalSourceConfig.classList.add("open");
  }

  function closeSourceModal() {
    if (dom.modalSourceConfig) dom.modalSourceConfig.classList.remove("open");
  }

  function selectSourceType(type) {
    const isFile = type === "file";
    if (dom.srcType) dom.srcType.value = isFile ? "file" : "tcp";

    if (dom.btnTypeFile) dom.btnTypeFile.classList.toggle("active", isFile);
    if (dom.btnTypeTcp) dom.btnTypeTcp.classList.toggle("active", !isFile);

    if (dom.containerFieldsFile) dom.containerFieldsFile.style.display = isFile ? "block" : "none";
    if (dom.containerFieldsTcp) dom.containerFieldsTcp.style.display = isFile ? "none" : "block";

    updateEffectivePreview();
  }

  // Construct Form Payload
  function getSourceFormData() {
    const isNew = dom.srcIsNew ? dom.srcIsNew.value === "true" : true;
    const name = dom.srcName ? dom.srcName.value.trim() : "";
    const desc = dom.srcDesc ? dom.srcDesc.value.trim() : "";
    const enabled = dom.srcEnabled ? dom.srcEnabled.checked : true;
    const type = dom.srcType ? dom.srcType.value : "file";
    const parser = dom.srcParser ? dom.srcParser.value : "";

    const payload = {
      is_new: isNew,
      source_name: name,
      description: desc,
      enabled: enabled,
      type: type,
      parser: parser,
    };

    if (type === "file") {
      payload.folder = dom.srcFolder ? dom.srcFolder.value.trim() : "";
      const rawPats = dom.srcPatterns ? dom.srcPatterns.value : "";
      payload.file_patterns = rawPats.split(",").map((p) => p.trim()).filter(Boolean);
      payload.stability_window_seconds = parseFloat(dom.srcStability ? dom.srcStability.value : 1.0) || 1.0;
      payload.poll_interval_seconds = parseFloat(dom.srcPoll ? dom.srcPoll.value : 1.0) || 1.0;
      payload.preserve_file = true;
    } else {
      payload.remote_host = dom.srcRemoteHost ? dom.srcRemoteHost.value.trim() : "";
      payload.remote_port = parseInt(dom.srcRemotePort ? dom.srcRemotePort.value : 0, 10) || 0;
      payload.framing = dom.srcFraming ? dom.srcFraming.value : "line";
      payload.delimiter = "\n";
      payload.max_line_length = parseInt(dom.srcMaxLine ? dom.srcMaxLine.value : 65536, 10) || 65536;
      payload.reconnect_initial_delay = parseFloat(dom.srcReconInit ? dom.srcReconInit.value : 2.0) || 2.0;
      payload.reconnect_max_delay = parseFloat(dom.srcReconMax ? dom.srcReconMax.value : 60.0) || 60.0;
      payload.reconnect_multiplier = 2.0;
    }

    return payload;
  }

  // Update Effective Preview Box
  function updateEffectivePreview() {
    if (!dom.srcPreviewText) return;
    const data = getSourceFormData();
    const dest = state.parserDestinations[data.parser];
    const destStr = dest ? `${dest.host}:${dest.port}` : "None";

    let text = `Source:      ${data.source_name || "<unnamed>"}\n`;
    text += `Type:        ${data.type.toUpperCase()}\n`;
    if (data.type === "file") {
      text += `Folder:      ${data.folder || "<none>"}\n`;
      text += `Patterns:    [${(data.file_patterns || []).join(", ")}]\n`;
      text += `Stability:   ${data.stability_window_seconds}s (Poll: ${data.poll_interval_seconds}s)\n`;
    } else {
      text += `Host:Port:   ${data.remote_host || "<none>"}:${data.remote_port || 0}\n`;
      text += `Framing:     ${data.framing} (Delimiter: \\n)\n`;
      text += `Reconnect:   ${data.reconnect_initial_delay}s -> ${data.reconnect_max_delay}s\n`;
    }
    text += `Parser:      ${data.parser || "<none>"} -> ${destStr}\n`;
    text += `Status:      ${data.enabled ? "ENABLED" : "DISABLED"}`;

    dom.srcPreviewText.textContent = text;
  }

  // Validate Source Form
  async function validateSourceForm() {
    clearModalFeedback();
    const payload = getSourceFormData();

    if (dom.btnModalValidate) dom.btnModalValidate.disabled = true;

    try {
      const res = await fetch("/api/router/sources/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = await res.json();

      if (res.ok && json.valid) {
        showModalFeedback("success", "✓ Configuration syntax and semantic checks PASSED.");
        if (dom.previewBadge) dom.previewBadge.style.display = "inline-block";
      } else {
        const errorList = (json.errors || [json.message || "Validation failed"]).map((e) => `• ${e}`).join("\n");
        showModalFeedback("error", `Configuration validation FAILED:\n${errorList}`);
        if (dom.previewBadge) dom.previewBadge.style.display = "none";
      }
    } catch (err) {
      showModalFeedback("error", `Network/Server Error: ${err.message}`);
    } finally {
      if (dom.btnModalValidate) dom.btnModalValidate.disabled = false;
    }
  }

  // Save Source Form
  async function saveSourceForm() {
    clearModalFeedback();
    const payload = getSourceFormData();

    if (dom.btnModalSave) {
      dom.btnModalSave.disabled = true;
      dom.btnModalSave.innerHTML = `⟳ Saving...`;
    }

    try {
      const res = await fetch("/api/router/sources/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = await res.json();

      if (res.ok && json.success) {
        closeSourceModal();
        showToast(`Configuration saved for '${json.source}'. Reload required to apply.`, "success");
        fetchDashboardData();
      } else {
        const errs = json.message || "Failed to save configuration";
        showModalFeedback("error", `Save rejected: ${errs}`);
      }
    } catch (err) {
      showModalFeedback("error", `Network Error: ${err.message}`);
    } finally {
      if (dom.btnModalSave) {
        dom.btnModalSave.disabled = false;
        dom.btnModalSave.innerHTML = `💾 Save Configuration`;
      }
    }
  }

  function showModalFeedback(type, text) {
    if (!dom.modalFeedbackAlert) return;
    dom.modalFeedbackAlert.style.display = "block";
    dom.modalFeedbackAlert.style.whiteSpace = "pre-wrap";
    if (type === "success") {
      dom.modalFeedbackAlert.style.background = "rgba(16, 185, 129, 0.15)";
      dom.modalFeedbackAlert.style.border = "1px solid var(--accent-emerald)";
      dom.modalFeedbackAlert.style.color = "var(--status-running-text)";
    } else {
      dom.modalFeedbackAlert.style.background = "rgba(244, 63, 94, 0.15)";
      dom.modalFeedbackAlert.style.border = "1px solid var(--accent-rose)";
      dom.modalFeedbackAlert.style.color = "var(--accent-rose)";
    }
    dom.modalFeedbackAlert.textContent = text;
  }

  function clearModalFeedback() {
    if (dom.modalFeedbackAlert) {
      dom.modalFeedbackAlert.style.display = "none";
      dom.modalFeedbackAlert.textContent = "";
    }
    if (dom.previewBadge) dom.previewBadge.style.display = "none";
  }

  // Toast Notifications
  function showToast(message, type = "info") {
    if (!dom.toastContainer) return;
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${message}</span>`;
    dom.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(50px)";
      toast.style.transition = "all 0.3s ease";
      setTimeout(() => toast.remove(), 300);
    }, 4500);
  }

  // Formatting Helpers
  function getBadgeClass(status) {
    if (!status) return "notimpl";
    const s = status.toUpperCase();
    if (s.includes("RUNNING") || s.includes("HEALTHY") || s.includes("CONNECTED") || s.includes("ACTIVE")) return "running";
    if (s.includes("STOPPED") || s.includes("OFFLINE") || s.includes("FAILED") || s.includes("DISCONNECTED")) return "stopped";
    if (s.includes("DEGRADED") || s.includes("WARNING") || s.includes("WAITING")) return "degraded";
    return "notimpl";
  }

  function formatUptime(seconds) {
    if (!seconds || seconds <= 0) return "0s";
    const s = Math.floor(seconds);
    const hrs = Math.floor(s / 3600);
    const mins = Math.floor((s % 3600) / 60);
    const secs = s % 60;
    if (hrs > 0) return `${hrs}h ${mins}m ${secs}s`;
    if (mins > 0) return `${mins}m ${secs}s`;
    return `${secs}s`;
  }

  function formatTimestamp(isoStr) {
    if (!isoStr) return "-";
    try {
      return isoStr.replace("T", " ").substring(0, 19);
    } catch {
      return isoStr;
    }
  }

  // Global Actions Exposed to Window
  window.consoleApp = {
    switchTab,
    refresh: fetchDashboardData,
    openAddSourceModal,
    openEditSourceModal,
    selectSourceType,
    onParserChange,
    confirmToggleSource: (sourceName, enable) => {
      const actionStr = enable ? "enable" : "disable";
      if (!enable) {
        showConfirmModal({
          title: `Disable Source '${sourceName}'?`,
          message: `The Router will stop ingesting messages from feed '${sourceName}' once configuration is reloaded.`,
          subtext: "You can re-enable this source at any time without data loss.",
          confirmBtnText: "Confirm Disable",
          onConfirm: async () => {
            await executeToggle(sourceName, false);
          },
        });
      } else {
        executeToggle(sourceName, true);
      }
    },
    confirmDeleteSource: (sourceName) => {
      showConfirmModal({
        title: `Delete Source '${sourceName}'?`,
        message: `This will permanently remove '${sourceName}' from sources.yaml. Ingestion will terminate upon router reload.`,
        subtext: "Historical database records and logs will remain preserved.",
        confirmBtnText: "Delete Source",
        onConfirm: async () => {
          try {
            const res = await fetch(`/api/router/sources/${encodeURIComponent(sourceName)}/delete`, { method: "POST" });
            const json = await res.json();
            if (res.ok && json.success) {
              showToast(`Source '${sourceName}' deleted. Reload required to apply.`, "success");
            } else {
              showToast(json.message || "Failed to delete source", "error");
            }
          } catch (err) {
            showToast(`Error: ${err.message}`, "error");
          } finally {
            fetchDashboardData();
          }
        },
      });
    },
  };

  async function executeToggle(sourceName, enable) {
    const action = enable ? "enable" : "disable";
    try {
      const res = await fetch(`/api/router/sources/${encodeURIComponent(sourceName)}/${action}`, { method: "POST" });
      const json = await res.json();
      if (res.ok && json.success) {
        showToast(json.message, "success");
      } else {
        showToast(json.message || "Failed to toggle source", "error");
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, "error");
    } finally {
      fetchDashboardData();
    }
  }

  function renderDatabaseTelemetry(data) {
    const setElem = (id, text, color = null) => {
      const el = document.getElementById(id);
      if (el) {
        el.textContent = text;
        if (color) el.style.color = color;
      }
    };
    
    const renderStatus = (id, status, isRefreshing) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = isRefreshing ? "REFRESHING" : status;
      if (isRefreshing) {
        el.className = "status-pill starting";
      } else {
        el.className = "status-pill " + (status === "READY" || status === "LIVE" ? "running" : (status === "MISSING" ? "degraded" : "stopped"));
      }
    };

    // WRS
    if (data.wrs) {
      renderStatus("db-wrs-status", data.wrs.status, data.wrs.is_refreshing);
      setElem("db-wrs-file", data.wrs.database);
      setElem("db-wrs-size", data.wrs.size_mb + " MB");
      setElem("db-wrs-tables", data.wrs.table_count);
      setElem("db-wrs-records", data.wrs.row_count);
      setElem("db-wrs-last", data.wrs.last_import);
    }
    
    // NSC
    if (data.nsc) {
      renderStatus("db-nsc-status", data.nsc.status, data.nsc.is_refreshing);
      setElem("db-nsc-file", data.nsc.database);
      setElem("db-nsc-size", data.nsc.size_mb + " MB");
      setElem("db-nsc-tables", data.nsc.table_count);
      setElem("db-nsc-records", data.nsc.row_count);
      setElem("db-nsc-east", data.nsc.east_count);
      setElem("db-nsc-west", data.nsc.west_count);
      setElem("db-nsc-last", data.nsc.last_import);
    }
    
    // PANS
    if (data.pans) {
      renderStatus("db-pans-status", data.pans.status, false);
      const impEl = document.getElementById("db-pans-importer-status");
      if (impEl) {
        impEl.textContent = data.pans.importer_status;
        impEl.className = "status-pill " + (data.pans.importer_status === "RUNNING" ? "running" : "stopped");
      }
      setElem("db-pans-size", data.pans.size_mb + " MB");
      setElem("db-pans-tables", data.pans.table_count);
      setElem("db-pans-records", data.pans.row_count);
      setElem("db-pans-files", data.pans.files_processed);
      setElem("db-pans-last", data.pans.last_update);
    }
    
    // Populate Tables Inventory
    const tbody = document.getElementById("db-tables-body");
    if (tbody) {
      const rows = [];
      const addTables = (dbName, tablesDict) => {
        if (!tablesDict) return;
        Object.keys(tablesDict).sort().forEach(tName => {
          rows.push(`<tr>
            <td><strong style="color: var(--accent-cyan); font-size: 11px;">${dbName}</strong></td>
            <td style="font-family: var(--font-mono); font-size: 11px;">${tName}</td>
            <td style="font-family: var(--font-mono); font-size: 11px;">${tablesDict[tName]}</td>
          </tr>`);
        });
      };
      if (data.wrs) addTables("WRS", data.wrs.tables);
      if (data.pans) addTables("PANS", data.pans.tables);
      if (data.nsc) addTables("NSC", data.nsc.tables);
      
      if (rows.length === 0) {
        tbody.innerHTML = `<tr><td colspan="3" style="text-align: center;">No tables found in active databases</td></tr>`;
      } else {
        tbody.innerHTML = rows.join("");
      }
    }
  }

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

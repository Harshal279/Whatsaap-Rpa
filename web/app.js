/**
 * app.js
 * -------
 * WhatsApp RPA Automator — Web UI JavaScript
 * Handles all UI logic, SocketIO events, and API calls.
 */

"use strict";

// ── SocketIO connection ───────────────────────────────────────────────────────
const socket = io({ transports: ["websocket", "polling"] });

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  contacts: [],
  excelFile: null,
  attachFile: null,
  mode: "known",
  browser: "Chrome",
  running: false,
  paused: false,
  sent: 0,
  failed: 0,
  skipped: 0,
  total: 0,
  resultRowCount: 0,
  settingsSnapshot: null,
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const dom = {
  // Navbar
  statusDot:      $("statusDot"),
  statusText:     $("statusText"),

  // Excel
  excelDropZone:  $("excelDropZone"),
  excelInput:     $("excelInput"),
  excelFileInfo:  $("excelFileInfo"),
  excelFileName:  $("excelFileName"),
  excelReloadBtn: $("excelReloadBtn"),
  excelDropInner: $("excelDropInner"),
  contactCount:   $("contactCount"),
  contactCountNum:$("contactCountNum"),
  dedupCheck:     $("dedupCheck"),

  // Browser
  browserSelect:  $("browserSelect"),

  // Mode
  modeKnown:      $("modeKnown"),
  modeUnknown:    $("modeUnknown"),
  modeDesc:       $("modeDesc"),

  // Attachment
  attachDropZone: $("attachDropZone"),
  attachInput:    $("attachInput"),
  attachFileInfo: $("attachFileInfo"),
  attachFileName: $("attachFileName"),
  attachClearBtn: $("attachClearBtn"),
  attachDropInner:$("attachDropInner"),

  // Buttons
  openSettings:   $("openSettings"),
  startBtn:       $("startBtn"),
  pauseBtn:       $("pauseBtn"),
  stopBtn:        $("stopBtn"),
  reportsBtn:     $("reportsBtn"),

  // Stats
  statTotalVal:   $("statTotalVal"),
  statSentVal:    $("statSentVal"),
  statFailedVal:  $("statFailedVal"),
  statSkippedVal: $("statSkippedVal"),

  // Progress
  progressBar:    $("progressBar"),
  progressLabel:  $("progressLabel"),

  // Tabs
  tabResults:     $("tabResults"),
  tabConsole:     $("tabConsole"),
  panelResults:   $("panelResults"),
  panelConsole:   $("panelConsole"),
  clearConsoleBtn:$("clearConsoleBtn"),

  // Results
  resultsEmpty:   $("resultsEmpty"),
  resultsTable:   $("resultsTable"),
  resultsBody:    $("resultsBody"),

  // Console
  consoleOutput:  $("consoleOutput"),

  // Settings modal
  settingsOverlay:$("settingsOverlay"),
  settingsClose:  $("settingsClose"),
  settingsCancel: $("settingsCancel"),
  settingsSave:   $("settingsSave"),
  settingsReset:  $("settingsReset"),

  // Reports modal
  reportsOverlay: $("reportsOverlay"),
  reportsClose:   $("reportsClose"),
  reportsList:    $("reportsList"),
  reportsEmpty:   $("reportsEmpty"),

  // Toast
  toast:          $("toast"),

  // Settings inputs
  s_delay_min:    $("s_delay_min"),
  s_delay_max:    $("s_delay_max"),
  s_warmup_count: $("s_warmup_count"),
  s_warmup_min:   $("s_warmup_min"),
  s_warmup_max:   $("s_warmup_max"),
  s_occasional_n: $("s_occasional_n"),
  s_occasional_min:$("s_occasional_min"),
  s_occasional_max:$("s_occasional_max"),
  s_batch_min:    $("s_batch_min"),
  s_batch_max:    $("s_batch_max"),
  s_deep_min:     $("s_deep_min"),
  s_deep_max:     $("s_deep_max"),
  s_fwd_min:      $("s_fwd_min"),
  s_fwd_max:      $("s_fwd_max"),
  s_retry:        $("s_retry"),
  s_retry_delay:  $("s_retry_delay"),
};

// ── Toast helper ──────────────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg, type = "info", duration = 3000) {
  dom.toast.textContent = msg;
  dom.toast.className = `toast ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { dom.toast.classList.add("hidden"); }, duration);
}

// ── Nav status helper ─────────────────────────────────────────────────────────
function setNavStatus(text, dotClass = "idle") {
  dom.statusText.textContent = text;
  dom.statusDot.className = `status-dot ${dotClass}`;
}

// ── Stat counter helper ───────────────────────────────────────────────────────
function setStat(el, value) {
  el.textContent = value;
  el.classList.remove("bump");
  void el.offsetWidth; // reflow to restart animation
  el.classList.add("bump");
  setTimeout(() => el.classList.remove("bump"), 300);
}

// ── Progress bar ──────────────────────────────────────────────────────────────
function setProgress(percent) {
  dom.progressBar.style.width = `${percent}%`;
  dom.progressBar.setAttribute("aria-valuenow", percent);
  dom.progressLabel.textContent = `${Math.round(percent)}%`;
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function activateTab(tabId) {
  const tabs = { tabResults: "panelResults", tabConsole: "panelConsole" };
  Object.entries(tabs).forEach(([btnId, panelId]) => {
    const btn = dom[btnId]; const panel = dom[panelId];
    const active = btnId === tabId;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active);
    panel.classList.toggle("active", active);
  });
}

dom.tabResults.addEventListener("click", () => activateTab("tabResults"));
dom.tabConsole.addEventListener("click", () => activateTab("tabConsole"));

// ── Console logging ───────────────────────────────────────────────────────────
function appendLog(message, level = "INFO", timestamp = null) {
  const ts = timestamp || new Date().toLocaleTimeString("en-GB", { hour12: false });
  const line = document.createElement("div");
  line.className = `log-line ${level}`;
  line.innerHTML = `<span class="log-time">[${ts}]</span><span class="log-msg">${escapeHtml(message)}</span>`;
  dom.consoleOutput.appendChild(line);
  dom.consoleOutput.scrollTop = dom.consoleOutput.scrollHeight;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

dom.clearConsoleBtn.addEventListener("click", () => {
  dom.consoleOutput.innerHTML = "";
});

// ── Results table ─────────────────────────────────────────────────────────────
function appendResult(name, phone, status) {
  state.resultRowCount++;
  dom.resultsEmpty.classList.add("hidden");
  dom.resultsTable.hidden = false;

  const row = document.createElement("tr");
  const statusLower = status.toLowerCase();
  const statusBadge = `<span class="status-badge ${statusLower}">${status}</span>`;
  row.innerHTML = `
    <td>${state.resultRowCount}</td>
    <td>${escapeHtml(name)}</td>
    <td>+${escapeHtml(phone)}</td>
    <td>${statusBadge}</td>`;
  dom.resultsBody.appendChild(row);
  row.scrollIntoView({ block: "nearest" });
}

// ── Engine state update ───────────────────────────────────────────────────────
function applyEngineState(running, paused) {
  state.running = running;
  state.paused = paused;

  dom.startBtn.disabled = running;
  dom.pauseBtn.disabled = !running;
  dom.stopBtn.disabled = !running;

  if (running && paused) {
    dom.pauseBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg> RESUME`;
    setNavStatus("Paused", "paused");
  } else if (running) {
    dom.pauseBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg> PAUSE`;
    setNavStatus("Running…", "running");
  } else {
    dom.pauseBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg> PAUSE`;
    setNavStatus("Ready", "idle");
  }
}

// ── SocketIO event handlers ───────────────────────────────────────────────────
socket.on("connect", () => {
  appendLog("Connected to server.", "SUCCESS");
});

socket.on("disconnect", () => {
  setNavStatus("Disconnected", "error");
  appendLog("Disconnected from server.", "ERROR");
});

socket.on("log", ({ message, level, timestamp }) => {
  appendLog(message, level, timestamp);
  // If block detected — switch to console tab
  if (message.includes("⛔ Blocked:")) activateTab("tabConsole");
});

socket.on("status", ({ message }) => {
  setNavStatus(message, state.running ? (state.paused ? "paused" : "running") : "idle");
});

socket.on("progress", ({ current, total, percent }) => {
  setProgress(percent);
  state.total = total;
});

socket.on("contact_result", ({ name, phone, status, error }) => {
  appendResult(name, phone, status);
  activateTab("tabResults");

  const statusUp = status.toUpperCase();
  if (statusUp === "SUCCESS") { state.sent++;    setStat(dom.statSentVal,    state.sent); }
  if (statusUp === "FAILED")  { state.failed++;  setStat(dom.statFailedVal,  state.failed); }
  if (statusUp === "SKIPPED") { state.skipped++; setStat(dom.statSkippedVal, state.skipped); }
});

socket.on("engine_state", ({ running, paused }) => {
  applyEngineState(running, paused);
});

socket.on("complete", ({ csv_filename, txt_filename }) => {
  setProgress(100);
  setNavStatus("Complete ✓", "idle");
  appendLog(`Done! Reports saved: ${csv_filename || "—"}, ${txt_filename || "—"}`, "SUCCESS");
  showToast("✓ Automation complete! Check Reports.", "success", 5000);
  applyEngineState(false, false);
});

// ── Excel upload ──────────────────────────────────────────────────────────────
function setupDropZone(zone, input, onFiles) {
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") input.click(); });
  input.addEventListener("change", () => { if (input.files.length) onFiles(input.files[0]); });

  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault(); zone.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) onFiles(file);
  });
}

async function uploadExcel(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("dedup", dom.dedupCheck.checked ? "true" : "false");

  try {
    const res = await fetch("/api/upload-excel", { method: "POST", body: fd });
    const data = await res.json();

    if (!res.ok) { showToast(`❌ ${data.error}`, "error"); return; }

    state.excelFile = file;
    state.contacts = data.preview || [];

    dom.excelFileName.textContent = data.filename;
    dom.excelFileInfo.classList.remove("hidden");
    dom.excelDropInner.querySelector(".drop-label").textContent = "File loaded ✓";
    dom.excelDropInner.querySelector(".drop-sublabel").textContent = "Click to replace";

    dom.contactCount.classList.remove("hidden");
    dom.contactCountNum.textContent = data.count;
    dom.statTotalVal.textContent = data.count;
    state.total = data.count;

    appendLog(`Loaded ${data.count} contacts from '${data.filename}'`, "SUCCESS");
    showToast(`✓ ${data.count} contacts loaded`, "success");
  } catch (err) {
    showToast("❌ Network error while uploading file.", "error");
    console.error(err);
  }
}

setupDropZone(dom.excelDropZone, dom.excelInput, uploadExcel);

dom.excelReloadBtn.addEventListener("click", async (e) => {
  e.stopPropagation();
  if (!state.excelFile) { showToast("No file loaded yet.", "warning"); return; }
  await uploadExcel(state.excelFile);
});

dom.dedupCheck.addEventListener("change", async () => {
  if (state.excelFile) await uploadExcel(state.excelFile);
});

// ── Attachment upload ─────────────────────────────────────────────────────────
async function uploadAttachment(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);

  try {
    const res = await fetch("/api/upload-attachment", { method: "POST", body: fd });
    const data = await res.json();

    if (!res.ok) { showToast(`❌ ${data.error}`, "error"); return; }

    state.attachFile = file;
    dom.attachFileName.textContent = data.filename;
    dom.attachFileInfo.classList.remove("hidden");
    dom.attachDropInner.querySelector(".drop-label").textContent = "Attached ✓";

    appendLog(`Attachment set: ${data.filename}`, "INFO");
    showToast(`✓ Attachment ready: ${data.filename}`, "success");
  } catch (err) {
    showToast("❌ Attachment upload failed.", "error");
    console.error(err);
  }
}

setupDropZone(dom.attachDropZone, dom.attachInput, uploadAttachment);

dom.attachClearBtn.addEventListener("click", async (e) => {
  e.stopPropagation();
  try {
    await fetch("/api/clear-attachment", { method: "POST" });
    state.attachFile = null;
    dom.attachFileInfo.classList.add("hidden");
    dom.attachDropInner.querySelector(".drop-label").textContent = "Image, video, PDF…";
    appendLog("Attachment cleared.", "INFO");
    showToast("Attachment removed.", "warning");
  } catch (err) {
    showToast("Failed to clear attachment.", "error");
  }
});

// ── Browser select (populate from API) ───────────────────────────────────────
async function loadStatus() {
  try {
    const res  = await fetch("/api/status");
    const data = await res.json();

    // Populate browser dropdown from status
    dom.browserSelect.innerHTML = "";
    (data.supported_browsers || ["Chrome"]).forEach((b) => {
      const opt = document.createElement("option");
      opt.value = b; opt.textContent = b;
      dom.browserSelect.appendChild(opt);
    });

    // Restore running state if server already has an engine
    applyEngineState(data.running, data.paused);

    if (data.contacts_loaded > 0) {
      dom.contactCountNum.textContent = data.contacts_loaded;
      dom.contactCount.classList.remove("hidden");
      dom.statTotalVal.textContent = data.contacts_loaded;
    }
  } catch (err) {
    console.error("Status fetch failed:", err);
  }
}

dom.browserSelect.addEventListener("change", () => { state.browser = dom.browserSelect.value; });

// ── Mode toggle ───────────────────────────────────────────────────────────────
dom.modeKnown.addEventListener("click", () => {
  state.mode = "known";
  dom.modeKnown.classList.add("active");
  dom.modeUnknown.classList.remove("active");
  dom.modeDesc.textContent = "Uses Forward dialog. Best for existing contacts.";
});

dom.modeUnknown.addEventListener("click", () => {
  state.mode = "unknown";
  dom.modeUnknown.classList.add("active");
  dom.modeKnown.classList.remove("active");
  dom.modeDesc.textContent = "Uses New Chat + Paste. Best for brand new numbers.";
});

// ── Automation control ────────────────────────────────────────────────────────
dom.startBtn.addEventListener("click", async () => {
  if (!state.excelFile && dom.contactCountNum.textContent === "0") {
    showToast("Load an Excel file first!", "warning");
    return;
  }

  // Reset UI for new run
  state.sent = 0; state.failed = 0; state.skipped = 0; state.resultRowCount = 0;
  dom.statSentVal.textContent    = "0";
  dom.statFailedVal.textContent  = "0";
  dom.statSkippedVal.textContent = "0";
  dom.resultsBody.innerHTML      = "";
  dom.resultsEmpty.classList.remove("hidden");
  dom.resultsTable.hidden        = true;
  setProgress(0);

  const settings = await fetchSettings();
  const payload = {
    browser: dom.browserSelect.value,
    mode:    state.mode,
    ...settings,
  };

  try {
    const res  = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) { showToast(`❌ ${data.error}`, "error"); return; }
    showToast(`▶ Automation started! Mode: ${data.mode}`, "success");
  } catch (err) {
    showToast("❌ Failed to start automation.", "error");
    console.error(err);
  }
});

dom.pauseBtn.addEventListener("click", async () => {
  const endpoint = state.paused ? "/api/resume" : "/api/pause";
  try {
    const res  = await fetch(endpoint, { method: "POST" });
    const data = await res.json();
    if (!res.ok) showToast(`❌ ${data.error}`, "error");
  } catch (err) {
    showToast("❌ Request failed.", "error");
  }
});

dom.stopBtn.addEventListener("click", async () => {
  if (!confirm("Stop the automation? This cannot be resumed.")) return;
  try {
    const res  = await fetch("/api/stop", { method: "POST" });
    const data = await res.json();
    if (!res.ok) showToast(`❌ ${data.error}`, "error");
    else showToast("■ Stop requested.", "warning");
  } catch (err) {
    showToast("❌ Request failed.", "error");
  }
});

// ── Settings modal ────────────────────────────────────────────────────────────
async function fetchSettings() {
  try {
    const res = await fetch("/api/settings");
    return await res.json();
  } catch { return {}; }
}

const SETTINGS_DEFAULTS = null;  // populated from /api/config — see loadConfig()
let _configDefaults = {};         // cache of latest /api/config response

async function loadConfig() {
  try {
    const res  = await fetch("/api/config");
    const data = await res.json();
    _configDefaults = data;

    // ── Feature flags from config.py ───────────────────────────────────────
    // Attachment section visibility
    const attachSection = document.getElementById("attachSection");
    const attachDivider = attachSection ? attachSection.previousElementSibling : null;
    if (attachSection) {
      if (data.enable_attachments) {
        attachSection.classList.remove("hidden");
        if (attachDivider) attachDivider.classList.remove("hidden");
      } else {
        attachSection.classList.add("hidden");
        if (attachDivider) attachDivider.classList.add("hidden");
      }
    }

    return data;
  } catch (err) {
    console.error("Failed to load config:", err);
    return {};
  }
}

function populateSettingsModal(s) {
  // Use _configDefaults (from /api/config) as fallback values
  const d = _configDefaults;
  dom.s_delay_min.value      = s.delay_min         ?? d.delay_min         ?? 45;
  dom.s_delay_max.value      = s.delay_max         ?? d.delay_max         ?? 95;
  dom.s_warmup_count.value   = s.warmup_count      ?? d.warmup_count      ?? 8;
  dom.s_warmup_min.value     = s.warmup_min        ?? d.warmup_min        ?? 90;
  dom.s_warmup_max.value     = s.warmup_max        ?? d.warmup_max        ?? 180;
  dom.s_occasional_n.value   = s.occasional_n      ?? d.occasional_n      ?? 7;
  dom.s_occasional_min.value = s.occasional_min    ?? d.occasional_min    ?? 180;
  dom.s_occasional_max.value = s.occasional_max    ?? d.occasional_max    ?? 300;
  dom.s_batch_min.value      = s.batch_break_min   ?? d.batch_break_min   ?? 300;
  dom.s_batch_max.value      = s.batch_break_max   ?? d.batch_break_max   ?? 600;
  dom.s_deep_min.value       = s.deep_rest_min     ?? d.deep_rest_min     ?? 1800;
  dom.s_deep_max.value       = s.deep_rest_max     ?? d.deep_rest_max     ?? 5400;
  dom.s_fwd_min.value        = s.forward_batch_min ?? d.forward_batch_min ?? 1;
  dom.s_fwd_max.value        = s.forward_batch_max ?? d.forward_batch_max ?? 5;
  dom.s_retry.value          = s.retry             ?? d.retry             ?? 2;
  dom.s_retry_delay.value    = s.retry_delay       ?? d.retry_delay       ?? 35;
}


function collectSettingsFromModal() {
  return {
    delay_min:         parseFloat(dom.s_delay_min.value),
    delay_max:         parseFloat(dom.s_delay_max.value),
    warmup_count:      parseInt(dom.s_warmup_count.value),
    warmup_min:        parseFloat(dom.s_warmup_min.value),
    warmup_max:        parseFloat(dom.s_warmup_max.value),
    occasional_n:      parseInt(dom.s_occasional_n.value),
    occasional_min:    parseFloat(dom.s_occasional_min.value),
    occasional_max:    parseFloat(dom.s_occasional_max.value),
    batch_break_min:   parseFloat(dom.s_batch_min.value),
    batch_break_max:   parseFloat(dom.s_batch_max.value),
    deep_rest_min:     parseFloat(dom.s_deep_min.value),
    deep_rest_max:     parseFloat(dom.s_deep_max.value),
    forward_batch_min: parseInt(dom.s_fwd_min.value),
    forward_batch_max: parseInt(dom.s_fwd_max.value),
    retry:             parseInt(dom.s_retry.value),
    retry_delay:       parseFloat(dom.s_retry_delay.value),
  };
}

dom.openSettings.addEventListener("click", async () => {
  const s = await fetchSettings();
  state.settingsSnapshot = { ...s };
  populateSettingsModal(s);
  dom.settingsOverlay.classList.remove("hidden");
});

dom.settingsClose.addEventListener("click",  closeSettings);
dom.settingsCancel.addEventListener("click", () => {
  if (state.settingsSnapshot) populateSettingsModal(state.settingsSnapshot);
  closeSettings();
});

function closeSettings() { dom.settingsOverlay.classList.add("hidden"); }

dom.settingsSave.addEventListener("click", async () => {
  const payload = collectSettingsFromModal();

  // Validate
  if (payload.delay_min > payload.delay_max) {
    showToast("Min delay cannot exceed max delay.", "error"); return;
  }

  for (const [k, v] of Object.entries(payload)) {
    if (isNaN(v)) { showToast(`Invalid value for: ${k}`, "error"); return; }
  }

  try {
    const res  = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) { showToast(`❌ ${data.error}`, "error"); return; }
    showToast("✓ Settings saved.", "success");
    closeSettings();
  } catch (err) {
    showToast("❌ Failed to save settings.", "error");
  }
});

dom.settingsReset.addEventListener("click", async () => {
  // Always fetch fresh config defaults (honours any edits to config.py)
  const cfg = await loadConfig();
  const defaults = {
    delay_min:         cfg.delay_min         ?? 45,
    delay_max:         cfg.delay_max         ?? 95,
    warmup_count:      cfg.warmup_count       ?? 8,
    warmup_min:        cfg.warmup_min         ?? 90,
    warmup_max:        cfg.warmup_max         ?? 180,
    occasional_n:      cfg.occasional_n       ?? 7,
    occasional_min:    cfg.occasional_min     ?? 180,
    occasional_max:    cfg.occasional_max     ?? 300,
    batch_break_min:   cfg.batch_break_min    ?? 300,
    batch_break_max:   cfg.batch_break_max    ?? 600,
    deep_rest_min:     cfg.deep_rest_min      ?? 1800,
    deep_rest_max:     cfg.deep_rest_max      ?? 5400,
    forward_batch_min: cfg.forward_batch_min  ?? 1,
    forward_batch_max: cfg.forward_batch_max  ?? 5,
    retry:             cfg.retry              ?? 2,
    retry_delay:       cfg.retry_delay        ?? 35,
  };
  populateSettingsModal(defaults);
  showToast("Defaults restored from config.py — click Save to apply.", "warning");
});

// Close modal on overlay click
dom.settingsOverlay.addEventListener("click", (e) => {
  if (e.target === dom.settingsOverlay) {
    if (state.settingsSnapshot) populateSettingsModal(state.settingsSnapshot);
    closeSettings();
  }
});

// ── Reports modal ─────────────────────────────────────────────────────────────
dom.reportsBtn.addEventListener("click", openReports);
dom.reportsClose.addEventListener("click", () => dom.reportsOverlay.classList.add("hidden"));
dom.reportsOverlay.addEventListener("click", (e) => {
  if (e.target === dom.reportsOverlay) dom.reportsOverlay.classList.add("hidden");
});

async function openReports() {
  dom.reportsOverlay.classList.remove("hidden");
  dom.reportsList.innerHTML = "";
  dom.reportsEmpty.classList.add("hidden");

  try {
    const res   = await fetch("/api/reports");
    const files = await res.json();

    if (!files.length) {
      dom.reportsEmpty.classList.remove("hidden");
      return;
    }

    files.forEach((f) => {
      const ext = f.name.split(".").pop().toLowerCase();
      const size = f.size < 1024 ? `${f.size} B` : `${(f.size / 1024).toFixed(1)} KB`;
      const item = document.createElement("div");
      item.className = "report-item";
      item.innerHTML = `
        <div class="report-type ${ext}">${ext.toUpperCase()}</div>
        <div class="report-info">
          <div class="report-name">${escapeHtml(f.name)}</div>
          <div class="report-meta">${f.modified} &nbsp;·&nbsp; ${size}</div>
        </div>
        <a class="btn-download" href="/api/reports/${encodeURIComponent(f.name)}" download="${escapeHtml(f.name)}">
          ↓ Download
        </a>`;
      dom.reportsList.appendChild(item);
    });
  } catch (err) {
    dom.reportsEmpty.classList.remove("hidden");
    console.error("Failed to load reports:", err);
  }
}

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeSettings();
    dom.reportsOverlay.classList.add("hidden");
  }
});

// ── QR Code Overlay (Render / remote browser) ─────────────────────────────────
const qrDom = {
  overlay:    $("qrOverlay"),
  screenshot: $("qrScreenshot"),
  loading:    $("qrLoading"),
  statusText: $("qrStatusText"),
  refreshBtn: $("qrRefreshBtn"),
};

let _qrPollTimer = null;
let _qrVisible = false;

function showQrOverlay() {
  if (_qrVisible) return;
  _qrVisible = true;
  qrDom.overlay.classList.remove("hidden");
  qrDom.loading.classList.remove("hidden");
  qrDom.screenshot.src = "";
  qrDom.statusText.textContent = "Waiting for QR scan…";
  refreshQrScreenshot();
  _qrPollTimer = setInterval(refreshQrScreenshot, 2500);
}

function hideQrOverlay() {
  if (!_qrVisible) return;
  _qrVisible = false;
  clearInterval(_qrPollTimer);
  qrDom.overlay.classList.add("hidden");
}

async function refreshQrScreenshot() {
  try {
    const res  = await fetch("/api/screenshot");
    const data = await res.json();
    if (data.image) {
      qrDom.screenshot.src = data.image;
      qrDom.loading.classList.add("hidden");
    }
  } catch {
    // Network hiccup — keep showing the last screenshot
  }
}

// SocketIO event: server signals QR waiting state
socket.on("qr_waiting", ({ waiting }) => {
  if (waiting) {
    showQrOverlay();
    appendLog("📱 Scan the QR code shown in the QR overlay panel.", "WARNING");
  } else {
    hideQrOverlay();
    qrDom.statusText.textContent = "✓ Logged in!";
  }
});

qrDom.refreshBtn.addEventListener("click", () => {
  qrDom.loading.classList.remove("hidden");
  refreshQrScreenshot();
});

// Close QR overlay on background click
qrDom.overlay.addEventListener("click", (e) => {
  if (e.target === qrDom.overlay) hideQrOverlay();
});

// ── Init ──────────────────────────────────────────────────────────────────────
(async function init() {
  // Load config.py values first (controls feature flags + Reset Defaults)
  await loadConfig();
  // Then load runtime status (browsers, running state)
  await loadStatus();
  appendLog("WhatsApp RPA Web UI ready. Load your Excel file to begin.", "INFO");
})();

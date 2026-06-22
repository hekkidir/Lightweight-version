/**
 * app.js — state, interaction model, persistence, bootstrap.
 *
 * Focus model — two coexisting layers:
 *   - category chip  -> focusCategory (the active GROUP; single-select quick pick)
 *   - clicking a row -> pins Set (spotlight on the map; does NOT collapse the category)
 * Two resolvers feed the frames:
 *   - groupFocus()     = category | pins | all  -> Aday Hisseler, sidebar ✓
 *   - spotlightFocus() = pins | category | all   -> RRG map + Stocks table
 *                        (pins drill in: the map highlights only the pinned dots)
 * The Active Filters bar shows every active filter as a removable chip.
 */

const state = {
  stocks: [], sectors: [], rotation: { current: [], tails: [] }, status: {}, robots: { robots: [] },
  pins: new Set(),        // spotlighted sectors (coexist with a category)
  focusCategory: "",      // the active group (category quick-pick)
  sectorSearch: "",       // sidebar find-in-list (not cross-frame)
  stages: new Set(),
  search: "",             // stock search
  ranges: {
    mcap: { min: "", max: "" },
    rsi:  { min: "", max: "" },
    atr:  { min: "", max: "" },
    ext:  { min: "", max: "" },
    rvol: { min: "", max: "" },
    perf: { field: "weekly", min: "", max: "" },
  },
};

const LS_KEY = "screener.filters";
const RNG_LABEL  = { mcap: "MCap", rsi: "RSI", atr: "ATR%", ext: "Ext", rvol: "RVOL" };
const PERF_LABEL = { change_pct: "Day%", weekly: "Week%", monthly: "Month%", ytd: "YTD%" };

// The active GROUP: category sectors, else pins, else null (all). Drives the
// Aday Hisseler list and the sidebar selected/✓ marks.
function groupFocus() {
  if (state.focusCategory) return categorySet(state.rotation, state.focusCategory);
  if (state.pins.size) return new Set(state.pins);
  return null;
}

// Spotlight scope: pins drill in (the RRG highlights only the pinned dots and the
// Stocks table narrows to them); with no pins, fall back to the category group;
// with neither, all sectors.
function spotlightFocus() {
  if (state.pins.size) return new Set(state.pins);
  if (state.focusCategory) return categorySet(state.rotation, state.focusCategory);
  return null;
}

function saveFilters() {
  localStorage.setItem(LS_KEY, JSON.stringify({
    pins: [...state.pins], focusCategory: state.focusCategory,
    sectorSearch: state.sectorSearch, stages: [...state.stages],
    search: state.search, ranges: state.ranges,
  }));
}

function loadFilters() {
  try {
    const f = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    if (Array.isArray(f.pins)) state.pins = new Set(f.pins);
    else if (Array.isArray(f.focus)) state.pins = new Set(f.focus);   // migrate old key
    if (typeof f.focusCategory === "string") state.focusCategory = f.focusCategory;
    if (typeof f.sectorSearch === "string") state.sectorSearch = f.sectorSearch;
    if (Array.isArray(f.stages)) state.stages = new Set(f.stages);
    if (typeof f.search === "string") state.search = f.search;
    if (f.ranges && typeof f.ranges === "object") {
      for (const k of Object.keys(state.ranges)) {
        if (f.ranges[k]) Object.assign(state.ranges[k], f.ranges[k]);
      }
    }
  } catch { /* ignore corrupt storage */ }
}


// ── Top bar ─────────────────────────────────────────────────────────────────

function renderTopBar(status, stocks) {
  const dateEl = document.getElementById("topbar-date");
  const ts = status.metrics;
  if (ts) {
    const d = new Date(ts);
    dateEl.textContent = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
    const ageDays = (Date.now() - d.getTime()) / 86400000;
    if (ageDays > 5) dateEl.style.color = "var(--neg)";
    else if (ageDays > 2) dateEl.style.color = "#f59e0b";
  }
  const total = stocks.length;
  const up = stocks.filter(s => ["2A", "2B", "2C"].includes(s.Stage)).length;
  const dn = stocks.filter(s => ["4A", "4B", "4C"].includes(s.Stage)).length;
  document.getElementById("topbar-counts").textContent =
    `${total} stocks | ${up} advancing | ${dn} declining`;
}


// ── Active Filters bar ────────────────────────────────────────────────────────

function rangeText(r) {
  if (r.min !== "" && r.max !== "") return `${r.min}–${r.max}`;
  if (r.min !== "") return `≥ ${r.min}`;
  return `≤ ${r.max}`;
}

function clearRangeInputs(k) {
  document.querySelectorAll(`#stock-filters input[data-rng='${k}']`).forEach(i => { i.value = ""; });
}

function chip(label, onRemove) {
  const c = h("span", "af-chip");
  c.appendChild(h("span", "af-chip-label", label));
  const x = h("button", "af-chip-x", "×");
  x.addEventListener("click", e => { e.stopPropagation(); onRemove(); });
  c.appendChild(x);
  return c;
}

function renderActiveFilters() {
  const el = document.getElementById("active-filters");
  el.innerHTML = "";
  const chips = [];

  if (state.focusCategory) {
    chips.push(chip(catLabel(state.focusCategory),
      () => { selectCategory(state.focusCategory); }));   // toggling off also clears pins
  }
  [...state.pins].forEach(s => chips.push(chip("📌 " + s,
    () => { state.pins.delete(s); saveFilters(); renderAll(); })));

  if (state.stages.size) {
    chips.push(chip(`Stage: ${[...state.stages].join(", ")}`,
      () => { state.stages.clear(); saveFilters(); renderAll(); }));
  }

  for (const [k, r] of Object.entries(state.ranges)) {
    if (r.min === "" && r.max === "") continue;
    const name = k === "perf" ? PERF_LABEL[r.field] : RNG_LABEL[k];
    chips.push(chip(`${name} ${rangeText(r)}`,
      () => { r.min = ""; r.max = ""; clearRangeInputs(k); saveFilters(); renderAll(); }));
  }

  if (state.search) {
    chips.push(chip(`🔍 ${state.search}`, () => {
      state.search = ""; document.getElementById("stock-search").value = "";
      saveFilters(); renderAll();
    }));
  }

  if (!chips.length) { el.style.display = "none"; return; }
  el.style.display = "flex";
  el.appendChild(h("span", "af-label", "Filtreler:"));
  chips.forEach(c => el.appendChild(c));
  const clear = h("button", "af-clear", "Tümünü Temizle");
  clear.addEventListener("click", resetFilters);
  el.appendChild(clear);
}


// ── Render orchestrator ───────────────────────────────────────────────────────

function renderAll() {
  const group = groupFocus();
  renderTopBar(state.status, state.stocks);
  renderActiveFilters();
  renderCatChips("sector-cats", state.focusCategory, selectCategory);
  renderSectorList(state.sectors, state.rotation, state.pins, state.focusCategory, state.sectorSearch, togglePin);
  renderRRG(state.rotation, spotlightFocus(), state.pins);
  syncRRGModal(state.rotation, state.sectors, spotlightFocus(), state.pins);
  renderCandidates(state.stocks, state.rotation, group, togglePin);
  renderStageChips(state.stages, toggleStage);
  window._rerenderTable();
}

window._rerenderTable = () => renderStockTable(
  state.stocks, spotlightFocus(), state.stages, state.search, state.ranges);

// Switch between the dashboard (Panel) and the Robots view.
function showView(view) {
  const robots = view === "robots";
  document.getElementById("layout").style.display = robots ? "none" : "flex";
  document.getElementById("robots-view").style.display = robots ? "block" : "none";
  document.getElementById("view-panel").classList.toggle("active", !robots);
  document.getElementById("view-robots").classList.toggle("active", robots);
  if (robots) renderRobotsView(state.robots, state.stocks);
}

// Lighter refresh after a stock-only filter change (no RRG/sidebar redraw).
function refreshStockFilters() {
  renderActiveFilters();
  renderStageChips(state.stages, toggleStage);
  window._rerenderTable();
}


// ── Interaction ───────────────────────────────────────────────────────────────

function selectCategory(cat) {
  state.focusCategory = state.focusCategory === cat ? "" : cat;
  state.pins.clear();           // a new (or cleared) group starts with no pins
  saveFilters();
  renderAll();
}

// Pin/unpin a single sector. Does NOT touch the active category (the group
// stays put; the pin is a spotlight on the map + a drill-down for the table).
function togglePin(sector) {
  if (state.pins.has(sector)) state.pins.delete(sector);
  else state.pins.add(sector);
  saveFilters();
  renderAll();
}

// Pin every sector currently listed in the sidebar (active category + search).
function pinAllVisible() {
  visibleSectors(state.sectors, state.rotation, state.focusCategory, state.sectorSearch)
    .forEach(s => state.pins.add(s.Sector));
  saveFilters();
  renderAll();
}

function clearPins() {
  if (!state.pins.size) return;
  state.pins.clear();
  saveFilters();
  renderAll();
}

// Replace the pin set wholesale (used by the modal quadrant legend).
function setPins(sectors) {
  state.pins = new Set(sectors);
  saveFilters();
  renderAll();
}

function toggleStage(st) {
  if (state.stages.has(st)) state.stages.delete(st);
  else state.stages.add(st);
  saveFilters();
  refreshStockFilters();
}

function resetFilters() {
  state.pins.clear();
  state.focusCategory = "";
  state.sectorSearch = "";
  state.stages.clear();
  state.search = "";
  for (const k of Object.keys(state.ranges)) { state.ranges[k].min = ""; state.ranges[k].max = ""; }
  state.ranges.perf.field = "weekly";
  document.getElementById("sector-search").value = "";
  document.getElementById("stock-search").value = "";
  document.getElementById("perf-field").value = "weekly";
  document.querySelectorAll("#stock-filters input[data-rng]").forEach(i => { i.value = ""; });
  saveFilters();
  renderAll();
}


// ── Event wiring ────────────────────────────────────────────────────────────

function wireEvents() {
  document.getElementById("sector-search").addEventListener("input", e => {
    state.sectorSearch = e.target.value.trim(); saveFilters();
    renderSectorList(state.sectors, state.rotation, state.pins,
                     state.focusCategory, state.sectorSearch, togglePin);
  });
  document.getElementById("pin-all").addEventListener("click", pinAllVisible);
  document.getElementById("clear-pins").addEventListener("click", clearPins);
  document.getElementById("stock-search").addEventListener("input", e => {
    state.search = e.target.value.trim(); saveFilters(); refreshStockFilters();
  });

  document.getElementById("filters-toggle").addEventListener("click", () => {
    document.getElementById("stock-filters").classList.toggle("open");
  });
  document.getElementById("csv-export").addEventListener("click", () =>
    exportStocksCSV(state.stocks, spotlightFocus(), state.stages, state.search, state.ranges));

  document.querySelectorAll("#stock-filters input[data-rng]").forEach(inp => {
    inp.addEventListener("input", () => {
      state.ranges[inp.dataset.rng][inp.dataset.b] = inp.value;
      saveFilters(); refreshStockFilters();
    });
  });
  document.getElementById("perf-field").addEventListener("change", e => {
    state.ranges.perf.field = e.target.value; saveFilters(); refreshStockFilters();
  });

  document.getElementById("view-panel").addEventListener("click", () => showView("panel"));
  document.getElementById("view-robots").addEventListener("click", () => showView("robots"));

  document.getElementById("rrg-fullscreen-btn").addEventListener("click",
    () => openRRGModal(state.rotation, state.sectors, spotlightFocus(), state.pins));
  document.getElementById("rrg-modal-close").addEventListener("click", closeRRGModal);
  document.getElementById("stock-modal-close").addEventListener("click", closeStockModal);
  document.getElementById("stock-modal").addEventListener("click",
    e => { if (e.target.id === "stock-modal") closeStockModal(); });   // backdrop
  document.getElementById("robot-modal-close").addEventListener("click", closeRobotModal);
  document.getElementById("robot-modal").addEventListener("click",
    e => { if (e.target.id === "robot-modal") closeRobotModal(); });   // backdrop
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { closeRRGModal(); closeStockModal(); closeRobotModal(); }
  });

  window.addEventListener("resize",
    () => renderRRG(state.rotation, spotlightFocus(), state.pins));
}


// ── Bootstrap ─────────────────────────────────────────────────────────────────

async function init() {
  try {
    const data = await loadAll();
    state.stocks = data.stocks;
    state.sectors = data.sectors;
    state.rotation = data.rotation;
    state.status = data.status;
    state.robots = data.robots || { robots: [] };

    loadFilters();
    document.getElementById("sector-search").value = state.sectorSearch;
    document.getElementById("stock-search").value = state.search;
    document.getElementById("perf-field").value = state.ranges.perf.field;
    document.querySelectorAll("#stock-filters input[data-rng]").forEach(inp => {
      inp.value = state.ranges[inp.dataset.rng][inp.dataset.b] || "";
    });

    wireEvents();
    renderAll();
  } catch (err) {
    document.body.innerHTML = `
      <div style="padding:40px;color:#ef4444;font-family:monospace">
        <h2>Failed to load data</h2>
        <pre>${err.message}</pre>
        <p>Run the pipeline: <code>python run.py pipeline</code> and serve: <code>python run.py serve</code></p>
      </div>`;
  }
}

document.addEventListener("DOMContentLoaded", init);

/**
 * table.js — E frame: the stocks table + its filters + CSV export.
 *
 * Filters: selected sectors (Set), multi-select stages (Set), ticker/sector
 * search, and TradingView-style min/max ranges (MCap, RSI, ATR%, Ext, RVOL,
 * Performance). filterStocks() is shared by the table render and CSV export.
 */

const STAGE_LIST = ["2C", "2B", "2A", "1B", "Chop", "1A", "3A", "3B", "4A", "4B", "4C", "New"];
const STAGE_ORDER = STAGE_LIST;

let _sortCol = "Stage", _sortAsc = true;

function _inRange(val, min, max, scale = 1) {
  if (min !== "" && min != null) { if (val == null || val < +min * scale) return false; }
  if (max !== "" && max != null) { if (val == null || val > +max * scale) return false; }
  return true;
}

function passRanges(s, r) {
  return _inRange(s.Market_Cap, r.mcap.min, r.mcap.max, 1e9)
      && _inRange(s.rsi,       r.rsi.min,  r.rsi.max)
      && _inRange(s.atr_pct,   r.atr.min,  r.atr.max)
      && _inRange(s.ext,       r.ext.min,  r.ext.max)
      && _inRange(s.rvol_avg,  r.rvol.min, r.rvol.max)
      && _inRange(s[r.perf.field], r.perf.min, r.perf.max);
}

function filterStocks(stocks, active, stages, search, ranges) {
  let rows = stocks;
  if (active) rows = rows.filter(s => active.has(s.Sector));
  if (stages.size) rows = rows.filter(s => stages.has(s.Stage));
  if (search) {
    const q = search.toLowerCase();
    rows = rows.filter(s => (s.Ticker || "").toLowerCase().includes(q)
                         || (s.Sector || "").toLowerCase().includes(q));
  }
  return rows.filter(s => passRanges(s, ranges));
}

function renderStageChips(stages, onToggle) {
  const el = document.getElementById("stage-chips");
  el.innerHTML = "";
  STAGE_LIST.forEach(st => {
    const b = h("button", "stage-chip" + (stages.has(st) ? " active" : ""), st);
    b.addEventListener("click", () => onToggle(st));
    el.appendChild(b);
  });
}

function renderStockTable(stocks, active, stages, search, ranges) {
  let rows = filterStocks(stocks, active, stages, search, ranges);

  rows = [...rows].sort((a, b) => {
    let av = a[_sortCol], bv = b[_sortCol];
    if (_sortCol === "Stage") { av = STAGE_ORDER.indexOf(av); bv = STAGE_ORDER.indexOf(bv); }
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return _sortAsc ? cmp : -cmp;
  });

  document.getElementById("stock-count").textContent = `${rows.length}`;

  const tbody = document.getElementById("stock-tbody");
  tbody.innerHTML = "";
  rows.forEach(s => {
    const tr = document.createElement("tr");
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => openStockModal(s.Ticker, s));
    const vc = s.Vol_Confirmed ? "vc" : "";
    tr.innerHTML = `
      <td><strong>${escHTML(s.Ticker || "")}</strong></td>
      <td class="cell-sector" title="${escAttr(s.Sector || "")}">${escHTML((s.Sector || "").split(" - ")[0])}</td>
      <td><span class="stage-badge ${stageCls(s.Stage)}">${escHTML(s.Stage || "")}</span></td>
      <td>${fmt(s.Close)}</td>
      <td class="${s.change_pct >= 0 ? "pos" : "neg"}">${fmtPct(s.change_pct)}</td>
      <td class="${s.weekly >= 0 ? "pos" : "neg"}">${fmtPct(s.weekly)}</td>
      <td class="${s.monthly >= 0 ? "pos" : "neg"}">${fmtPct(s.monthly)}</td>
      <td class="${s.ytd >= 0 ? "pos" : "neg"}">${fmtPct(s.ytd)}</td>
      <td>${fmt(s.rsi, 1)}</td>
      <td>${fmt(s.rvol_avg)}</td>
      <td>${fmt(s.ext)}</td>
      <td>${fmt(s.atr_pct)}</td>
      <td class="${vc}">${s.Vol_Confirmed ? "Y" : ""}</td>
    `;
    tbody.appendChild(tr);
  });

  if (!document.getElementById("stock-table").dataset.sorted) {
    document.getElementById("stock-table").dataset.sorted = "1";
    document.querySelectorAll("#stock-table thead th[data-col]").forEach(th => {
      th.style.cursor = "pointer";
      th.addEventListener("click", () => {
        if (_sortCol === th.dataset.col) _sortAsc = !_sortAsc;
        else { _sortCol = th.dataset.col; _sortAsc = true; }
        window._rerenderTable && window._rerenderTable();
      });
    });
  }
}

function exportStocksCSV(stocks, active, stages, search, ranges) {
  const rows = filterStocks(stocks, active, stages, search, ranges);
  const cols = ["Ticker", "Sector", "Stage", "Close", "change_pct", "weekly",
                "monthly", "ytd", "rsi", "rvol_avg", "ext", "atr_pct",
                "Market_Cap", "Vol_Confirmed"];
  const esc = v => {
    const t = v == null ? "" : String(v);
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const csv = [cols.join(",")]
    .concat(rows.map(s => cols.map(c => esc(s[c])).join(",")))
    .join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = "stocks.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

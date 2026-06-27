/**
 * robots.js — Robots view: one card per robot (strategy), each showing its
 * current holdings + next candidates. Strategy data comes from /api/robots
 * (data/robots.json); every ticker is joined to live /api/stocks so each row
 * also shows the current sector + stage. Ticker click -> stock modal;
 * "pin holdings" pushes a robot's holdings onto the RRG as pins.
 */

const STAT_LABELS = {
  return_pct: "Getiri", cagr: "CAGR", max_dd: "MaxDD",
  win_rate: "Kazanç%", sharpe: "Sharpe",
};

function _drawSparkline(canvas, values) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height, pad = 2;
  ctx.clearRect(0, 0, W, H);
  if (!values || values.length < 2) return;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || 1;
  const x = i => pad + (i / (values.length - 1)) * (W - 2 * pad);
  const y = v => H - pad - ((v - lo) / span) * (H - 2 * pad);
  ctx.beginPath();
  ctx.strokeStyle = values[values.length - 1] >= values[0] ? "#10b981" : "#ef4444";
  ctx.lineWidth = 1.5;
  values.forEach((v, i) => i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v)));
  ctx.stroke();
}

function _statChips(stats) {
  if (!stats) return "";
  return Object.entries(STAT_LABELS)
    .filter(([k]) => stats[k] != null)
    .map(([k, label]) => {
      const v = stats[k];
      const isPct = k !== "sharpe";
      const cls = (k === "return_pct" || k === "cagr") ? (v >= 0 ? "pos" : "neg")
                : k === "max_dd" ? "neg" : "";
      const txt = isPct ? fmtPct(v) : fmt(v);
      return `<span class="rb-stat"><span class="rb-stat-l">${label}</span><span class="rb-stat-v ${cls}">${txt}</span></span>`;
    }).join("");
}

function _liveCells(t, byTicker) {
  const live = byTicker[t];
  const sector = live ? escHTML((live.Sector || "").split(" - ")[0]) : "—";
  const stage = live
    ? `<span class="stage-badge ${stageCls(live.Stage)}">${escHTML(live.Stage || "")}</span>`
    : '<span class="muted">—</span>';
  return { sector, stage };
}

function _holdingsTable(holdings, byTicker) {
  if (!holdings || !holdings.length)
    return '<div class="rb-empty-sm">Pozisyon yok — nakitte.</div>';
  const rows = holdings.map(hd => {
    const { sector, stage } = _liveCells(hd.ticker, byTicker);
    return `<tr data-ticker="${escAttr(hd.ticker)}">
      <td class="rb-tkr">${escHTML(hd.ticker)}</td>
      <td class="rb-sec">${sector}</td>
      <td>${stage}</td>
      <td>${hd.entry_date ? escHTML(hd.entry_date) : "—"}</td>
      <td class="${hd.return_pct >= 0 ? "pos" : "neg"}">${hd.return_pct != null ? fmtPct(hd.return_pct) : "—"}</td>
      <td>${hd.weight != null ? (hd.weight * 100).toFixed(0) + "%" : "—"}</td>
    </tr>`;
  }).join("");
  return `<table class="rb-table">
    <thead><tr><th>Hisse</th><th>Sektör</th><th>Stage</th><th>Giriş</th><th>Getiri</th><th>Ağ.</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function _candidatesTable(cands, byTicker) {
  if (!cands || !cands.length)
    return '<div class="rb-empty-sm">Aday yok.</div>';
  const rows = cands.map(c => {
    const { sector, stage } = _liveCells(c.ticker, byTicker);
    return `<tr data-ticker="${escAttr(c.ticker)}">
      <td class="rb-tkr">${escHTML(c.ticker)}</td>
      <td class="rb-sec">${sector}</td>
      <td>${stage}</td>
      <td>${c.score != null ? fmt(c.score) : "—"}</td>
      <td class="rb-why" title="${escAttr(c.reason || "")}">${escHTML(c.reason || "")}</td>
    </tr>`;
  }).join("");
  // Capped to ~5 rows; the rest scroll within the panel (header stays pinned).
  return `<div class="rb-scroll"><table class="rb-table">
    <thead><tr><th>Hisse</th><th>Sektör</th><th>Stage</th><th>Skor</th><th>Neden</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

function _robotCard(r, byTicker) {
  const nH = (r.holdings || []).length, nC = (r.candidates || []).length;
  return `<div class="rb-card">
    <div class="rb-card-head">
      <div class="rb-name" data-robot="${escAttr(r.key)}" title="Detay">${escHTML(r.name || r.key)} <span class="rb-detay">▸</span></div>
      <div class="rb-stats">${_statChips(r.stats)}</div>
      ${r.equity ? `<canvas class="rb-eq" id="rb-eq-${escAttr(r.key)}" width="120" height="30"></canvas>` : ""}
      <button class="rb-pin" data-pin-robot="${escAttr(r.key)}" ${(nH + nC) ? "" : "disabled"}>📌 Sektörleri sabitle</button>
    </div>
    <div class="rb-cols">
      <div class="rb-col">
        <div class="rb-col-h">Tutuyor <span class="rb-n">${nH}</span></div>
        ${_holdingsTable(r.holdings, byTicker)}
      </div>
      <div class="rb-col">
        <div class="rb-col-h rb-col-h-cand">Sıradaki Adaylar <span class="rb-n">${nC}</span></div>
        ${_candidatesTable(r.candidates, byTicker)}
      </div>
    </div>
  </div>`;
}

function renderRobotsView(robotsData, stocks) {
  const el = document.getElementById("robots-view");
  const robots = (robotsData && robotsData.robots) || [];
  if (!robots.length) {
    el.innerHTML = '<div class="rb-empty">Robot verisi yok. Backtest dışa aktarımını çalıştırın (data/robots.json).</div>';
    return;
  }
  const byTicker = {};
  (stocks || []).forEach(s => { byTicker[s.Ticker] = s; });

  const gen = robotsData.generated_at
    ? `<div class="rb-gen">Üretim: ${escHTML(String(robotsData.generated_at).replace("T", " ").slice(0, 16))}</div>` : "";
  el.innerHTML = gen + robots.map(r => _robotCard(r, byTicker)).join("");

  robots.forEach(r => {
    const c = document.getElementById(`rb-eq-${r.key}`);
    if (c && r.equity) _drawSparkline(c, r.equity);
  });
  el.querySelectorAll("tr[data-ticker]").forEach(row =>
    row.addEventListener("click", () => {
      const t = row.dataset.ticker;
      openStockModal(t, byTicker[t] || { Ticker: t });
    }));
  el.querySelectorAll(".rb-name[data-robot]").forEach(n =>
    n.addEventListener("click", () =>
      openRobotModal(robots.find(x => String(x.key) === n.dataset.robot), byTicker)));
  el.querySelectorAll("[data-pin-robot]").forEach(btn =>
    btn.addEventListener("click", () => {
      const r = robots.find(x => String(x.key) === btn.dataset.pinRobot);
      if (!r) return;
      // Pin the SECTORS of this robot's holdings + candidates (the RRG is sector-based).
      const secs = new Set();
      [...(r.holdings || []), ...(r.candidates || [])].forEach(x => {
        const live = byTicker[x.ticker];
        if (live && live.Sector) secs.add(live.Sector);
      });
      if (secs.size) { setPins([...secs]); showView("panel"); }
    }));
}

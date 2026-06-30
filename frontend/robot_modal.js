/**
 * robot_modal.js — per-robot tearsheet modal (opened from a robot card header).
 *
 * Panels: performance chart (robot vs S&P 500 vs Nasdaq 100, rebased to 100) +
 * drawdown, stats, monthly-returns heatmap, holdings sector allocation, current
 * holdings + candidates, closed-trade log, last-rebalance activity.
 * Series come from /api/robots; tickers are live-joined via byTicker.
 * Reuses _liveCells / _holdingsTable / _candidatesTable from robots.js.
 * Public API: openRobotModal(robot, byTicker) / closeRobotModal().
 */

let _rmOpen = false, _rmRobot = null, _rmBy = null;
const MON_TR = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];

// ── Charts ────────────────────────────────────────────────────────────────────

function _drawPerf(canvas, robot) {
  const ctx = canvas.getContext("2d"), W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  const padL = 8, padR = 44, padT = 8, padB = 16, pw = W - padL - padR, ph = H - padT - padB;
  const bm = robot.benchmarks || {};
  const lines = [{ vals: robot.equity, color: "#3b82f6", w: 1.9 }];
  if (bm.sp500) lines.push({ vals: bm.sp500, color: "#94a3b8", w: 1.2 });
  if (bm.ndx)   lines.push({ vals: bm.ndx,   color: "#a855f7", w: 1.2 });
  const all = [];
  lines.forEach(l => (l.vals || []).forEach(p => all.push(p.value)));
  if (!all.length) return;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (lo === hi) { lo -= 1; hi += 1; }
  const m = (hi - lo) * 0.08; lo -= m; hi += m;
  const n = Math.max(...lines.map(l => (l.vals || []).length));
  const x = i => padL + (n < 2 ? pw / 2 : (i / (n - 1)) * pw);
  const y = v => padT + ph - ((v - lo) / (hi - lo)) * ph;

  ctx.strokeStyle = "rgba(255,255,255,0.10)"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(padL, y(100)); ctx.lineTo(padL + pw, y(100)); ctx.stroke();
  lines.forEach(l => {
    ctx.beginPath(); ctx.strokeStyle = l.color; ctx.lineWidth = l.w;
    (l.vals || []).forEach((p, i) => i ? ctx.lineTo(x(i), y(p.value)) : ctx.moveTo(x(i), y(p.value)));
    ctx.stroke();
  });
  ctx.fillStyle = "rgba(255,255,255,0.4)"; ctx.font = "9px system-ui"; ctx.textAlign = "left";
  ctx.fillText(hi.toFixed(0), W - padR + 4, padT + 8);
  ctx.fillText(lo.toFixed(0), W - padR + 4, padT + ph);
  const eq = robot.equity || [];
  if (eq.length) {
    ctx.fillText(eq[0].date, padL, H - 4);
    ctx.textAlign = "right"; ctx.fillText(eq[eq.length - 1].date, W - padR, H - 4);
  }
}

function _drawDD(canvas, equity) {
  const ctx = canvas.getContext("2d"), W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  if (!equity || equity.length < 2) return;
  const padL = 8, padR = 44, padT = 4, pw = W - padL - padR, ph = H - padT - 4;
  let peak = -Infinity;
  const dd = equity.map(p => { peak = Math.max(peak, p.value); return (p.value / peak - 1) * 100; });
  const lo = Math.min(...dd, -0.01), n = dd.length;
  const x = i => padL + (i / (n - 1)) * pw, y = v => padT + (-v / -lo) * ph;
  ctx.beginPath(); ctx.moveTo(padL, padT);
  dd.forEach((v, i) => ctx.lineTo(x(i), y(v)));
  ctx.lineTo(padL + pw, padT); ctx.closePath();
  ctx.fillStyle = "rgba(239,68,68,0.25)"; ctx.fill();
  ctx.beginPath(); ctx.strokeStyle = "#ef4444"; ctx.lineWidth = 1;
  dd.forEach((v, i) => i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))); ctx.stroke();
  ctx.fillStyle = "rgba(255,255,255,0.4)"; ctx.font = "9px system-ui"; ctx.textAlign = "left";
  ctx.fillText(lo.toFixed(0) + "%", W - padR + 4, padT + ph);
}

// ── Derived panels ────────────────────────────────────────────────────────────

function _monthly(equity) {
  if (!equity || !equity.length) return [];
  const last = {};
  equity.forEach(p => { last[p.date.slice(0, 7)] = p.value; });
  const keys = Object.keys(last).sort();
  const out = []; let prev = equity[0].value;
  keys.forEach(k => { const v = last[k]; out.push({ ym: k, ret: (v / prev - 1) * 100 }); prev = v; });
  return out;
}

function _heatColor(r) {
  const a = Math.min(0.85, Math.abs(r) / 8 * 0.85 + 0.12);
  return r >= 0 ? `rgba(16,185,129,${a})` : `rgba(239,68,68,${a})`;
}

function _heatmap(equity) {
  const m = _monthly(equity);
  if (!m.length) return '<div class="rm-empty-sm">Veri yok.</div>';
  const byYear = {};
  m.forEach(x => { const [y, mo] = x.ym.split("-"); (byYear[y] ||= {})[+mo] = x.ret; });
  const head = '<div class="rm-hm-row rm-hm-head"><span></span>' + MON_TR.map(mn => `<span>${mn}</span>`).join("") + "</div>";
  const rows = Object.keys(byYear).sort().map(y => {
    let cells = "";
    for (let mo = 1; mo <= 12; mo++) {
      const r = byYear[y][mo];
      cells += (r == null)
        ? '<span class="rm-hm-cell rm-hm-empty"></span>'
        : `<span class="rm-hm-cell" style="background:${_heatColor(r)}" title="${y}-${String(mo).padStart(2, "0")}: ${fmtPct(r)}">${r.toFixed(0)}</span>`;
    }
    return `<div class="rm-hm-row"><span class="rm-hm-y">${y}</span>${cells}</div>`;
  }).join("");
  return `<div class="rm-hm">${head}${rows}</div>`;
}

function _alloc(holdings, byTicker) {
  if (!holdings || !holdings.length) return '<div class="rm-empty-sm">Pozisyon yok — nakitte.</div>';
  const a = {};
  holdings.forEach(hd => {
    const s = ((byTicker[hd.ticker] || {}).Sector || "?").split(" - ")[0];
    a[s] = (a[s] || 0) + (hd.weight || 0);
  });
  const items = Object.entries(a).sort((x, y) => y[1] - x[1]);
  const max = Math.max(...items.map(i => i[1]), 0.0001);
  return items.map(([s, w]) => `<div class="rm-alloc-row">
    <span class="rm-alloc-l" title="${escAttr(s)}">${escHTML(s)}</span>
    <span class="rm-alloc-bar"><span class="rm-alloc-fill" style="width:${(w / max * 100).toFixed(0)}%"></span></span>
    <span class="rm-alloc-v">${(w * 100).toFixed(0)}%</span></div>`).join("");
}

function _rmStats(s) {
  if (!s) return "";
  const t = (l, v, cls = "") => `<div class="rm-tile"><span class="rm-tile-l">${l}</span><span class="rm-tile-v ${cls}">${v}</span></div>`;
  return `<div class="rm-stats">
    ${t("Getiri", fmtPct(s.return_pct), s.return_pct >= 0 ? "pos" : "neg")}
    ${t("CAGR", fmtPct(s.cagr), s.cagr >= 0 ? "pos" : "neg")}
    ${t("Sharpe", fmt(s.sharpe))}
    ${t("MaxDD", fmtPct(s.max_dd), "neg")}
    ${t("Kazanç%", s.win_rate != null ? s.win_rate + "%" : "—")}
    ${t("İşlem", s.n_trades != null ? s.n_trades : "—")}
    ${t("Poz.", s.exposure != null ? (s.exposure * 100).toFixed(0) + "%" : "—")}
  </div>`;
}

// Trade tape: all trades (open + closed) with a time window (default last 1 year).
// Each row shows, directly beneath it, the candidate pool at the buy.
const _RM_WINDOWS = [["1 Ay", 1], ["3 Ay", 3], ["6 Ay", 6], ["1 Yıl", 12], ["Tümü", null]];
let _rmTradeWin = 12;

function _cutoffISO(months) {
  if (months == null) return null;
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  return d.toISOString().slice(0, 10);
}

function _filterTrades(trades, months) {
  const cut = _cutoffISO(months);
  return (trades || [])
    .filter(t => !t.exit_date || cut == null || t.exit_date >= cut)
    .sort((a, b) => {                                   // open first, then newest activity
      const ao = !a.exit_date, bo = !b.exit_date;
      if (ao !== bo) return ao ? -1 : 1;
      const ad = a.exit_date || a.entry_date || "", bd = b.exit_date || b.entry_date || "";
      return bd < ad ? -1 : bd > ad ? 1 : 0;
    });
}

function _tradeCands(ec) {
  if (!ec || !ec.length) return "";
  const chips = ec.map(c =>
    `<span class="rm-cand-chip" data-ticker="${escAttr(c.ticker)}" title="skor ${c.score != null ? fmt(c.score) : "—"}">${escHTML(c.ticker)}</span>`).join("");
  return `<div class="rm-trade-cands"><span class="rm-tc-l">Girişte adaylar:</span>${chips}</div>`;
}

function _rmTradeRows(trades, byTicker, months) {
  const rows = _filterTrades(trades, months);
  if (!rows.length) return '<div class="rm-empty-sm">Bu aralıkta işlem yok.</div>';
  return rows.map(t => {
    const { sector } = _liveCells(t.ticker, byTicker);
    const open = !t.exit_date;
    const status = open
      ? '<span class="rm-tstatus rm-open">Açık</span>'
      : `<span class="rm-treason" title="${escAttr(t.exit_reason || "")}">${escHTML(t.exit_reason || "Kapandı")}</span>`;
    const priceTxt = t.entry_price != null
      ? `$${fmt(t.entry_price)} → ${open ? "açık" : (t.exit_price != null ? "$" + fmt(t.exit_price) : "—")}`
      : "";
    return `<div class="rm-trade">
      <div class="rm-trade-main">
        <span class="rb-tkr" data-ticker="${escAttr(t.ticker)}">${escHTML(t.ticker)}</span>
        <span class="rb-sec">${sector}</span>
        <span class="rm-tdate">${escHTML(t.entry_date || "—")} → ${open ? "açık" : escHTML(t.exit_date)}</span>
        <span class="rm-tprice">${priceTxt}</span>
        <span class="${t.return_pct >= 0 ? "pos" : "neg"}">${t.return_pct != null ? fmtPct(t.return_pct) : "—"}</span>
        <span class="rm-tdays">${t.days_held != null ? t.days_held + "g" : "—"}</span>
        ${status}
      </div>
      ${_tradeCands(t.entry_candidates)}
    </div>`;
  }).join("");
}

function _renderWinChips() {
  const el = document.getElementById("rm-winchips");
  if (!el) return;
  el.innerHTML = _RM_WINDOWS.map(([lbl, m]) =>
    `<button class="rm-winchip${_rmTradeWin === m ? " active" : ""}" data-win="${m == null ? "all" : m}">${lbl}</button>`).join("");
  el.querySelectorAll(".rm-winchip").forEach(b => b.addEventListener("click", () => {
    _rmTradeWin = b.dataset.win === "all" ? null : +b.dataset.win;
    _renderWinChips(); _renderTradeWrap();
  }));
}

function _renderTradeWrap() {
  const wrap = document.getElementById("rm-trades-wrap");
  if (!wrap) return;
  wrap.innerHTML = _rmTradeRows(_rmRobot.trades, _rmBy, _rmTradeWin);
  wrap.querySelectorAll("[data-ticker]").forEach(elx =>
    elx.addEventListener("click", () => {
      const t = elx.dataset.ticker;
      openStockModal(t, _rmBy[t] || { Ticker: t });
    }));
}

function _rmRebal(rb) {
  if (!rb) return '<div class="rm-empty-sm">—</div>';
  const chip = (t, cls) => `<span class="rm-chip ${cls}">${escHTML(t)}</span>`;
  const add = (rb.added || []).map(t => chip("+ " + t, "rm-add")).join("") || '<span class="muted">—</span>';
  const drop = (rb.dropped || []).map(t => chip("− " + t, "rm-drop")).join("") || '<span class="muted">—</span>';
  return `<div class="rm-rebal">
    <div class="rm-rebal-d">${escHTML(rb.date || "")}</div>
    <div class="rm-rebal-row"><span class="rm-rebal-l">Eklenen</span><span>${add}</span></div>
    <div class="rm-rebal-row"><span class="rm-rebal-l">Çıkarılan</span><span>${drop}</span></div>
  </div>`;
}

// ── Render + lifecycle ────────────────────────────────────────────────────────

function _rmRender(robot, byTicker) {
  const legend = `<span class="rm-legend">
    <i style="background:#3b82f6"></i>Robot <i style="background:#94a3b8"></i>S&P 500 <i style="background:#a855f7"></i>Nasdaq 100</span>`;
  return `<div class="rm-head">
      <div class="rm-key">${escHTML(robot.key || "")}</div>
      <div class="rm-name">${escHTML(robot.name || "")}</div>
      <button id="rm-pin" class="rb-pin">📌 Sektörleri sabitle</button>
    </div>
    ${_rmStats(robot.stats)}
    <div class="rm-lbl">Performans — başlangıçtan beri ${legend}</div>
    <canvas id="rm-perf"></canvas>
    <div class="rm-lbl">Geri çekilme (drawdown)</div>
    <canvas id="rm-dd"></canvas>
    <div class="rm-2col">
      <div>
        <div class="rm-lbl">Aylık getiriler</div>${_heatmap(robot.equity)}
        <div class="rm-lbl" style="margin-top:10px">Sektör dağılımı</div>${_alloc(robot.holdings, byTicker)}
      </div>
      <div>
        <div class="rm-lbl">Tutuyor <span class="rb-n">${(robot.holdings || []).length}</span></div>${_holdingsTable(robot.holdings, byTicker)}
        <div class="rm-lbl rm-lbl-cand" style="margin-top:10px">Sıradaki Adaylar <span class="rb-n">${(robot.candidates || []).length}</span></div>${_candidatesTable(robot.candidates, byTicker)}
      </div>
    </div>
    <div class="rm-lbl">Son rebalans</div>${_rmRebal(robot.rebalance)}
    <div class="rm-lbl">İşlemler <span id="rm-winchips" class="rm-winchips"></span></div>
    <div id="rm-trades-wrap"></div>`;
}

function _rmDraw(robot) {
  const pc = document.getElementById("rm-perf");
  if (pc) { pc.width = Math.max(300, pc.parentElement.clientWidth - 4); pc.height = 200; _drawPerf(pc, robot); }
  const dc = document.getElementById("rm-dd");
  if (dc) { dc.width = Math.max(300, dc.parentElement.clientWidth - 4); dc.height = 56; _drawDD(dc, robot.equity); }
}

function openRobotModal(robot, byTicker) {
  if (!robot) return;
  _rmOpen = true; _rmRobot = robot; _rmBy = byTicker || {}; _rmTradeWin = 12;
  document.getElementById("robot-modal-title").textContent = robot.name || robot.key;
  document.getElementById("robot-modal").classList.add("open");
  const body = document.getElementById("robot-modal-body");
  body.innerHTML = _rmRender(robot, _rmBy);
  _rmDraw(robot);
  _renderWinChips();
  _renderTradeWrap();
  body.querySelectorAll("tr[data-ticker]").forEach(r =>
    r.addEventListener("click", () => {
      const t = r.dataset.ticker;
      openStockModal(t, _rmBy[t] || { Ticker: t });
    }));
  const pin = document.getElementById("rm-pin");
  if (pin) pin.addEventListener("click", () => {
    const secs = new Set();
    [...(robot.holdings || []), ...(robot.candidates || [])].forEach(x => {
      const live = _rmBy[x.ticker];
      if (live && live.Sector) secs.add(live.Sector);
    });
    if (secs.size) { setPins([...secs]); closeRobotModal(); showView("panel"); }
  });
}

function closeRobotModal() {
  _rmOpen = false;
  document.getElementById("robot-modal").classList.remove("open");
}

window.addEventListener("resize", () => { if (_rmOpen && _rmRobot) _rmDraw(_rmRobot); });

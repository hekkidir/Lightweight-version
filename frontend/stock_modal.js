/**
 * stock_modal.js — per-stock detail modal.
 *
 * Opened from a stock-table row. The current snapshot (state.stocks row) fills
 * the header + metrics grid; a 20-bar series fetched from /api/stock/{ticker}
 * drives the stage strip, price/volume chart, range bar, EMA panel and table.
 * Public API: openStockModal(ticker, snapshot) / closeStockModal().
 */

let _smOpen = false;
let _smBars = null;            // kept for redraw on resize

const SM_EMA = { ema10: "#3b82f6", ema20: "#f59e0b", ema50: "#a855f7", Close: "#e2e8f0" };


// ── Price + volume chart ──────────────────────────────────────────────────────

function _drawStockChart(canvas, bars) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  const n = bars.length;
  if (!n) return;

  const padL = 8, padR = 46, padT = 8, padB = 16;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const volH = plotH * 0.28, priceH = plotH - volH - 6;

  const ser = [];
  bars.forEach(b => ["Close", "ema10", "ema20", "ema50"].forEach(k => {
    if (b[k] != null && !isNaN(b[k])) ser.push(b[k]);
  }));
  let lo = Math.min(...ser), hi = Math.max(...ser);
  if (lo === hi) { lo -= 1; hi += 1; }
  const m = (hi - lo) * 0.08; lo -= m; hi += m;

  const x  = i => padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const yP = v => padT + priceH - ((v - lo) / (hi - lo)) * priceH;

  const vmax = Math.max(...bars.map(b => b.Volume || 0), 1);
  const volTop = padT + priceH + 6;
  const yV = v => volTop + volH - (v / vmax) * volH;
  const bw = Math.max(1, (plotW / n) * 0.6);
  bars.forEach((b, i) => {
    ctx.fillStyle = (b.change_pct || 0) >= 0 ? "rgba(16,185,129,0.45)" : "rgba(239,68,68,0.45)";
    const top = yV(b.Volume || 0);
    ctx.fillRect(x(i) - bw / 2, top, bw, volTop + volH - top);
  });

  const line = (key, color, w) => {
    ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = w;
    let started = false;
    bars.forEach((b, i) => {
      const v = b[key];
      if (v == null || isNaN(v)) return;
      const px = x(i), py = yP(v);
      if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
    });
    ctx.stroke();
  };
  line("ema50", SM_EMA.ema50, 1);
  line("ema20", SM_EMA.ema20, 1);
  line("ema10", SM_EMA.ema10, 1);
  line("Close", SM_EMA.Close, 1.8);

  ctx.fillStyle = "rgba(255,255,255,0.4)"; ctx.font = "9px system-ui"; ctx.textAlign = "left";
  ctx.fillText(hi.toFixed(2), W - padR + 4, padT + 8);
  ctx.fillText(lo.toFixed(2), W - padR + 4, padT + priceH);
  ctx.fillText(bars[0].Date, padL, H - 4);
  ctx.textAlign = "right"; ctx.fillText(bars[n - 1].Date, W - padR, H - 4); ctx.textAlign = "left";
}


// ── Section builders ──────────────────────────────────────────────────────────

function _smHeader(data, s) {
  const stage = s.Stage || "";
  const prev = s.Prev_Stage || "";
  const trans = (prev && prev !== stage) ? `<span class="sm-prev">${escHTML(prev)} →</span> ` : "";
  return `<div class="sm-head">
    <div class="sm-head-main">
      <span class="sm-ticker">${escHTML(data.ticker)}</span>
      <span class="sm-sector" title="${escAttr(data.sector || s.Sector || "")}">${escHTML(data.sector || s.Sector || "")}</span>
    </div>
    <div class="sm-head-right">
      <span class="stage-badge ${stageCls(stage)}">${trans}${escHTML(stage)}</span>
      <span class="sm-close-px">${fmt(s.Close)}</span>
      <span class="sm-day ${s.change_pct >= 0 ? "pos" : "neg"}">${fmtPct(s.change_pct)}</span>
    </div>
  </div>`;
}

function _smStrip(bars) {
  const cells = bars.map(b =>
    `<span class="sm-strip-cell ${stageCls(b.Stage)}" title="${b.Date}: ${escHTML(b.Stage)}"></span>`).join("");
  return `<div class="sm-lbl">Stage — son 20 gün</div><div class="sm-strip">${cells}</div>`;
}

function _smRange(bars, s) {
  const closes = bars.map(b => b.Close).filter(v => v != null);
  const lo = Math.min(...closes), hi = Math.max(...closes);
  const cur = s.Close != null ? s.Close : closes[closes.length - 1];
  const pos = hi > lo ? ((cur - lo) / (hi - lo)) * 100 : 50;
  const fromHi = hi > 0 ? ((cur - hi) / hi) * 100 : 0;
  return `<div class="sm-lbl">20 gün aralığı — zirveden <span class="${fromHi >= 0 ? "pos" : "neg"}">${fmtPct(fromHi)}</span></div>
    <div class="sm-range">
      <span class="sm-range-end">${fmt(lo)}</span>
      <div class="sm-range-track"><div class="sm-range-mark" style="left:${pos.toFixed(1)}%"></div></div>
      <span class="sm-range-end">${fmt(hi)}</span>
    </div>`;
}

function _smGrid(s) {
  const tile = (l, v, cls = "") => `<div class="sm-tile"><span class="sm-tile-l">${l}</span><span class="sm-tile-v ${cls}">${v}</span></div>`;
  const pct  = (l, v) => tile(l, fmtPct(v), v >= 0 ? "pos" : "neg");
  return `<div class="sm-grid">
    ${tile("Kapanış", fmt(s.Close))}
    ${pct("Gün", s.change_pct)}
    ${pct("Hafta", s.weekly)}
    ${pct("Ay", s.monthly)}
    ${pct("YBaşı", s.ytd)}
    ${tile("RSI", fmt(s.rsi, 1))}
    ${tile("ATR%", fmt(s.atr_pct))}
    ${tile("Ext", fmt(s.ext))}
    ${tile("RVOL", fmt(s.rvol_avg))}
    ${tile("Piyasa Değ.", fmtMcap(s.Market_Cap))}
    ${tile("Hacim Onayı", s.Vol_Confirmed ? "Evet" : "Hayır", s.Vol_Confirmed ? "vc" : "muted")}
  </div>`;
}

function _smEma(bars) {
  const lb = bars[bars.length - 1] || {};
  const row = (label, ema) => {
    const d = (ema && lb.Close) ? (lb.Close / ema - 1) * 100 : null;
    return `<div class="sm-d-row"><span>${label}</span><span class="${d >= 0 ? "pos" : "neg"}">${d == null ? "—" : fmtPct(d)}</span></div>`;
  };
  const up = lb.Close > lb.ema10 && lb.ema10 > lb.ema20 && lb.ema20 > lb.ema50;
  const dn = lb.Close < lb.ema10 && lb.ema10 < lb.ema20 && lb.ema20 < lb.ema50;
  const verdict = up ? '<span class="pos">Yükseliş dizilimi</span>'
                : dn ? '<span class="neg">Düşüş dizilimi</span>'
                     : '<span class="muted">Karışık</span>';
  return `<div class="sm-lbl">EMA yapısı — ${verdict}</div>
    <div class="sm-ema">${row("EMA10", lb.ema10)}${row("EMA20", lb.ema20)}${row("EMA50", lb.ema50)}${row("EMA200", lb.ema200)}</div>`;
}

function _smTable(bars) {
  const rows = [...bars].reverse().map(b => `<tr>
    <td>${b.Date}</td><td>${fmt(b.Close)}</td>
    <td class="${b.change_pct >= 0 ? "pos" : "neg"}">${fmtPct(b.change_pct)}</td>
    <td>${fmt(b.rsi, 1)}</td><td>${fmt(b.atr_pct)}</td><td>${fmt(b.rvol_avg)}</td>
    <td><span class="stage-badge ${stageCls(b.Stage)}">${escHTML(b.Stage)}</span></td>
  </tr>`).join("");
  return `<div class="sm-lbl">Son 20 gün</div>
    <div class="sm-table-wrap"><table class="sm-table">
      <thead><tr><th>Tarih</th><th>Kapanış</th><th>Gün%</th><th>RSI</th><th>ATR%</th><th>RVOL</th><th>Stage</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
}


// ── Render + lifecycle ────────────────────────────────────────────────────────

function _renderStockModal(body, data, snapshot) {
  const bars = data.bars || [];
  _smBars = bars;
  const sector = data.sector || snapshot.Sector || "";
  const legend = `<span class="sm-legend">
    <i style="background:${SM_EMA.Close}"></i>Close <i style="background:${SM_EMA.ema10}"></i>EMA10
    <i style="background:${SM_EMA.ema20}"></i>EMA20 <i style="background:${SM_EMA.ema50}"></i>EMA50</span>`;

  body.innerHTML =
    _smHeader(data, snapshot) +
    _smStrip(bars) +
    `<div class="sm-lbl">Fiyat & hacim — son 20 gün ${legend}</div><canvas id="sm-chart"></canvas>` +
    _smRange(bars, snapshot) +
    _smGrid(snapshot) +
    _smEma(bars) +
    _smTable(bars) +
    (sector ? `<button id="sm-pin-sector" class="sm-pin">📌 Sektörü sabitle: ${escHTML(sector)}</button>` : "");

  const canvas = document.getElementById("sm-chart");
  canvas.width = Math.max(200, body.clientWidth - 4);
  canvas.height = 200;
  _drawStockChart(canvas, bars);

  const pin = document.getElementById("sm-pin-sector");
  if (pin) pin.addEventListener("click", () => { setPins([sector]); closeStockModal(); });
}

async function openStockModal(ticker, snapshot) {
  _smOpen = true;
  document.getElementById("stock-modal-title").textContent = ticker;
  document.getElementById("stock-modal").classList.add("open");
  const body = document.getElementById("stock-modal-body");
  body.innerHTML = '<div class="sm-loading">Yükleniyor…</div>';
  let data;
  try {
    data = await fetchStock(ticker, 20);
  } catch (e) {
    if (_smOpen) body.innerHTML = `<div class="sm-loading neg">Veri alınamadı: ${escHTML(e.message)}</div>`;
    return;
  }
  if (!_smOpen) return;                       // closed while fetching
  _renderStockModal(body, data, snapshot || {});
}

function closeStockModal() {
  _smOpen = false;
  _smBars = null;
  document.getElementById("stock-modal").classList.remove("open");
}

window.addEventListener("resize", () => {
  if (!_smOpen || !_smBars) return;
  const body = document.getElementById("stock-modal-body");
  const canvas = document.getElementById("sm-chart");
  if (!canvas) return;
  canvas.width = Math.max(200, body.clientWidth - 4);
  _drawStockChart(canvas, _smBars);
});

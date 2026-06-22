/**
 * rrg_modal.js — fullscreen RRG: a wide canvas + an inspector panel.
 *
 * Panel modules: sector detail card (hover/pin), quadrant legend with live
 * counts, a rotation leaderboard, and display controls (tails / labels / tail
 * length). Drawing is delegated to drawRRG() in rrg.js with display opts.
 * Public API used by app.js: openRRGModal / closeRRGModal / syncRRGModal.
 */

const rrgModal = {
  open: false, rotation: null, sectors: [], focus: null, pins: new Set(),
  hover: null, showTails: true, showLabels: false, tailLen: 15, sort: "vel",
};

const _ARROWS = ["→", "↗", "↑", "↖", "←", "↙", "↓", "↘"];
function _arrow(dx, dy) {
  if (Math.hypot(dx, dy) < 1e-6) return "·";
  let oct = Math.round((Math.atan2(dy, dx) * 180 / Math.PI) / 45);
  if (oct < 0) oct += 8;
  return _ARROWS[oct % 8];
}

function _metaMap() {
  const m = {};
  (rrgModal.sectors || []).forEach(s => { m[s.Sector] = s; });
  return m;
}

// sector -> { quad row, meta row, dx, dy } merged for the detail/leaderboard.
function _info(sector) {
  const rot = rotMap(rrgModal.rotation)[sector] || {};
  const meta = _metaMap()[sector] || {};
  const t = trailMap(rrgModal.rotation)[sector];
  const dx = (t && t.length) ? (rot.X ?? 0) - t[0].X : 0;
  const dy = (t && t.length) ? (rot.Y ?? 0) - t[0].Y : 0;
  return { rot, meta, dx, dy };
}


// ── Canvas ────────────────────────────────────────────────────────────────────

function _modalCanvas() { return document.getElementById("rrg-canvas-full"); }

function _sizeModalCanvas() {
  const wrap = document.getElementById("rrg-canvas-wrap");
  const c = _modalCanvas();
  const w = Math.max(300, wrap.clientWidth - 16);
  const h = Math.max(300, wrap.clientHeight - 16);
  c.width = w; c.height = h;
}

function _drawModal() {
  _sizeModalCanvas();
  drawRRG(_modalCanvas(), rrgModal.rotation, rrgModal.focus, rrgModal.pins, {
    showTails: rrgModal.showTails,
    showAllLabels: rrgModal.showLabels,
    tailLen: rrgModal.tailLen,
  });
}


// ── Panel ─────────────────────────────────────────────────────────────────────

function _buildSkeleton() {
  document.getElementById("rrg-panel").innerHTML = `
    <div id="rp-detail" class="rp-card"></div>
    <div class="rp-card">
      <div class="rp-title">Bölgeler</div>
      <div id="rp-quads"></div>
    </div>
    <div class="rp-card">
      <div class="rp-title">Lider Tablosu
        <span id="rp-sort">
          <button class="rp-sortbtn" data-sort="vel">Hız</button>
          <button class="rp-sortbtn" data-sort="mom">Momentum</button>
        </span>
      </div>
      <div id="rp-leader"></div>
    </div>
    <div class="rp-card">
      <div class="rp-title">Görünüm</div>
      <label class="rp-ctl"><input type="checkbox" id="rp-tails"> Kuyruklar</label>
      <label class="rp-ctl"><input type="checkbox" id="rp-labels"> Tüm etiketler</label>
      <label class="rp-ctl">Kuyruk
        <input type="range" id="rp-taillen" min="3" max="15">
        <span id="rp-taillen-val" class="rp-mono"></span> gün
      </label>
    </div>`;

  document.getElementById("rp-tails").addEventListener("change", e => {
    rrgModal.showTails = e.target.checked; _drawModal();
  });
  document.getElementById("rp-labels").addEventListener("change", e => {
    rrgModal.showLabels = e.target.checked; _drawModal();
  });
  document.getElementById("rp-taillen").addEventListener("input", e => {
    rrgModal.tailLen = +e.target.value;
    document.getElementById("rp-taillen-val").textContent = e.target.value;
    _drawModal();
  });
  document.querySelectorAll("#rp-sort .rp-sortbtn").forEach(b =>
    b.addEventListener("click", () => { rrgModal.sort = b.dataset.sort; _renderLeader(); }));
}

function _renderPanel() {
  document.getElementById("rp-tails").checked  = rrgModal.showTails;
  document.getElementById("rp-labels").checked = rrgModal.showLabels;
  document.getElementById("rp-taillen").value  = rrgModal.tailLen;
  document.getElementById("rp-taillen-val").textContent = rrgModal.tailLen;
  _renderDetail();
  _renderQuads();
  _renderLeader();
}

function _lastPin() {
  const arr = [...rrgModal.pins];
  return arr.length ? arr[arr.length - 1] : null;
}

function _renderDetail() {
  const el = document.getElementById("rp-detail");
  const sector = rrgModal.hover || _lastPin();
  if (!sector) {
    el.innerHTML = '<div class="rp-empty">Haritada bir sektörün üstüne gelin.</div>';
    return;
  }
  const { rot, meta, dx, dy } = _info(sector);
  const col = RRG_DOT[rot.Quadrant] || "#aaa";
  const pct = (v) => v == null || isNaN(v) ? "—"
    : `<span class="${v >= 0 ? "pos" : "neg"}">${fmtPct(v)}</span>`;
  const row = (lbl, val) => `<div class="rp-d-row"><span>${lbl}</span><span>${val}</span></div>`;
  el.innerHTML =
    `<div class="rp-d-name" style="color:${col}">${escHTML(sector)}</div>` +
    `<div class="rp-d-quad" style="color:${col}">${rot.Quadrant || "—"} ` +
      `<span class="rp-mono">${_arrow(dx, dy)}</span></div>` +
    row("RS / RM", `<span class="rp-mono">${fmt(rot.X)} / ${fmt(rot.Y)}</span>`) +
    row("ΔRS / ΔRM", `<span class="rp-mono">${(dx >= 0 ? "+" : "") + dx.toFixed(2)} / ` +
      `${(dy >= 0 ? "+" : "") + dy.toFixed(2)}</span>`) +
    row("Güç Skoru", fmt(rot.Strength_Score)) +
    row("Hafta / Ay / YBaşı", `${pct(meta.Weekly)} ${pct(meta.Monthly)} ${pct(meta.YTD)}`) +
    row("Breadth", `${fmt(meta.Breadth_Pct, 0)}%`) +
    row("Ort. RSI / RVOL", `<span class="rp-mono">${fmt(meta.Avg_RSI, 0)} / ${fmt(meta.Avg_RVOL)}</span>`) +
    row("A/D", `<span class="rp-mono">${meta.AD || "—"}</span>`) +
    (meta.Top3 ? `<div class="rp-d-top">${escHTML(meta.Top3)}</div>` : "");
}

function _renderQuads() {
  const order = ["STRONG", "WARMING", "COOLING", "WEAK"];
  const counts = { STRONG: 0, WARMING: 0, COOLING: 0, WEAK: 0 };
  const bySector = {};
  (rrgModal.rotation.current || []).forEach(r => {
    if (counts[r.Quadrant] != null) { counts[r.Quadrant]++; (bySector[r.Quadrant] ||= []).push(r.Sector); }
  });
  const el = document.getElementById("rp-quads");
  el.innerHTML = "";
  order.forEach(q => {
    const secs = bySector[q] || [];
    const allPinned = secs.length && secs.every(s => rrgModal.pins.has(s));
    const r = h("div", "rp-quad-row" + (allPinned ? " active" : ""));
    r.innerHTML =
      `<span class="rp-swatch" style="background:${RRG_DOT[q]}"></span>` +
      `<span class="rp-quad-name">${q}</span><span class="rp-quad-n">${counts[q]}</span>`;
    r.addEventListener("click", () => {
      const next = new Set(rrgModal.pins);
      if (allPinned) secs.forEach(s => next.delete(s));
      else secs.forEach(s => next.add(s));
      setPins(next);   // app.js -> triggers renderAll -> syncRRGModal
    });
    el.appendChild(r);
  });
}

function _renderLeader() {
  document.querySelectorAll("#rp-sort .rp-sortbtn").forEach(b =>
    b.classList.toggle("active", b.dataset.sort === rrgModal.sort));
  const list = (rrgModal.rotation.current || []).map(r => {
    const { dx, dy } = _info(r.Sector);
    return { sector: r.Sector, quad: r.Quadrant, vel: Math.hypot(dx, dy), mom: dy };
  }).sort((a, b) => b[rrgModal.sort] - a[rrgModal.sort]).slice(0, 10);

  const el = document.getElementById("rp-leader");
  el.innerHTML = "";
  list.forEach((it, i) => {
    const val = rrgModal.sort === "vel" ? it.vel.toFixed(2) : (it.mom >= 0 ? "+" : "") + it.mom.toFixed(2);
    const r = h("div", "rp-leader-row" + (rrgModal.pins.has(it.sector) ? " active" : ""));
    r.innerHTML =
      `<span class="rp-rank">${i + 1}</span>` +
      `<span class="rp-swatch" style="background:${RRG_DOT[it.quad] || "#666"}"></span>` +
      `<span class="rp-leader-name" title="${escAttr(it.sector)}">${escHTML(it.sector)}</span>` +
      `<span class="rp-leader-val rp-mono">${val}</span>`;
    r.addEventListener("click", () => togglePin(it.sector));   // app.js
    el.appendChild(r);
  });
}


// ── Canvas interaction (own handlers; no floating tooltip in the modal) ────────

function _wireCanvas() {
  const c = _modalCanvas();
  if (c._rpWired) return;
  c._rpWired = true;
  c.addEventListener("mousemove", e => {
    const dot = _hitTest(c, e);
    c.style.cursor = dot ? "pointer" : "default";
    const next = dot ? dot.row.Sector : null;
    if (next !== rrgModal.hover) { rrgModal.hover = next; _renderDetail(); }
  });
  c.addEventListener("mouseleave", () => {
    c.style.cursor = "default";
    if (rrgModal.hover) { rrgModal.hover = null; _renderDetail(); }
  });
  c.addEventListener("click", e => {
    const dot = _hitTest(c, e);
    if (dot) togglePin(dot.row.Sector);
  });
}


// ── Public API ────────────────────────────────────────────────────────────────

function openRRGModal(rotation, sectors, focus, pins) {
  rrgModal.open = true;
  rrgModal.rotation = rotation; rrgModal.sectors = sectors;
  rrgModal.focus = focus; rrgModal.pins = pins; rrgModal.hover = null;
  document.getElementById("rrg-modal").classList.add("open");
  _buildSkeleton();
  _drawModal();
  _wireCanvas();
  _renderPanel();
}

function closeRRGModal() {
  rrgModal.open = false;
  rrgModal.hover = null;
  document.getElementById("rrg-modal").classList.remove("open");
}

// Called from renderAll(): keep the open modal in sync with pin/data changes.
function syncRRGModal(rotation, sectors, focus, pins) {
  if (!rrgModal.open) return;
  rrgModal.rotation = rotation; rrgModal.sectors = sectors;
  rrgModal.focus = focus; rrgModal.pins = pins;
  _drawModal();
  _renderPanel();
}

window.addEventListener("resize", () => { if (rrgModal.open) _drawModal(); });

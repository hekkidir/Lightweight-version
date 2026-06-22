/**
 * rrg.js — B frame: Relative Rotation Graph (canvas).
 *
 * Axes are anchored at TRUE 0,0 with a symmetric scale, so a dot's colour
 * (Quadrant, whose boundary is 0,0) always matches its visual quadrant. Tails
 * are drawn as a fading comet (old=faint -> now=solid). All sectors are drawn;
 * the active group is bright, the rest dimmed; pinned sectors (labelSet) get a
 * bold dot + name label and stay bright even outside the group.
 * Interactive: hover shows a tooltip; click toggles a sector pin.
 */

const RRG_DOT = { STRONG: "#10b981", WARMING: "#3b82f6", COOLING: "#f59e0b", WEAK: "#ef4444" };

function _hexA(hex, a) {
  const v = Math.round(Math.max(0, Math.min(1, a)) * 255).toString(16).padStart(2, "0");
  return hex + v;
}

// Per-canvas dot hit-maps; rebuilt on every draw.
const _hitmaps = new WeakMap();
// Last drawn rotation (for delta computation in the tooltip).
let _lastRotation = null;

// ── Tooltip ──────────────────────────────────────────────────────────────────

function _tt() { return document.getElementById("rrg-tooltip"); }

function _showTooltip(e, row, dx, dy) {
  const tt = _tt(); if (!tt) return;
  const col = RRG_DOT[row.Quadrant] || "#aaa";
  const fmt = v => (v >= 0 ? "+" : "") + v.toFixed(2);
  const dxCls = dx >= 0 ? "rtt-pos" : "rtt-neg";
  const dyCls = dy >= 0 ? "rtt-pos" : "rtt-neg";
  tt.innerHTML =
    `<div class="rtt-name" style="color:${col}">${row.Sector}</div>` +
    `<div class="rtt-row"><span class="rtt-quad" style="color:${col}">${row.Quadrant}</span></div>` +
    `<div class="rtt-row"><span class="rtt-lbl">RS</span><span>${row.X.toFixed(2)}</span>` +
    `<span class="rtt-lbl">RM</span><span>${row.Y.toFixed(2)}</span></div>` +
    `<div class="rtt-row"><span class="rtt-lbl">ΔRS</span><span class="${dxCls}">${fmt(dx)}</span>` +
    `<span class="rtt-lbl">ΔRM</span><span class="${dyCls}">${fmt(dy)}</span></div>` +
    `<div class="rtt-hint">Click to focus</div>`;
  tt.style.display = "block";
  // Position near cursor, stay in viewport.
  const tw = tt.offsetWidth, th = tt.offsetHeight;
  const vw = window.innerWidth, vh = window.innerHeight;
  let left = e.clientX + 14, top = e.clientY - 10;
  if (left + tw > vw - 8) left = e.clientX - tw - 14;
  if (top + th > vh - 8) top = vh - th - 8;
  if (top < 8) top = 8;
  tt.style.left = left + "px";
  tt.style.top  = top  + "px";
}

function _hideTooltip() {
  const tt = _tt(); if (tt) tt.style.display = "none";
}

// ── Hit testing ──────────────────────────────────────────────────────────────

function _hitTest(canvas, e) {
  const hitmap = _hitmaps.get(canvas);
  if (!hitmap || !hitmap.length) return null;
  const rect = canvas.getBoundingClientRect();
  // Convert CSS pixels -> canvas pixels (handles high-DPI if ever used).
  const mx = (e.clientX - rect.left) * (canvas.width  / rect.width);
  const my = (e.clientY - rect.top)  * (canvas.height / rect.height);
  let best = null, bestD = Infinity;
  for (const dot of hitmap) {
    const d = Math.hypot(mx - dot.cx, my - dot.cy);
    if (d <= dot.radius * 2.5 && d < bestD) { best = dot; bestD = d; }
  }
  return best;
}

// ── Event attachment (idempotent — attach once per canvas element) ────────────

const _wired = new WeakSet();

function _attachEvents(canvas) {
  if (_wired.has(canvas)) return;
  _wired.add(canvas);

  canvas.addEventListener("mousemove", e => {
    const dot = _hitTest(canvas, e);
    canvas.style.cursor = dot ? "pointer" : "default";
    if (dot) {
      const trails = _lastRotation ? trailMap(_lastRotation) : {};
      const t = trails[dot.row.Sector];
      const dx = (t && t.length) ? dot.row.X - t[0].X : 0;
      const dy = (t && t.length) ? dot.row.Y - t[0].Y : 0;
      _showTooltip(e, dot.row, dx, dy);
    } else {
      _hideTooltip();
    }
  });

  canvas.addEventListener("mouseleave", () => {
    _hideTooltip();
    canvas.style.cursor = "default";
  });

  canvas.addEventListener("click", e => {
    const dot = _hitTest(canvas, e);
    if (dot) togglePin(dot.row.Sector);   // togglePin defined in app.js (same global scope)
  });
}

// ── Drawing ──────────────────────────────────────────────────────────────────

// opts: { showTails=true, showAllLabels=false, tailLen=Infinity } — used by the
// fullscreen modal's display controls; the inline map relies on the defaults.
function drawRRG(canvas, rotation, focus, labelSet, opts = {}) {
  const showTails     = opts.showTails !== false;
  const showAllLabels = !!opts.showAllLabels;
  const tailLen       = opts.tailLen != null ? opts.tailLen : Infinity;

  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  const PAD = 40, cW = W - 2 * PAD, cH = H - 2 * PAD;
  const midX = PAD + cW / 2, midY = PAD + cH / 2;

  ctx.clearRect(0, 0, W, H);

  // Quadrant backgrounds (canvas centre == data 0,0)
  ctx.fillStyle = "rgba(16,185,129,0.07)"; ctx.fillRect(midX, PAD, cW / 2, cH / 2);       // STRONG  TR
  ctx.fillStyle = "rgba(59,130,246,0.07)"; ctx.fillRect(PAD, PAD, cW / 2, cH / 2);        // WARMING TL
  ctx.fillStyle = "rgba(245,158,11,0.07)"; ctx.fillRect(midX, midY, cW / 2, cH / 2);      // COOLING BR
  ctx.fillStyle = "rgba(239,68,68,0.07)";  ctx.fillRect(PAD, midY, cW / 2, cH / 2);       // WEAK    BL

  ctx.strokeStyle = "rgba(255,255,255,0.15)"; ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(PAD, midY); ctx.lineTo(PAD + cW, midY);
  ctx.moveTo(midX, PAD); ctx.lineTo(midX, PAD + cH);
  ctx.stroke();

  const pts = rotation.current || [];
  if (!pts.length) { _hitmaps.set(canvas, []); return; }

  // Symmetric range so 0 maps to the centre on both axes.
  const xs = pts.map(r => r.X), ys = pts.map(r => r.Y);
  const rangeX = Math.max(...xs.map(Math.abs), 0.5) * 1.15;
  const rangeY = Math.max(...ys.map(Math.abs), 0.5) * 1.15;
  const toC = (x, y) => [
    PAD + ((x + rangeX) / (2 * rangeX)) * cW,
    PAD + cH - ((y + rangeY) / (2 * rangeY)) * cH,
  ];

  const tails  = trailMap(rotation);
  const hasFocus = focus instanceof Set;
  const r0 = Math.max(3, Math.round(cW / 110));
  const hitmap = [];

  pts.forEach(row => {
    const col      = RRG_DOT[row.Quadrant] || "#666";
    const isLabel  = labelSet.has(row.Sector);              // pinned -> bold + name
    const inFocus  = !hasFocus || focus.has(row.Sector) || isLabel;  // pins stay bright outside the group
    const prominent = isLabel || (hasFocus && inFocus);
    let chain = [...(tails[row.Sector] || []), row];
    if (chain.length > tailLen + 1) chain = chain.slice(chain.length - (tailLen + 1));

    // Comet tail: opacity + width grow toward the current dot.
    if (showTails) {
      for (let i = 1; i < chain.length; i++) {
        const t = i / (chain.length - 1);
        const a = prominent ? 0.25 + 0.75 * t
                            : (hasFocus ? 0.04 + 0.05 * t : 0.12 + 0.18 * t);
        const [ax, ay] = toC(chain[i - 1].X, chain[i - 1].Y);
        const [bx, by] = toC(chain[i].X, chain[i].Y);
        ctx.beginPath();
        ctx.strokeStyle = _hexA(col, a);
        ctx.lineWidth   = prominent ? 0.8 + 1.6 * t : 0.7;
        ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      }
    }

    const [cx, cy] = toC(row.X, row.Y);
    const dotR = isLabel ? r0 * 1.6 : r0;

    ctx.beginPath();
    ctx.arc(cx, cy, dotR, 0, Math.PI * 2);
    ctx.fillStyle = inFocus ? col : _hexA(col, 0.22);
    ctx.fill();

    if (isLabel || (showAllLabels && inFocus)) {
      ctx.fillStyle = isLabel ? "#fff" : "rgba(255,255,255,0.55)";
      const fs = isLabel ? Math.max(10, r0 * 2) : Math.max(8, r0 * 1.3);
      ctx.font = `${isLabel ? "bold " : ""}${fs}px system-ui`;
      ctx.fillText(row.Sector.split(" ")[0], cx + r0 * 1.8, cy + r0 * 0.7);
    }

    hitmap.push({ sector: row.Sector, cx, cy, radius: dotR, row });
  });

  _hitmaps.set(canvas, hitmap);
  _lastRotation = rotation;

  ctx.font = "11px system-ui";
  ctx.fillStyle = "rgba(255,255,255,0.3)";
  ctx.fillText("WARMING", PAD + 6, PAD + 16);
  ctx.fillText("STRONG",  midX + 6, PAD + 16);
  ctx.fillText("WEAK",    PAD + 6, PAD + cH - 6);
  ctx.fillText("COOLING", midX + 6, PAD + cH - 6);
}


// Inline (non-fullscreen) map. The fullscreen modal lives in rrg_modal.js.
function renderRRG(rotation, focus, labelSet) {
  const c = document.getElementById("rrg-canvas");
  const body = c.parentElement;                       // card-body fills the (wide) card
  const w   = Math.max(200, body.clientWidth  - 8);
  const hgt = Math.max(200, body.clientHeight - 8);
  if (c.width  !== w)   c.width  = w;                 // setting size also clears -> guard it
  if (c.height !== hgt) c.height = hgt;
  drawRRG(c, rotation, focus, labelSet);
  _attachEvents(c);
}

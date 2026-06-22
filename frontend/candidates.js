/**
 * candidates.js — D frame: Aday Hisseler (STRONG/WARMING + Güçlenen columns).
 * Scoring mirrors the old dashboard. Phase 1: multi-select cross-frame filter.
 * (why-tag + score breakdown land in Phase 6.)
 */

const SCORE_MIN_MAIN = 2.39;
const SCORE_MIN_GUC  = 1.90;

function isHealthy2C(s) {
  if (!s.Vol_Confirmed) return false;
  if (s.Close == null || s.ema10 == null || s.Close <= s.ema10) return false;
  if ((s.ext ?? 999) >= 9) return false;
  if (!["2B", "2C"].includes(s.Prev_Stage || "")) return false;
  return true;
}

function buildCandidates(stocks, rotation) {
  const rot = rotMap(rotation);
  const guc = guclenenSet(rotation);

  const mainList = [], gucList = [];
  stocks.forEach(s => {
    const stage = String(s.Stage || "");
    const sec = rot[s.Sector];
    if (!sec) return;
    const isMainQuad = ["STRONG", "WARMING"].includes(sec.Quadrant);
    const isGuc = guc.has(s.Sector);
    if (!isMainQuad && !isGuc) return;
    if (!["2A", "2B", "2C"].includes(stage)) return;
    if (stage === "2C" && !isHealthy2C(s)) return;
    if (s.rsi == null) return;

    const volMult = s.Vol_Confirmed ? 1.25 : 1.0;
    const stageMult = stage === "2C" ? 0.7 : 1.0;
    const rsiTerm = Math.max(0, s.rsi - 50) / 20;
    const score = sec.Strength_Score * rsiTerm * volMult * stageMult;
    const item = {
      ticker: s.Ticker, sector: s.Sector, stage, volConf: !!s.Vol_Confirmed,
      score, quadrant: sec.Quadrant, rsi: s.rsi,
      strength: sec.Strength_Score, rsiTerm, volMult, stageMult,
    };
    if (isMainQuad && score >= SCORE_MIN_MAIN) mainList.push(item);
    if (isGuc && score >= SCORE_MIN_GUC) gucList.push(item);
  });

  mainList.sort((a, b) => b.score - a.score);
  gucList.sort((a, b) => b.score - a.score);
  return { main: mainList, guc: gucList };
}

function renderCandidates(stocks, rotation, active, onSectorToggle) {
  let { main, guc } = buildCandidates(stocks, rotation);
  if (active) {
    main = main.filter(c => active.has(c.sector));
    guc  = guc.filter(c => active.has(c.sector));
  }

  function row(c, isGuc) {
    const cls = isGuc ? "stage-guc" : stageCls(c.stage);
    const volBadge = c.volConf ? '<span class="vol-badge">V</span>' : "";
    // Visible why-tag + full score breakdown on hover.
    const why = `${c.quadrant} · RSI ${c.rsi != null ? c.rsi.toFixed(0) : "—"}`
      + (c.volConf ? " · Vol✓" : "") + (isGuc ? " · Güçlenen" : "");
    const breakdown = `Skor ${c.score.toFixed(2)} = Güç ${fmt(c.strength)}`
      + ` × RSI ${fmt(c.rsiTerm)} × Vol ${c.volMult} × Stage ${c.stageMult}`;
    const d = document.createElement("div");
    d.className = "cand-row";
    d.title = breakdown;
    d.innerHTML = `
      <div class="cand-main">
        <span class="cand-ticker">${escHTML(c.ticker)}</span>
        <span class="cand-sector" title="${escAttr(c.sector)}">${escHTML(c.sector)}</span>
        <span class="cand-stage ${cls}">${escHTML(c.stage)}${volBadge}</span>
        <span class="cand-score">${c.score.toFixed(2)}</span>
      </div>
      <div class="cand-why">${escHTML(why)}</div>
    `;
    d.addEventListener("click", () => onSectorToggle(c.sector));
    return d;
  }

  document.getElementById("cand-main-count").textContent = main.length;
  document.getElementById("cand-guc-count").textContent = guc.length;

  const mainEl = document.getElementById("cand-main-rows");
  const gucEl = document.getElementById("cand-guc-rows");
  mainEl.innerHTML = main.length ? "" : '<div class="empty">—</div>';
  gucEl.innerHTML = guc.length ? "" : '<div class="empty">—</div>';
  main.forEach(c => mainEl.appendChild(row(c, false)));
  guc.forEach(c => gucEl.appendChild(row(c, true)));
}

/**
 * compute.js — shared rotation computations (pure). Used by sectors, rrg and
 * candidates so the math lives in one place: rotation lookups, ΔY, and the
 * category sets (quadrants, velocity, breakouts, güçlenen, zayıflayan).
 */

// sector -> rotation row
function rotMap(rotation) {
  const m = {};
  (rotation.current || []).forEach(r => { m[r.Sector] = r; });
  return m;
}

// sector -> trail points sorted oldest..newest
function trailMap(rotation) {
  const m = {};
  (rotation.tails || []).forEach(t => {
    (m[t.Sector] ||= []).push(t);
  });
  Object.values(m).forEach(arr => arr.sort((a, b) => a.Day_Offset - b.Day_Offset));
  return m;
}

// sector -> ΔY (current Y minus oldest trail Y); 0 when no trail
function dyMap(rotation) {
  const trails = trailMap(rotation);
  const m = {};
  (rotation.current || []).forEach(r => {
    const t = trails[r.Sector];
    m[r.Sector] = (t && t.length) ? r.Y - t[0].Y : 0;
  });
  return m;
}

// Güçlenen quadrant weights. STRONG/WARMING lowered vs the old dashboard so they
// dominate the ranking less and more emerging (COOLING/WEAK) sectors surface.
const Q_WEIGHT = { STRONG: 1.7, WARMING: 1.55, COOLING: 1.1, WEAK: 1.0 };

// 🚀 En Hızlı — sectors that moved the most on the RRG (vector length over trail).
function velocitySet(rotation, n = 8) {
  const trails = trailMap(rotation);
  const out = [];
  (rotation.current || []).forEach(r => {
    const t = trails[r.Sector];
    if (!t || !t.length) return;
    const dx = r.X - t[0].X, dy = r.Y - t[0].Y;
    out.push({ sector: r.Sector, dist: Math.hypot(dx, dy) });
  });
  out.sort((a, b) => b.dist - a.dist);
  return new Set(out.slice(0, n).map(o => o.sector));
}

// 🚨 Kırılımlar — near an axis (|X| or |Y| < 0.3) and moving to cross it.
function breakoutSet(rotation) {
  const trails = trailMap(rotation);
  const NEAR = 0.3, MIN = 0.15;
  const out = new Set();
  (rotation.current || []).forEach(r => {
    const t = trails[r.Sector];
    if (!t || !t.length) return;
    const dx = r.X - t[0].X, dy = r.Y - t[0].Y;
    if (Math.abs(r.X) < NEAR && ((r.X < 0 && dx > MIN) || (r.X >= 0 && dx < -MIN))) out.add(r.Sector);
    if (Math.abs(r.Y) < NEAR && ((r.Y < 0 && dy > MIN) || (r.Y >= 0 && dy < -MIN))) out.add(r.Sector);
  });
  return out;
}

// Güçlenen — weighted-percentile ΔY within quadrant (top n). Shared with candidates.
function guclenenSet(rotation, n = 12) {
  const dy = dyMap(rotation);
  const byQuad = { STRONG: [], WARMING: [], COOLING: [], WEAK: [] };
  (rotation.current || []).forEach(r => {
    if (byQuad[r.Quadrant]) byQuad[r.Quadrant].push({ sector: r.Sector, dy: dy[r.Sector] ?? 0 });
  });
  const scored = [];
  Object.entries(byQuad).forEach(([q, items]) => {
    const sorted = [...items].sort((a, b) => a.dy - b.dy);
    items.forEach(item => {
      const rank = sorted.findIndex(s => s.sector === item.sector) + 1;
      scored.push({ sector: item.sector, score: (rank / sorted.length) * Q_WEIGHT[q] });
    });
  });
  return new Set(scored.sort((a, b) => b.score - a.score).slice(0, n).map(r => r.sector));
}

// Zayıflayan — most-negative ΔY (bottom n).
function zayiflayanSet(rotation, n = 12) {
  const dy = dyMap(rotation);
  return new Set((rotation.current || [])
    .map(r => ({ sector: r.Sector, dy: dy[r.Sector] ?? 0 }))
    .filter(r => r.dy < 0)
    .sort((a, b) => a.dy - b.dy)
    .slice(0, n)
    .map(r => r.sector));
}

// Resolve a category key -> Set of sectors (null = no filter / "All").
function categorySet(rotation, cat) {
  if (["STRONG", "WARMING", "COOLING", "WEAK"].includes(cat))
    return new Set((rotation.current || []).filter(r => r.Quadrant === cat).map(r => r.Sector));
  if (cat === "VELOCITY") return velocitySet(rotation);
  if (cat === "PENDING") return breakoutSet(rotation);
  if (cat === "GUCLENEN") return guclenenSet(rotation);
  if (cat === "ZAYIFLAYAN") return zayiflayanSet(rotation);
  return null;
}

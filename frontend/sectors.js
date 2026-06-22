/**
 * sectors.js — A frame: category quick-pick chips + sector list.
 *
 * The list is sorted by Strength_Score (desc). A category narrows the list to
 * that category; the search box narrows by name. Pinned rows show a ✓ and a
 * selected highlight; clicking a row toggles its pin (see app.togglePin).
 */

const SECTOR_CATS = [
  { key: "",           label: "All" },
  { key: "STRONG",     label: "Strong" },
  { key: "WARMING",    label: "Warming" },
  { key: "COOLING",    label: "Cooling" },
  { key: "WEAK",       label: "Weak" },
  { key: "GUCLENEN",   label: "Güçlenen" },
  { key: "ZAYIFLAYAN", label: "Zayıflayan" },
  { key: "VELOCITY",   label: "🚀 En Hızlı" },
  { key: "PENDING",    label: "🚨 Kırılımlar" },
];

function catLabel(key) {
  const c = SECTOR_CATS.find(x => x.key === key);
  return c ? c.label : key;
}

// Generic category-chip bar.
function renderCatChips(elId, category, onCat) {
  const el = document.getElementById(elId);
  el.innerHTML = "";
  SECTOR_CATS.forEach(c => {
    const b = h("button", "cat-chip" + (category === c.key ? " active" : ""), c.label);
    b.addEventListener("click", () => onCat(c.key));
    el.appendChild(b);
  });
}

// The sectors currently listed in the sidebar (category + search applied),
// sorted by Strength_Score. Shared by the list renderer and "Tümünü Seç".
function visibleSectors(sectors, rotation, category, search) {
  const rot = rotMap(rotation);
  let list = [...sectors].sort(
    (a, b) => (rot[b.Sector]?.Strength_Score || 0) - (rot[a.Sector]?.Strength_Score || 0));

  if (category) {
    const set = categorySet(rotation, category);
    if (set) list = list.filter(s => set.has(s.Sector));
  }
  if (search) {
    const q = search.toLowerCase();
    list = list.filter(s => (s.Sector || "").toLowerCase().includes(q));
  }
  return list;
}

function renderSectorList(sectors, rotation, focusSet, category, search, onToggle) {
  const el = document.getElementById("sector-list");
  el.innerHTML = "";
  const rot = rotMap(rotation);
  const list = visibleSectors(sectors, rotation, category, search);

  if (!list.length) {
    el.innerHTML = '<div class="empty">Sektör bulunamadı.</div>';
    return;
  }

  list.forEach(sec => {
    const r = rot[sec.Sector] || {};
    const sel = focusSet ? focusSet.has(sec.Sector) : false;
    const row = document.createElement("div");
    row.className = "sector-row" + (sel ? " selected" : "");
    row.innerHTML = `
      <span class="sec-check">${sel ? "✓" : ""}</span>
      <span class="sec-name" title="${escAttr(sec.Sector)}">${escHTML(sec.Sector)}</span>
      <span class="sec-quad quad-${(r.Quadrant || "").toLowerCase()}">${r.Quadrant || "—"}</span>
      <span class="sec-breadth">${fmt(sec.Breadth_Pct, 0)}%</span>
      <span class="sec-weekly ${sec.Weekly >= 0 ? "pos" : "neg"}">${fmtPct(sec.Weekly)}</span>
    `;
    row.addEventListener("click", () => onToggle(sec.Sector));
    el.appendChild(row);
  });
}

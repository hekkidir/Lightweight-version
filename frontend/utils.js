/**
 * utils.js — shared DOM + formatting helpers. No state.
 */

function h(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text != null) el.textContent = text;
  return el;
}

function escHTML(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escAttr(s) {
  return escHTML(s).replace(/"/g, "&quot;");
}

function fmt(v, decimals = 2) {
  if (v == null || isNaN(v)) return "—";
  const n = Number(v);
  return isNaN(n) ? "—" : n.toFixed(decimals);
}

function fmtPct(v) {
  if (v == null || isNaN(v)) return "—";
  const n = Number(v);
  return isNaN(n) ? "—" : (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

function fmtMcap(v) {
  if (v == null || isNaN(v)) return "—";
  const n = Number(v);
  if (n >= 1e12) return (n / 1e12).toFixed(2) + "T";
  if (n >= 1e9)  return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6)  return (n / 1e6).toFixed(0) + "M";
  return String(n);
}

function stageCls(s) {
  if (!s) return "";
  if (s.startsWith("2")) return "stage-up";
  if (s.startsWith("4")) return "stage-dn";
  if (s === "1B") return "stage-pre-up";
  if (s === "3B") return "stage-pre-dn";
  return "stage-neutral";
}

/**
 * data.js — all API fetch calls.
 * Exports a single load() function that returns all dashboard data.
 */

const API = {
  status:   "./data/status.json",
  stocks:   "./data/stocks.json",
  sectors:  "./data/sectors.json",
  rotation: "./data/rotation.json",
  robots:   "./data/robots.json",
};

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  return res.json();
}

/**
 * Load all data in parallel.
 * Returns { stocks, sectors, rotation: { current, tails }, status, robots }
 * Robots are optional — a missing/failed feed degrades to an empty payload.
 */
async function loadAll() {
  const robotsP = fetchJSON(API.robots).catch(() => ({ generated_at: null, robots: [] }));
  const [stocks, sectors, rotation, status, robots] = await Promise.all([
    fetchJSON(API.stocks),
    fetchJSON(API.sectors),
    fetchJSON(API.rotation),
    fetchJSON(API.status),
    robotsP,
  ]);
  return { stocks, sectors, rotation, status, robots };
}

// Lazily loaded bundle; cached in memory for the session.
let _detailBundle = null;

async function fetchStock(ticker) {
  if (!_detailBundle) _detailBundle = await fetchJSON("./data/stocks_detail.json");
  const data = _detailBundle[ticker.toUpperCase()];
  if (!data) throw new Error(`No detail for ${ticker}`);
  return data;
}

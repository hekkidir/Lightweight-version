/**
 * data.js — all API fetch calls.
 * Exports a single load() function that returns all dashboard data.
 */

const API = {
  status:   "/api/status",
  stocks:   "/api/stocks",
  sectors:  "/api/sectors",
  rotation: "/api/rotation",
  robots:   "/api/robots",
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

// Per-ticker indicator series (last `days` bars) for the stock detail modal.
async function fetchStock(ticker, days = 20) {
  return fetchJSON(`/api/stock/${encodeURIComponent(ticker)}?days=${days}`);
}

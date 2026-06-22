# Deployment

The app has two moving parts: a **data refresh** (`run.py pipeline`) that runs on
a schedule, and a **web server** (`server.asgi:app`) that serves the dashboard.
They share the data directory (`SCREENER_DATA_DIR`).

All deployment settings come from environment variables — see [.env.example](.env.example).

---

## Docker

```bash
docker build -t screener .

# Serve the dashboard (persist data on a named volume):
docker run -d --name screener -p 8000:8000 -v screener-data:/app/data screener


# First-time cold start (build data/ from tickers.csv):
docker run --rm -v screener-data:/app/data screener python run.py bootstrap
```

The volume `screener-data` is the database. Both the server container and the
refresh job mount it at `/app/data`.

## Scheduling the data refresh

The server does not refresh data on its own. Run the pipeline on a schedule.

**System cron** (host):
```cron
# Weekdays at 17:10 ET, after the close
10 17 * * 1-5  docker run --rm -v screener-data:/app/data screener python run.py pipeline
```

**Or systemd timer / your platform's scheduler** calling the same command.
Set `SCREENER_ALERT_WEBHOOK` so a failed refresh notifies you.

## Production server options

- Single worker is fine for a personal dashboard. Scale with workers:
  ```bash
  uvicorn server.asgi:app --host 0.0.0.0 --port 8000 --workers 2
  ```
- Put it behind a reverse proxy (Caddy/nginx) for TLS.
- Restrict access with `SCREENER_AUTH_TOKEN` (clients send `Authorization: Bearer <token>`)
  and/or `SCREENER_CORS_ORIGINS`. `/api/health` is always open for uptime checks.

## Health & monitoring

- `GET /api/health` → `200 {"status":"ok"}` or `503 {"status":"unhealthy","problems":[...]}`.
- `python run.py check` → same checks from the CLI (exit 1 on problems); good for CI/cron.

## Backup & restore

The data dir is the only state. Back it up by snapshotting the volume:
```bash
docker run --rm -v screener-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/screener-data.tgz -C /data .
```
Restore by extracting the tarball back into the volume. Losing it costs only a
`run.py bootstrap` (a full re-download), not real data.

---

## Making it a standalone repository

When you're ready to split this folder into its own repo (with history):

```bash
# from the parent project root
git subtree split --prefix="Lightweight version" -b screener-standalone
# then push that branch to a new empty repo, or:
git clone . /path/to/screener-repo --branch screener-standalone --single-branch
```

After that, `CLAUDE.md`, the tests, CI, and Docker all work unchanged — the
project was built to stand on its own (`python run.py bootstrap` from
`data/tickers.csv` + code alone).

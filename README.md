# AWB Status Dashboard

B2B courier status across **Smart Tracking** and **Platform (Instalogix)**.
Vue 3 frontend · Python FastAPI backend · MongoDB (Motor, async).

## How to start (no technical steps)

### On your computer (Windows)
1. Unzip the folder anywhere (Downloads is fine).
2. Double-click **`run.bat`**. A black window opens. Keep it open while you use the dashboard.
   - First time only: it installs what it needs (1–2 minutes). If Python isn't installed, it installs it.
   - It also puts an **AWB Dashboard** shortcut on your Desktop for next time.
3. Your browser opens the **Setup** page. For each database:
   - Click **Paste connection link** and paste the `MONGO_URI=...` line from your Smart Tracking
     Dashboard's `.env` (or type the server address, username and password).
   - Click **Test connection**, then pick the database and the collection from the lists.
   - Check the sample shipment looks right.
4. Click **Save and open dashboard**. Done. Next time, just double-click the Desktop shortcut.

Mac / Linux: same steps, but start it with `bash run.sh`.

### On the server (AWS / Linux)
1. Copy the zip to the server and unzip it.
2. Run: `sudo bash install-on-server.sh`
3. Open the address it prints (port **8010**, so it runs next to the Smart Tracking Dashboard on 8000)
   and complete the same Setup page. On a shared server, set a **Settings PIN** in step 3 of Setup.

It keeps running in the background and starts again by itself after a server reboot.
To update later: unzip the new version and run `sudo bash install-on-server.sh` again (settings are kept).
If the page doesn't open from outside, allow TCP port 8010 in the AWS Security Group.

### Status names and closed shipments
Dispatch status codes are shown as the names in **`Dispatch-status-Mapping.xlsx`** (column 1 = code,
column 2 = name). Edit it in Excel and restart to change names. AWBs whose current status is
**5, 13, 14, 15 or 16** are closed and skipped on both pages (on AWB Check, "Show them" reveals them).
Change the closed codes with `CLOSED_STATUS_CODES=5,13,14,15,16` in `.env`.

### Change settings later
Click **⚙ Settings** in the top bar.

### If something goes wrong
The black window (or `sudo journalctl -u awb-dashboard -n 50` on the server) shows a `[FAIL]` line
explaining what to fix. The Setup page also explains connection problems in plain words.

## Pages

**AWB Check** — paste one or many AWBs (new lines, commas or spaces). Each AWB is looked up in
Smart Tracking first, then Platform, and shown under two headers:

| Smart Tracking / Platform columns |
|---|
| Courier · Current Status · Status Datetime · Pickup Date · Last Track (with "x h ago") · Tracking |

Click a row to open both courier tracking blocks side by side (newest event first).
A **Sync** column flags *Status match / Mismatch / Only in one system / Not found*, with filter chips on top.
Export CSV gives both systems in one sheet. `/awb-check?awb=123` pre-fills and runs.

**Open Cases** — every shipment whose current status is not closed (closed list in `.env`).
Switch source between Smart Tracking and Platform. Shows total, aging buckets by hours since last
update (< 1 day … 5+ days), breakdown by status and by courier (click to filter), and a paginated
case list that also shows the *other* system's status with a ≠ marker on mismatch. CSV export streams
up to `EXPORT_MAX_ROWS`.

## Advanced settings — `.env` (optional)

```bash
cp .env.example .env   # or just use the Setup page
```

Set `ST_MONGO_URI / ST_DB_NAME / ST_COLLECTION` and the `PF_*` equivalents (blank `PF_MONGO_URI` reuses
the ST connection). Every `*_FIELDS` / `*_KEYS` value is a comma-separated list of candidate paths in
dot notation — the first non-empty value wins — so you can point it at Instalogix's field names without
code changes. For open-case filtering and grouping, the **first** path of `STATUS_FIELDS`,
`COURIER_FIELDS` and `CREATED_FIELDS` is used.

Dates are handled whether stored as Mongo dates, ISO / `dd-mm-yyyy` strings (assumed IST) or epoch
seconds/ms. Everything is shown in IST.

### Indexes (recommended on both collections)

```js
db.shipments.createIndex({ airwaybilno: 1 })                       // AWB check
db.shipments.createIndex({ created_at: -1, "status.dispatch_status": 1 }) // open cases
```

### Production load

Reads use `secondaryPreferred` when a replica set exists, AWB lookups go in `$in` batches of
`QUERY_BATCH_SIZE`, every aggregation starts with a status + `OPEN_LOOKBACK_DAYS` match and is capped
by `MONGO_MAX_TIME_MS`.

## Deploy on Vercel

This repo is set up as a **FastAPI** project on Vercel. The Vue frontend is built during deploy and served with the API.

1. Push the repo to GitHub/GitLab/Bitbucket and [import it in Vercel](https://vercel.com/new), **or** from the project root run:
   ```bash
   npx vercel
   ```
2. In **Project → Settings → Environment Variables**, set at least:
   - `ST_MONGO_URI`, `ST_DB_NAME`, `ST_COLLECTION`
   - `PF_DB_NAME`, `PF_COLLECTION` (leave `PF_MONGO_URI` blank to reuse the Smart Tracking URI)
   - Optional: any other keys from `.env.example` (`CLOSED_STATUS_CODES`, field mappings, `SETUP_PIN_HASH`, …)
3. Deploy. Open the deployment URL — if Mongo env vars are set, the dashboard loads; otherwise the Setup page can **test** connections but cannot write a `.env` (Vercel’s filesystem is read-only). Apply settings via env vars and redeploy.
4. Ensure your MongoDB Atlas (or other) network access allows Vercel egress (e.g. allow `0.0.0.0/0` or use Atlas private connectivity).

`vercel.json` sets a **60s** function `maxDuration` (Pro plans can raise this). Large CSV exports stream; keep `EXPORT_MAX_ROWS` reasonable for serverless.

## Local development (hot reload)

```bash
cd backend && python3 -m venv venv && . venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

cd frontend && npm install && npm run dev   # http://localhost:5173 (proxies /api to :8000)
```

Vercel-local alternative (builds like production): `npx vercel dev` from the repo root.

Tests (need any MongoDB; creates and drops `awbdash_test_*` databases only):

```bash
cd backend && TEST_MONGO_URI=mongodb://localhost:27017 python -m tests.smoke_test
```

## API

| Method | Path | |
|---|---|---|
| POST | `/api/awb/check` | `{"awbs": ["123", "456"]}` |
| POST | `/api/awb/export` | same body → CSV |
| GET | `/api/open-cases/summary` | `source, courier, status, date_from, date_to` |
| GET | `/api/open-cases/list` | + `aging, sort (stale/recent), page, page_size` |
| GET | `/api/open-cases/export` | same filters → streamed CSV |
| GET | `/api/open-cases/filters` | courier/status options (5-min cache) |
| GET | `/api/health` | DB connectivity |

Interactive docs at `/docs`. There is no login yet — keep it behind your VPN / nginx auth until one is added.

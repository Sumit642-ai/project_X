# Deploying to Vercel

Synthetic data only. The Vercel deploy runs the **demo**: the same data and clock as `make demo`.

## Why "API status: unreachable"

Locally, the Vite dev server proxies `/api/*` to the backend. A static Vercel build has no such
proxy, so `/api/health` returned the web page, not the API. Deep links such as `/queue` also
returned 404, because there was no SPA fallback. The backend could not start there either: it
expected a local Postgres, a second server for the mock CM platform, and a writable disk. The
fix is below.

## Option A: one project (recommended)

The repository root holds the frontend (static) and the API (a Python function) on one domain,
with no CORS and no settings to change.

1. In Vercel: **Add New → Project**, import the repository, and leave **Root Directory** as the
   repository root.
2. Framework preset: **Other**. `vercel.json` already sets the install command, the build
   command (`npm --prefix frontend run build`) and the output directory (`frontend/dist`).
3. Environment variables (Settings → Environment Variables):
   - `JWT_SECRET`: any random string of 32 or more characters (recommended; there is a demo default).
   - `ANTHROPIC_API_KEY`: optional, for live AI note drafts. Without it the Live pane says
     "AI draft unavailable", by design.
4. Deploy, then open `https://<project>.vercel.app/demo/old-way` (or `/login`). The sign-in page
   should say **API status: ok**.

How it works:

- **Static files and routes:** `frontend/dist` is served as static files, `/api/*` is rewritten to `api/index.py`, and every other path falls back to `index.html`.
- **The function:** `api/index.py` loads `backend/vercel_app.py`. On a cold start that module:
  - copies the committed demo bundle (`backend/deploy/`: SQLite database, synthetic feed files, demo state, seed files) to `/tmp`;
  - runs the mock CM platform inside the same function;
  - turns demo mode on with the clock frozen at Mon 9 Nov 2026 08:00 New York time.

## Option B: two projects (frontend and backend separately)

**Backend project**

- **Root Directory:** `backend`.
- **Config:** `backend/vercel.json` routes every path to `backend/api/index.py`, which accepts paths with or without `/api`.
- **Environment:**
  - `JWT_SECRET` (as above).
  - `CORS_ORIGINS` = `["https://<your-frontend>.vercel.app"]` (a JSON list).
  - Optionally `CORS_ORIGIN_REGEX` = `https://<your-frontend>-.*\.vercel\.app`, for preview deploys.
- **Check:** `https://<backend>.vercel.app/health` returns `{"status":"ok"}`.

**Frontend project**

- **Root Directory:** `frontend`.
- **Framework:** Vite.
- **Environment:** `VITE_API_BASE_URL` = `https://<backend>.vercel.app`. It is read at build time, so redeploy after changing it.
- **SPA fallback:** `frontend/vercel.json` sends deep links to `index.html`.

## Updating the demo data

The bundle is committed, so a deploy needs no build step for data. After changing the generator, the pipeline or the migrations:

```sh
make vercel-bundle   # rebuilds backend/deploy/ (about 15 s, 2.8 MB), then commit it
```

## Limits of the Vercel demo

- **State per instance:** demo state lives in `/tmp` on each function instance. A cold start (after idle time or a new deploy) is a fresh demo at Monday 08:00, as after **Reset demo**. Two instances running at once would each have their own state. Vercel normally reuses one warm instance for a single presenter, but for a shared, persistent environment use a managed Postgres and a long-running backend (see [LIMITATIONS.md](LIMITATIONS.md)).
- **Clock steps:** advancing the clock re-runs the pipeline in the request, which takes a few seconds. `maxDuration` is 60 s.
- **No real data:** synthetic data only. Do not put real PHI into this deployment.

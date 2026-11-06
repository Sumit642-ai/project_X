# CaseCompass

MVP case-management workbench for US health-plan nurse case managers. **Synthetic data only.** Product rules live in [CLAUDE.md](CLAUDE.md).

| Path        | What                                                                 |
|-------------|----------------------------------------------------------------------|
| `backend/`  | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, pytest, ruff, mypy       |
| `frontend/` | React + TypeScript + Vite + Tailwind, Vitest                         |
| `e2e/`      | Playwright                                                           |
| `data/`     | Synthetic raw files (generated, gitignored); `data/seed/` is committed |
| `docs/`     | Architecture notes                                                   |

## Prerequisites

- Docker with Compose v2
- Python 3.12
- Node 20+
- GNU make (on Windows: run from Git Bash; `mingw32-make` works as `make`)

## Setup

```sh
cp .env.example .env      # optional, make up does this if .env is missing
make install              # backend venv, npm deps, Playwright chromium
make up                   # Postgres + backend on http://localhost:8000
curl http://localhost:8000/health   # {"status":"ok"}
cd frontend && npm run dev          # http://localhost:5173 shows "ok"
```

Without Python 3.12 on the PATH, pick another interpreter for the local venv, e.g.
`make install PYTHON="py -3.13"`. The container always uses 3.12.

## Everyday commands

```sh
make test    # backend pytest + frontend vitest (no database needed)
make lint    # ruff, mypy, tsc
make e2e     # Playwright, needs make up
make seed    # build the demo DB: ingest, identity, facts, users, scores
make demo    # demo mode: rebuild data/demo, start API + mock CM + frontend (see docs/DEMO.md)
make down
```

## Notes

- The frontend calls `/api/health`; the Vite dev server proxies `/api/*` to `VITE_API_PROXY_TARGET` (default `http://localhost:8000`).
- The backend container runs `alembic upgrade head` on start.
- AI note draft (Live pane): set `ANTHROPIC_API_KEY` (and optionally `AI_DRAFT_MODEL`, default `claude-opus-5-5`) to use it. Without a key it says "AI draft unavailable". The live test is opt-in: `cd backend && .venv/Scripts/python -m pytest tests/ai_draft/test_live.py --live`.
- Business logic gets the time from `app.core.clock.Clock`. `CLOCK_MODE=fixed` pins it to 2026-11-09T08:00 America/New_York. Ruff fails the build on `datetime.now()` / `date.today()` outside `app/core/clock.py`.

## Demo API

After `make seed`, open http://localhost:8000/docs. Sign in with `POST /auth/login {"username": "maria"}`
(also devon, alma, priya, janet = supervisor, sam = call agent) and use the token as a Bearer header.

# CaseCompass

MVP case-management workbench for US health-plan nurse case managers: ranks members to call, shows a trustworthy member view, and lets the nurse confirm documentation instead of typing it. Synthetic data only.

## Product rules

- Synthetic data only. IDs start with SYN-, phones are 555-01xx. Never add real PHI.
- Every stored value is a Fact with source_system, source_record_id, event_date, loaded_at, confidence and status (raw | member_reported | cm_confirmed).
- Never auto-resolve a medication or diagnosis conflict. Never auto-merge identities below 0.90 confidence.
- Missing data is shown as UNKNOWN, never as "none" or 0.
- AI may only draft text. It never decides doses, coverage, merges or consent.
- Part 2 substance-use program records are masked unless valid consent exists; every reveal is audited.
- No SMS without TCPA consent. Hard block, no override.
- The reference clock for tests and demo is 2026-11-09T08:00 America/New_York, injected through a Clock service; never call datetime.now() directly in business logic.
- Every rule and score must be explainable: store the input fact IDs.
- Write tests for every rule. Run make test before saying a task is done.
- Ingestion, normalisation, identity matching and conflict detection SIMULATE the HiLabs data layer (out of scope per the caselet). CaseCompass's own scope is trust display, signals, scoring, next best action and the clinician workflow. UI and docs must say 'flagged by data layer' for duplicates and conflicts.

## Terms

- The user-facing name is "Next best action (suggested)"; the API field is next_best_action.

## Commands

Run from the repo root (on Windows, from Git Bash with GNU make).

- `make install` - create backend venv (Python 3.12) and install frontend/e2e dependencies
- `make up` - start Postgres 16 + backend via docker compose (creates .env from .env.example if missing)
- `make down` - stop containers
- `make test` - backend pytest + frontend vitest
- `make lint` - ruff check, ruff format --check, mypy, frontend tsc
- `make seed` - build the demo database from data/raw: ingest, identity, facts, users, signals and scores
- `make migrate` - alembic upgrade head in the backend container
- `make e2e` - Playwright tests (requires `make up`)
- `make synth` - regenerate the synthetic raw feeds in data/raw (fixed seed, byte-identical)
- `make ingest` - land, validate and stage everything in data/raw (migrates first)
- `make demo` - demo mode: drop and rebuild the SQLite demo DB in data/demo, freeze the clock, start API (:8000), mock CM (:8200) and frontend. Script: docs/DEMO.md

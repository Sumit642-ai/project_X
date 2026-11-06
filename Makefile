# CaseCompass developer commands. On Windows run from Git Bash (GNU make, e.g. mingw32-make).

ifeq ($(OS),Windows_NT)
PYTHON ?= py -3.12
VENV_BIN := .venv/Scripts
else
PYTHON ?= python3.12
VENV_BIN := .venv/bin
endif

COMPOSE := docker compose

.PHONY: help install up down logs test test-backend test-frontend lint seed migrate e2e synth ingest demo

help:
	@echo "make install  - create backend venv and install frontend/e2e deps"
	@echo "make up       - start Postgres + backend (docker compose)"
	@echo "make down     - stop containers"
	@echo "make test     - backend pytest + frontend vitest"
	@echo "make lint     - ruff, mypy, tsc"
	@echo "make seed     - build the demo database: ingest, match, facts, users, scores"
	@echo "make migrate  - run alembic upgrade head in the backend container"
	@echo "make e2e      - Playwright tests (needs make up)"
	@echo "make synth    - regenerate synthetic raw feeds in data/raw (fixed seed)"
	@echo "make ingest   - land, validate and stage everything in data/raw"
	@echo "make demo     - rebuild the demo DB (SQLite, data/demo) and start API, mock CM, frontend"

.env:
	cp .env.example .env

install:
	cd backend && $(PYTHON) -m venv .venv && $(VENV_BIN)/python -m pip install -e ".[dev]"
	cd frontend && npm install
	cd e2e && npm install && npx playwright install chromium

up: .env
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

test: test-backend test-frontend

test-backend:
	cd backend && $(VENV_BIN)/python -m pytest

test-frontend:
	cd frontend && npm test

lint:
	cd backend && $(VENV_BIN)/ruff check . && $(VENV_BIN)/ruff format --check . && $(VENV_BIN)/mypy
	cd frontend && npm run typecheck

seed:
	cd backend && $(VENV_BIN)/alembic upgrade head && $(VENV_BIN)/python -m app.seed

migrate:
	$(COMPOSE) exec backend alembic upgrade head

e2e:
	cd e2e && npx playwright test

synth:
	cd backend && $(VENV_BIN)/python -m app.synth

ingest:
	cd backend && $(VENV_BIN)/alembic upgrade head && $(VENV_BIN)/python -m app.datalayer_mock.ingest

demo:
	node scripts/demo.mjs

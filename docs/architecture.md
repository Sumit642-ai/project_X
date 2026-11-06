# Architecture notes

## Shape

```
browser ── Vite dev server (:5173) ──/api/*──▶ FastAPI (:8000) ──▶ Postgres 16
```

- **backend/app/main.py** - `create_app()` factory; routers live in `app/api/`.
- **backend/app/core/config.py** - `Settings` (pydantic-settings) from env vars and `.env`; `get_settings()` is cached.
- **backend/app/core/clock.py** - `Clock` protocol, `FixedClock` (reference instant 2026-11-09T08:00 America/New_York) and `SystemClock`. `get_clock()` is the FastAPI dependency. This is the only module allowed to read the wall clock (ruff `TID251`).
- **backend/app/db/** - `Base` (declarative), engine/session factory created lazily, `get_db()` dependency.
- **backend/alembic/** - migrations; `env.py` takes the URL from `Settings` unless `sqlalchemy.url` is set explicitly (tests use SQLite this way).

## Testing

- Backend tests don't need Postgres: they use the app factory with `TestClient` and SQLite for session/migration smoke tests.
- Frontend tests stub `fetch`; e2e tests hit the real stack.

## Data pipeline

> **Scope.** Ingestion, normalisation, identity matching and conflict detection *simulate the HiLabs
> data layer* (out of scope per the caselet) and live in `app/datalayer_mock/`. CaseCompass's own
> scope is trust display, signals, scoring, next best action (suggested) and the clinician workflow.
> Duplicates and conflicts are always shown as **"flagged by data layer"**.

```
app.synth -> data/raw -> app.datalayer_mock.ingest (landing, contracts, stg_*) -> app.datalayer_mock.normalise (norm_*)
                                                                -> app.datalayer_mock.identity (members, member_links)
```

- **synth / ingest:** see [data-feeds.md](data-feeds.md).
- **normalise:**
  - Local terminology CSVs in `app/datalayer_mock/normalise/terminology/` (ICD-10 with condition groups, NDC to ingredient, strength and drug class, LOINC). No RxCUIs: they could not be verified offline.
  - `run_normalisation` rebuilds `norm_diagnoses`, `norm_medications` and `norm_labs` from active loads, keeping the staging lineage on each row.
  - Unmapped codes stay as rows with `mapped = false` and are counted in `unmapped_codes`.
  - C-CDA medications have no NDC, so they map by drug name, and the strength comes from the document.
- **identity:**
  - **Golden records:** `members` holds one row per plan ID with active eligibility on the clock's date.
  - **Links:** `member_links` attaches source records (eligibility rows, hospital patient IDs from ADT and C-CDA, plan-keyed feeds) to members.
  - **Exact plan ID:** gives confidence 1.0 and `auto_linked`.
  - **Weighted scorer:** used for everything else. Weights are first 0.22, last 0.18, DOB 0.32, sex 0.04, address 0.10, phone 0.14.
    - Comparison levels are stored per field in `field_scores`. A missing field contributes 0.
    - A score of at least 0.90 is `auto_linked` only when it is the sole candidate. 0.70 to 0.89 is `needs_review`. Below 0.70 there is no link.
  - **Pairs:** a pair with any existing link row is never re-scored, so rejections stick.
  - **Decisions:** `confirm_link`, `reject_link` and `unmerge` need a named human user and write `link_audit` rows. Links are pointers, so unmerging leaves both histories intact.
  - **Metric:** `record_daily_metrics` stores `unlinked_adt_events` per day. Events in the review queue count as unlinked.

- **facts** (`refresh_facts` = build -> projections -> conflicts):
  - **Append-only:** `facts` keeps full lineage (load_id, source_row, link_id). The only permitted UPDATE sets `superseded_by` once, enforced by the ORM and by a database trigger (Postgres and SQLite). A changed source value becomes a new Fact.
  - **Identity gating:** Facts are built only from records behind an `auto_linked` or `confirmed` link. Raymond's St Brigid medication list appears only after a nurse confirms SYN-001-H. An unmerge hides those Facts without deleting them.
  - **Current-state tables:** `contact_points`, `consents` and `documents` are rebuilt from Facts and HIE request staging.
  - **Contact confidence:** recency x source reliability x outcome. The factor tables in `app/facts/contacts.py` are calibrated to annex Sheet 8. Disconnected numbers are capped at 0.09, and third parties without authorisation are never callable.
  - **Conflicts:** a hospital medication list is compared with pharmacy fills around the document date (dose and presence). Diagnoses conflict only when sources use different codes in the same condition group. Only humans move a conflict to `sent_to_prescriber` or `resolved`.
  - **Freshness:** from `event_date`. Green is under 7 days, amber 7 to 30, red over 30, and grey means never received.
  - **UNKNOWN:** `get_fact_or_unknown` returns an `Unknown` with a reason, e.g. "practice not connected" or "claims loaded through 2026-09-25".
  - **Part 2:** records are masked in `member_snapshot`. An audited reveal is still to be built.

- **signals** (`evaluate_signals`):
  - **Rules:** 16 rule classes in `app/signals/rules.py`. Each has rule_id, version, owner, severity and description, and declares whether it is a lever and what kind of deadline it sets.
  - **Signals:** each signal cites its input Fact IDs, keeps its insight text to 12 words or fewer, and stores deadlines in UTC alongside the member's time zone.
  - **Calendar:** weekdays minus `BUSINESS_HOLIDAYS`.
  - **Kill switch and counts:** `DISABLED_RULES` switches rules off. Counts are stored per rule per day in `daily_metrics` as `signals.<RULE_ID>`.
- **scoring** (`score_members`, `explain`):
  - **Formula:** Score = 40R + 30U + 20M + 10A.
  - **Inputs:**
    - R: the plan risk score, or the cohort median with a VERIFY flag.
    - U: max of the deadline urgency and the clinical urgency. Deadlines are member-contact rule deadlines plus open care gaps; UM-owned deadlines are excluded. Clinical urgency is red 1.0, amber 0.6, info 0.3.
    - M: the best lever, x0.75 when its key input is over 30 days old.
    - A: the best authorised, callable contact.
  - **Storage:** every score is stored in `member_scores` with its inputs, fact IDs and signal IDs. `backtest()` compares our daily top 12 with arrival order and risk-only order on readmissions.

- **api** (FastAPI, docs at `/docs`):
  - **Login:** demo-grade, seeded users only (maria, devon, alma, priya, janet, sam), HS256 JWT. Token expiry is checked against the Clock, and login is disabled outside local/test/demo.
  - **Access:** every endpoint checks the user's role; member endpoints also check the active assignment.
  - **Decision logic:** in `app/workbench/` (access, views, actions, feeds); every action writes `audit_events`.
  - **Part 2:** a reveal needs a valid consent. The notes are returned only in the reveal response, and the 360 stays masked.
  - **Reassignment:** checks licensure (hard 422) and language (422 unless an audited `override_reason` is given).
  - **Stale feeds:** load-age and data-age thresholds per feed and stream, in `app/workbench/feeds.py`.

- **encounters** (`app/encounters/`, UI `pages/Call/`): simulated dialer (`data/seed/dial_script.json`), channel ladder, guards, a 40-field assessment template with prefill status and source fact IDs, wrap-up tasks that mark signals handled, inbound routing, and the crisis protocol.
- **writeback** (`app/writeback/`, mock system of record in `backend/mock_cm/`):
  - Saves carry an idempotency key (encounter + payload hash) and go through an outbox.
  - Status moves saved -> syncing -> synced. Retries use exponential backoff on the Clock; after 2 hours a supervisor is alerted. The worker is `python -m app.writeback.worker`, and `POST /admin/writeback/run` retries on demand.
  - Writes are conditional on the CM record version the nurse opened. On a mismatch the API returns 409 with both versions, and nothing is written.
  - Field mapping lives in `mapping.yaml`, with a round-trip test per field.
  - A successful sync writes `cm_confirmed` Facts and closes the conflicts the nurse resolved on the call. Source Facts are never deleted.
- **consent** (`app/consent/policy.py`):
  - The only place consent is decided: `can_call`, `can_sms`, `can_reveal_part2`, `can_contact_third_party`, plus masking.
  - A test greps `app/` for direct checks anywhere else.
  - Part 2 tagging: a program on the allowlist gives `part2`; any other program gives `unverified`, masked and not revealable.
- **audit:** `audit_events` is append-only, enforced by a database trigger (and a revoke from PUBLIC on Postgres). `GET /audit?member_id=` (supervisor, `format=csv`).
- **minimum necessary:** call agents get only `/members/{id}/contact-card` (identity, reach ladder, a non-clinical "why we called").
- **ai_draft** (`app/ai_draft/`, UI `pages/Call/AiDraftPanel.tsx`): AI note draft in the Live pane. Rules-based pre-fill stays the main documentation saving; the draft only fills the free-text note.
  - **Transcript:** no live speech-to-text in the MVP. `data/seed/transcripts/{member_id}.txt` (numbered `NURSE:`/`MEMBER:`/`CAREGIVER:` turns) stands in for the transcription feed. It needs a verified identity and transcription consent (`policy.can_transcribe`).
  - **Model:** official Anthropic SDK. `AI_DRAFT_MODEL` (default `claude-opus-5-5`) and `ANTHROPIC_API_KEY` come from the environment. The 20 s timeout has no retries. Structured outputs (JSON schema) are used, and the server-side refusal fallback is on. Any failure returns `available: false`, and the UI says "AI draft unavailable".
  - **Prompt:** the transcript goes in the user turn inside `<transcript>` tags, and any closing tag inside it is defused. The system prompt says the transcript is data, not instructions. It also rules out diagnoses, doses and coverage statements.
  - **Validation:** every sentence must cite existing turns, otherwise it is UNSUPPORTED. Dose, diagnosis and coverage wording is BLOCKED (the backstop to the prompt). Medication names found in neither the transcript nor the member's visible medication Facts are flagged. Only supported note sentences can be inserted.
  - **Write-back guard:** `mapping.yaml` marks only `note.body` as `ai: allowed`. `encode_section` refuses AI text for every other field: `AiDrafted` values, plus any stored value containing a sentence from the encounter's drafts. The save then returns 422 and nothing is sent.
  - **Flag:** `DEMO_MODE=true` turns it on for every pod; otherwise it is on only for pods listed in `AI_DRAFT_PODS` (`users.pod`).
  - **Audit and metrics:**
    - `ai_logs` (append-only by trigger) stores every prompt and output with encounter_id.
    - `ai_guardrail_metrics` stores per encounter: unsupported count, word-level normalised edit distance between the draft and the saved note (major edit if > 0.3), and seconds from draft to save.
    - `GET /admin/ai-draft/metrics` shows the major-edit ratio per pod.
  - **Live test:** `pytest tests/ai_draft/test_live.py --live` runs Raymond's transcript against the real API. It is skipped by default.
- **demo** (`app/demo/`, `scripts/demo.mjs`, UI `/demo-admin`, `/demo/old-way`; script in [DEMO.md](DEMO.md)). Only when `DEMO_MODE=true`.
  - **Build:** `make demo` builds a SQLite demo database in `data/demo/` in about 15 s. The same build twice gives a byte-identical `queue_snapshot.json`. The build keeps `pristine.db` for Reset, and the e2e run uses the same build.
  - **Clock:** frozen at the reference instant in `data/demo/demo_state.json`, which `get_clock()` reads in demo mode. Advancing delivers the scripted rows in `data/seed/demo/intraday.json` as new snapshot files through the data-layer ingest. Then it re-runs identity, normalisation, facts, signals and scores, and closes tasks that the new data answers (`resolve_tasks_by_data`).
  - **Task resolution:** each rule says what can answer it (`RESOLVED_BY`): a fill of the same drug, or a coverage decision. The task stores the resolving fact IDs. Tasks from any other rule are closed by a person.
  - **Operator toggles:**
    - **Feed pause:** makes the feed stale in `feeds.py`; deliveries wait until it resumes.
    - **CM platform:** goes down through the mock CM's admin API. Restoring retries every waiting save at once (`sync_due(now_all=True)`).
    - **Kayla's consent:** expires or is restored as a new consent snapshot. The policy code is unchanged.
    - **Bad file, unknown NDC:** go through the normal quarantine path and the unmapped report (`GET /admin/unmapped-codes`).
    - **AI time-out:** a model that raises a timeout.
  - **Audit:** every action is audited as `demo_*`.
  - **Manual discharge:** `POST /members/{id}/discharges` records a member-reported discharge while ADT is down (the "Add discharge" button). It also works outside demo mode.

## Planned (not built yet)

- Readmissions in the synthetic background (the back-test currently has none to measure).

- CLI or API entry points for normalisation, matching and facts. For now they are library functions exercised by the tests.
- Annual freshness thresholds for SDOH screens, if wanted: under the current bands, Raymond's 8-month HRA is red where annex Sheet 9 says amber.

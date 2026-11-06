# CaseCompass architecture

Synthetic data only. Product rules are in [CLAUDE.md](../CLAUDE.md), and where each rule is
enforced is in [RULES_AUDIT.md](RULES_AUDIT.md). What is mocked, and what a pilot needs, is in
[LIMITATIONS.md](LIMITATIONS.md). The demo script is [DEMO.md](DEMO.md).

## Layers

```
browser (React 19, Vite)  --/api/*-->  FastAPI app (backend/app)  -->  Postgres 16 (SQLite in tests and demo)
                                            |
                                            +--> mock CM platform (backend/mock_cm): the system of record for write-back
                                            +--> Anthropic API (AI note draft only; optional)
```

| Layer | Where | Owns |
|---|---|---|
| Simulated HiLabs data layer | `app/datalayer_mock/` (ingest, normalise, identity), `app/facts/conflicts.py` | Landing and validating feed files, staging, terminology mapping, golden member records and links, conflict detection. **Out of CaseCompass scope.** It *simulates the HiLabs data layer*, and its output is labelled "flagged by data layer". |
| Facts | `app/facts/` | Append-only Facts with lineage, current-state projections (contacts, consents, documents), freshness, UNKNOWN. |
| Signals and scoring | `app/signals/`, `app/scoring/` | 16 explainable rules; score = 40R + 30U + 20M + 10A, tiers, rank. Every signal and score stores its input fact IDs. |
| Consent policy | `app/consent/policy.py` | Every call, SMS, third-party, transcription and Part 2 decision, in one module. |
| Workbench and encounters | `app/workbench/`, `app/encounters/` | Queue, member 360, actions, audit, the call workflow, tasks. |
| Write-back | `app/writeback/` | Outbox, idempotent conditional writes to the CM platform, the field mapping (including the AI guard). |
| AI draft | `app/ai_draft/` | Note draft from the transcript: validation, logs, guardrail metrics. Text only. |
| Platform | `app/core/` (settings, clock, logging), `app/api/` (routes, auth, rate limit), `app/observability.py` | The injected Clock, structured masked logs, `/metrics`. |
| Demo | `app/demo/`, `scripts/demo.mjs` | `make demo`, the movable clock and the operator toggles (DEMO_MODE only). |

## Data flow

1. **Nightly (or `make seed` / `make demo`):**
   - Synthetic feed files are written to `data/raw/`. The ingest step lands each file immutably, validates it against its contract, and stages it (`stg_*`), or quarantines it with the previous load still active.
   - Normalisation and identity matching run next.
   - Facts are built only behind auto-linked or confirmed links. Projections and conflicts are rebuilt.
   - Signals are evaluated per member, then scores and ranks are stored per day.
   - `make perf` times this pipeline with 5,000 background members.
2. **Daytime, read path:**
   - `/queue` reads the stored day's `member_scores` and signals.
   - `/members/{id}/360` builds a snapshot from Facts, with Part 2 masked and missing data shown as UNKNOWN with a reason.
3. **Daytime, call path:**
   - Dial (simulated), then verify identity, then the live notes and the optional AI draft.
   - Wrap-up confirms fields: high-risk ones one by one. Tasks are created from signals (`signal_handles`), and the member is re-scored.
   - Save writes to the outbox, then conditionally to the CM platform. On sync, confirmed fields become `cm_confirmed` Facts and resolved conflicts close.
4. **Intraday data (demo clock, or a real feed):**
   - New files go through the same ingest, then the refresh runs.
   - `resolve_tasks_by_data` closes tasks that a matching Fact answers, such as a fill of the same drug or a coverage decision.

## Data model (main tables)

| Table | Holds | Notes |
|---|---|---|
| `loads`, `load_errors`, `stg_*` | Every file received, with its status (PASS or QUARANTINE), row errors and staged rows | Landing files are read-only. |
| `members`, `member_links`, `link_audit` | Golden records, source-record links with confidence and field scores, every human decision | Below 0.90 a person decides. |
| `norm_*`, `unmapped_codes` | Mapped diagnoses, medications and labs; codes that did not map | Raw values are kept. |
| `facts` | Every stored value: type, key, value, source_system, source_record_id, event_date, loaded_at, confidence, status (raw, member_reported, cm_confirmed), sensitivity | Append-only (ORM and DB triggers); only `superseded_by` may be set, once. |
| `conflicts`, `conflict_facts` | Disagreements between sources, with their Facts | Only people resolve them; medication conflicts need the prescriber. |
| `contact_points`, `consents`, `documents` | Current-state projections rebuilt from Facts | Consent validity is decided only in `policy.py`. |
| `signals`, `member_scores`, `daily_metrics` | Per-day signals (with input fact IDs and deadlines) and scores (with R, U, M, A inputs) | Explainable by construction. |
| `users`, `assignments`, `snoozes`, `audit_events` | Seeded users (with pod), caseloads, deferrals, every view and action | `audit_events` is append-only (trigger; REVOKE on Postgres). |
| `encounters`, `encounter_fields`, `tasks`, `signal_handles`, `notifications` | Calls, the 40-field template state, tasks (with resolution by data), handled signals | |
| `writeback_outbox` | Each save: idempotency key, payload, base version, attempts, status | Status moves saved, then syncing, then synced (or alerted). |
| `ai_logs`, `ai_drafts`, `ai_guardrail_metrics` | Every prompt and output, validated drafts, per-encounter edit and support metrics | `ai_logs` is append-only. |

## Failure handling

| Failure | What happens | Where |
|---|---|---|
| A feed file is malformed, or its layout changed | Quarantined with the reason. The previous good load stays active and nothing reaches staging. | `datalayer_mock/ingest/pipeline.py` |
| A feed is late or paused | The stream is marked stale. The queue shows a banner (red for ADT), and the 360 offers **Add discharge** while ADT is down. | `workbench/feeds.py`, `POST /members/{id}/discharges` |
| A code does not map | Kept by its raw name and listed in `unmapped_codes` (`GET /admin/unmapped-codes`). | `datalayer_mock/normalise/run.py` |
| An identity match is uncertain | 0.70 to 0.89 waits for a person (banner, and charting is paused). Below 0.70, no link. | `datalayer_mock/identity` |
| Sources disagree | A conflict card, flagged by data layer. Never auto-resolved; medication conflicts need the prescriber's decision. | `facts/conflicts.py`, `writeback/service.py` |
| The CM platform is down | The save goes to the outbox ("Saved here, syncing to record") and retries with exponential backoff. After 2 hours a supervisor is alerted. The idempotency key prevents duplicates. | `writeback/service.py`, `writeback/worker.py` |
| The CM record changed since it was opened | 409 with both versions. Nothing is written until the nurse chooses. | `writeback/service.py` |
| The AI draft fails or times out | `available: false`, "AI draft unavailable", and the nurse writes as normal. Logged in `ai_logs`. | `ai_draft/client.py`, `ai_draft/service.py` |
| AI text reaches a non-note field | The mapping refuses it (422) and nothing is sent. | `writeback/mapping.py` |
| Consent missing or expired | Hard block in `policy.py` (403/409), with no override path for SMS. | `consent/policy.py` |
| Too many sign-in attempts | 429 with Retry-After, per client address. | `api/ratelimit.py` |

## Security and observability

- **Auth:** demo-grade sign-in for seeded users only (local, test and demo environments). The HS256 JWT expiry is checked against the Clock. Sign-in is rate limited. Every endpoint checks the role, and member endpoints also check the assignment.
- **CORS:** only the frontend origins in `CORS_ORIGINS`.
- **Logs:** structured JSON, one line per request with the route template and member ID, never the raw path or query. A log-record factory masks phone numbers, emails, query values, and member and representative names in every log line, whatever logger it comes from. Uvicorn's access log is off.
- **Metrics:** `/metrics` (Prometheus text) and `/admin/metrics` (JSON, supervisors; the Metrics page) report feed ages, signals per rule, the override rate, the AI unsupported-sentence rate and write-back lag. Counts only, no member data.
- **Audit:** `audit_events` and `ai_logs` are append-only, enforced by database triggers.

## Testing

- **Backend:** `make test` runs pytest on SQLite, with no Postgres needed. `make coverage` reports line coverage, 85% or more on signals, scoring, consent, writeback and identity. `tests/test_golden.py` asserts every blueprint number.
- **Frontend:** vitest with a stubbed `fetch`.
- **e2e:** `make e2e` runs Playwright against the demo build: Lighthouse on the Queue, 360 and Call pages, a keyboard-only Raymond call, the 15-minute demo script, and the workbench flows.
- **Other targets:** `make perf` (5,000 members), `make audit` (pip-audit, npm audit), and the opt-in `pytest --live` (real Anthropic API).

## Component reference

### Data pipeline (simulated HiLabs data layer)

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
  - **Freshness** (display only, from `event_date`, by kind as in annex Sheet 9): screens are green under 6 months, amber 6 to 8, red from 9; open care gaps with a deadline ahead are green; services are green to 60 days, amber to 90; everything else is green under 7 days, amber 7 to 30, red over 30. Grey means never received.
  - **UNKNOWN:** `get_fact_or_unknown` returns an `Unknown` with a reason, e.g. "practice not connected" or "claims loaded through 2026-09-25".
  - **Part 2:** records are masked in `member_snapshot`; revealing needs a valid consent (`policy.can_reveal_part2`) and is audited.

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

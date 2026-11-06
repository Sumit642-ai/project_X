# Limitations: what is mocked, and what a real pilot needs

CaseCompass is an MVP on **synthetic data only** (IDs start with SYN-, phones are 555-01xx). It
shows the workflow end to end, but several parts are stand-ins.

## What is mocked

| Part | Stand-in | Where | What it does not do |
|---|---|---|---|
| **The HiLabs data layer** (ingestion, normalisation, identity, conflict detection) | A simulation, labelled "flagged by data layer" in the UI | `backend/app/datalayer_mock/`, `app/facts/conflicts.py` | No real feed contracts or SLAs; terminology is a small local table (no RxNorm, no full ICD-10/LOINC); identity matching is a simple weighted scorer. |
| **Source feeds** (eligibility 834, claims 837, PBM/NCPDP, ADT, C-CDA, UM, labs, care gaps, Medicaid LTSS, Part 2 program notes) | Deterministic synthetic files from `make synth` | `backend/app/synth/`, `data/raw/` | No real volumes, lags or edge cases beyond the 17 planted imperfections. `make perf` clones members to 5,000 for load testing. |
| **HIE** (hospital ADT, discharge summaries, med lists) | Synthetic HL7 v2 and C-CDA files, plus a "request" table | `data/raw/adt`, `data/raw/documents` | No real HIE query or subscription, no MPI. A "re-query" only records the request. |
| **Dialer and SMS** | A script of outcomes per number (`data/seed/dial_script.json`) | `app/encounters/service.py` | No call or message is ever placed. SMS is simulated, after the consent checks. |
| **Transcription** | Synthetic transcripts per member (`data/seed/transcripts/`) | `app/ai_draft/transcript.py` | No speech-to-text. The AI draft uses the real Anthropic API when a key is set. |
| **CM platform** (system of record) | A small FastAPI app with versioned records and failure modes (down, slow, conflict) | `backend/mock_cm/` | No real CM vendor API, field codes or authentication. `mapping.yaml` is where real field codes would go. |
| **Sign-in** | Demo users chosen from a list; HS256 JWT | `app/api/auth.py` | No SSO, MFA, password or account lifecycle. `APP_ENV` accepts only local, test and demo, and sign-in is refused otherwise. |
| **Clock** | Frozen at 2026-11-09 08:00 America/New_York (movable in demo mode) | `app/core/clock.py`, `app/demo/` | `CLOCK_MODE=system` uses wall time, but the data is fixed around the reference date. |
| **Database in demo and tests** | SQLite (Postgres 16 via docker compose for `make up`) | `app/db/` | Postgres-specific triggers and REVOKEs are written but have not been run here (no Docker on the build machine). |

## What a real pilot needs

1. **Agreements and compliance**
   - **Business Associate Agreements:** with the plan, the hosting provider, the LLM provider (or no LLM), and every vendor that touches PHI.
   - **42 CFR Part 2:** a review of the program allowlist and the consent model (`PART2_PROGRAM_ALLOWLIST`), and redisclosure handling signed off by privacy and legal.
   - **TCPA and state rules:** for calls and texts. Consent capture flows from the real CM platform.
   - **Assessments:** a HIPAA security risk assessment and a privacy impact assessment.
2. **Real data**
   - **Production feeds:** each with a data contract, an SLA and an owner, delivered by the HiLabs data layer (replacing `datalayer_mock`).
   - **Terminology:** full RxNorm/NDC, ICD-10-CM and LOINC, with versioning.
   - **MPI and HIE:** a real master patient index or HIE identity service, and HIE connectivity (ADT subscriptions, document query).
   - **Practice connections:** follow-up appointments are UNKNOWN today because "practice not connected".
3. **Identity and access**
   - **SSO:** OIDC or SAML through the plan's identity provider, plus MFA and role mapping from directory groups (cm, supervisor, call_agent).
   - **Sessions:** shorter token lifetimes, refresh tokens and revocation.
   - **Licensure:** checks against real licensure data, not seed values.
4. **Systems of record**
   - **CM platform integration:** the vendor API, real field codes in `mapping.yaml`, and their idempotency and versioning semantics.
   - **Telephony:** a real dialer and SMS provider, with recorded consent and opt-out handling.
5. **Clinical governance**
   - **Sign-off:** clinical sign-off for the 16 signal rules and their thresholds, the score weights, the next best action (suggested) wording, and the 40-field template.
   - **Review:** a process for rule changes (rule IDs and versions are stored with every signal) and regular review of the override rate and the AI major-edit rate.
   - **AI draft rollout:** pod by pod (`AI_DRAFT_PODS`), with the guardrail metrics watched.
6. **Operations**
   - **Hosting:** managed Postgres with backups, encryption at rest and point-in-time recovery; secrets in a vault, not `.env`.
   - **Monitoring:** scrape `/metrics`, ship the masked JSON logs to the SIEM, and alert on stale feeds, write-back lag and alerted saves.
   - **Load:** testing at the plan's real volume (`make perf` covers 5,000 members on one machine).
   - **Accessibility:** a manual audit with screen-reader users; Lighthouse and the keyboard-only test are automated checks only.

## Known differences from the blueprint

`tests/test_golden.py` asserts every blueprint number. Six checks are `xfail(strict=True)`, all
from the contact-confidence formula (recency x source reliability x outcome), which was not tuned
to force a match:

- **SYN-005 and SYN-002 scores:** 68.7 and 46.3 instead of 68.6 and 46.4, because A is 0.81 and 0.59 instead of 0.80 and 0.60. With the annex's A, the arithmetic reproduces the annex scores exactly.
- **Disconnected numbers:** 555-0110 (Darnell) and 555-0133 (Kayla) both compute to 0.06; the annex lists 0.05 and 0.10. Neither number is callable, so neither affects a score.

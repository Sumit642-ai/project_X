# Synthetic feeds (`make synth`) and ingestion (`make ingest`)

Source of truth for the hero members: `annex.md` (repo root). Everything is fictional.

## Files written to `data/raw/`

| Feed | File | Shape |
|---|---|---|
| eligibility | `eligibility_834_YYYYMMDD.csv` | 834-style member rows, incl. representative fields |
| claims | `claims_837_YYYYMMDD.csv` | 837P/837I headers; `claims_loaded_through` = 2026-09-25 on every row |
| pharmacy | `pharmacy_ncpdp_YYYYMMDD.csv` | NCPDP fills incl. rejects (75 = PA required, 70 = non-formulary) |
| adt | `ADT_<received>_<control>.hl7` | HL7 v2.5.1 A01/A03/A04, CR-separated, DG1-3 always blank |
| documents | `CCDA_<date>_<doc>.xml`, `hie_requests_YYYYMMDD.csv` | simplified C-CDA (problems, meds, disposition/address, follow-up) and HIE queries |
| um | `auth_requests_YYYYMMDD.csv` | prior auth and Part D coverage determinations |
| formulary | `formulary_YYYYMMDD.csv` | tier, copay, formulary status, PA/step flags, alternative |
| care_gaps | `care_gaps_YYYYMMDD.csv` | TRC, FMC, FUH, PDC with due dates |
| labs | `lab_results_YYYYMMDD.csv` | LOINC results (added: the annex has labs that no listed feed carries) |
| cm_platform | `consents_`, `contact_points_`, `outreach_`, `preferences_*.json` | consents (TCPA per number, Part 2, representative, third-party release), contact ladder, outreach, preferences |
| medicaid | `ltss_aide_hours_20261008.csv`, `nemt_trips_YYYYMMDD.csv` | LTSS file is 32 days old on purpose (I-16) |
| sdoh | `screens_YYYYMMDD.csv` | HRA, AHC-HRSN housing, ZBI-4 caregiver strain |
| part2 | `new_dawn_notes_YYYYMMDD.csv` | New Dawn Recovery counselling notes, SYN-004 only |
| risk | `risk_scores_YYYYMMDD.csv` | plan predictive risk score (R); annex values for heroes, about 10% of background members have none |

`MANIFEST.json` lists every file (rows, bytes, sha256), the members, where each imperfection
I-01..I-17 is planted, and records that are intentionally absent (e.g. Raymond's discharge
summary, his inpatient claim, the 80 mg furosemide fill).

Background members: SYN-006..SYN-050. Each per-member imperfection kind is planted in 5 of 45
(the smallest count of at least 10%). I-12 stays with SYN-004 (Part 2 is a single program),
I-16 is file-level. I-11 uses the same members as I-09 (the new number lacks the consent the
old number had).

Determinism: fixed seed 20261109, no wall-clock reads, fixed line endings. The test suite
regenerates in two processes with different hash seeds and compares checksums.

## Values the annex does not state (chosen here)

- Dates of birth consistent with the annex ages on 2026-11-09; Anh Pham's sex recorded as F.
- Cities and ZIPs (Columbus/Dayton, OH). Month-only annex dates use the 1st of the month.
- Record IDs (`SYN-CLM-…`, `SYN-RX-…`, etc.), NDCs (synthetic, labeler prefix 99), ADT control
  IDs and visit numbers.
- SYN-001-H is the patient ID in St Brigid's ADT and medication list (the hospital created it).
- Raymond's representative form expiry (2027-05-31); Joan's consent date.
- Discharge prescriber for sacubitril/valsartan ("Dr K. Osei (St Brigid Regional)").
- Exact times inside annex months for outreach attempts, and SYN-004's disconnected-number
  call on 2026-10-16 (the annex gives no date).
- SYN-003's NEMT pickup address (an older address), Part 2 note dates and wording.
- SYN-002 has no named CM; `cm_language_required = vi`.
- Formulary alternative for semaglutide: dulaglutide.
- Kayla's 2026-07-02 claim keeps the annex code F31.81 even though F31.81 is Bipolar II and her
  condition is Bipolar I. Flagged, not changed.
- W19 (unspecified fall) is kept without a 7th character, as in the annex.

## Ingestion outcomes

- **PASS:** rows are staged in `stg_*` with `load_id` and `source_row`. For snapshot streams
  the new load becomes active.
- **QUARANTINE:**
  - a missing or added column (schema change)
  - more than 2% of rows failing the contract
  - a snapshot row count more than 30% below the active load
  - an unknown file name, or a file that cannot be read

  Nothing is staged, and the previous good load stays active.
- `feed_status(session, clock)` reports, per feed, the last good load time, its age in hours
  on the injected clock, and the data as-of date (claims: loaded-through date).

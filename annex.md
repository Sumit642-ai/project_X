# CaseCompass Synthetic Data Annex (source of truth)

All data is fictional. IDs use the prefix SYN-, phone numbers use 555-01xx. No real PHI.

- **Reference clock:** Monday 9 Nov 2026, 08:00, America/New_York
- **Medical claims loaded through:** 25 Sep 2026 (45 days old)
- **Plan:** "Evergreen" (fictional), all members in Ohio (OH)
- **Score formula:** Score = 40R + 30U + 20M + 10A
  - U = max(U_deadline, U_clinical)
  - U_deadline = clamp(1 − h/120, 0, 1), where h is the number of hours to the earliest member-contact deadline, measured to 17:00 local on the due day
  - U_clinical: red = 1.0, amber = 0.6, routine contact due = 0.3, otherwise 0
  - M is multiplied by 0.75 when its key input is older than 30 days
  - A = confidence of the best authorised contact point
- **Tiers:** T0 if U ≥ 0.9; T1 if 0.5 ≤ U < 0.9; T2 otherwise. Sort by tier, then by score.

---

## Sheet 1: Members and score inputs

| member_id | duplicate record | name | age | plan | language | conditions | CM | R | U | M | A | score | tier | rank |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SYN-001 | SYN-001-H (hospital-created, match 0.86) | Raymond Tull | 76 | MA-PPO | English | HFrEF (EF 30%), CKD 3a, HTN | Maria | 0.88 | 1.0 | 1.0 | 0.82 | 93.4 | T0 | 1 |
| SYN-004 | SYN-004-M (maiden name Delaney, 0.78, not merged) | Kayla Morrison | 34 | Medicaid MCO | English | Bipolar I, opioid use disorder, asthma | Alma | 0.74 | 1.0 | 1.0 | 0.75 | 87.1 | T0 | 2 |
| SYN-003 | — | Darnell Pruitt | 54 | Dual (disability) | English | Severe asthma, chronic pain, T2DM | Devon | 0.71 | 0.6 | 1.0 | 0.72 | 73.6 | T1 | 3 |
| SYN-005 | — | Rose-Marie Joseph | 84 | D-SNP (fully integrated) | Haitian Creole (daughter: English) | Dementia, CKD 4, falls, HTN | Maria | 0.69 | 0.6 | 0.75 | 0.80 | 68.6 | T1 | 4 |
| SYN-002 | — | Anh Pham | 68 | MA-PPO | Vietnamese | T2DM, HTN, hyperlipidemia | Vietnamese-speaking CM | 0.41 | 0.3 | 0.75 | 0.60 | 46.4 | T2 | 5 |

### Score worked examples

| member | deadline | h | U_deadline | U_clinical | arithmetic |
|---|---|---|---|---|---|
| SYN-001 | Transition contact Tue 10 Nov 17:00 (2 business days after Sat discharge) | 33 | 0.725 | 1.0 red (no diuretic on hand) | 35.2 + 30 + 20 + 8.2 = 93.4 |
| SYN-004 | FUH 7-day follow-up Thu 12 Nov 17:00 | 81 | 0.325 | 1.0 red (psych discharge ≤ 7 days, no contact) | 29.6 + 30 + 20 + 7.5 = 87.1 |
| SYN-003 | FMC 7-day follow-up Fri 13 Nov 17:00 | 105 | 0.125 | 0.6 amber (rescue inhaler gap after ED) | 28.4 + 18 + 20 + 7.2 = 73.6 |
| SYN-005 | none scored (DME deadline is UM-owned) | — | 0 | 0.6 amber (caregiver crisis) | 27.6 + 18 + 15 + 8 = 68.6 |
| SYN-002 | PDC gap due 31 Dec (outside 120 h) | — | 0 | 0.3 routine due | 16.4 + 9 + 15 + 6 = 46.4 |

---

## Sheet 2: Eligibility and contacts on file

| member_id | effective | PCP | representative | phone on file (as of) | address on file (as of) |
|---|---|---|---|---|---|
| SYN-001 | 2019-01-01 | Dr A. Lindqvist | Wife Joan, valid | 555-0177 landline (2023-02) | 12 Larch St (2023-02) |
| SYN-001-H | created 2026-11-03 by hospital | — | — | 555-0142 (2026-11) | 12 Larch Street |
| SYN-002 | 2023-01-01 | Dr T. Nguyen | — | 555-0121 (2025-06) | 88 Pine Ave (2025-06) |
| SYN-003 | 2021-07-01 | none attributed (no visit in 14 months) | — | 555-0110, disconnected 2026-10-20 | 401 Elm Ct Apt 3 (2024-01) |
| SYN-004 | 2024-04-01 | Riverside FQHC | — | 555-0133, disconnected | 9 Birch Rd, evicted Sep 2026 (2025-12) |
| SYN-004-M | 2022-02 to 2023-06 | — | — | 555-0134 | 70 Oak St |
| SYN-005 | 2024-01-01; Medicaid redetermination due 2026-12-31 | Dr M. Celestin | Daughter Mirlande, form expired 2026-09-30 | 555-0155 daughter (2026-03) | 3 Cedar Ln (2026-03) |

---

## Sheet 3: ADT events (diagnosis field always blank)

| member_id | event | facility | event time | received | diagnosis field |
|---|---|---|---|---|---|
| SYN-001 | Admit (A01) | St Brigid Regional | 2026-11-03 14:20 | 2026-11-03 15:05 | blank |
| SYN-001 | Discharge home (A03) | St Brigid Regional | 2026-11-07 13:40 | 2026-11-07 14:12 | blank |
| SYN-003 | ED registration (A04) | Lakeview ED | 2026-10-28 21:05 | 2026-10-29 07:10 | blank |
| SYN-003 | ED registration (A04) | Lakeview ED | 2026-11-06 22:15 | 2026-11-07 06:30 | blank |
| SYN-003 | ED discharge (A03) | Lakeview ED | 2026-11-07 03:50 | 2026-11-07 06:31 | blank |
| SYN-004 | Discharge from psychiatric unit (A03) | Mercy BH Pavilion | 2026-11-05 11:00 | 2026-11-05 12:10 | blank (diagnosis comes from the HIE summary) |

---

## Sheet 4: Medical claims (loaded through 25 Sep 2026)

| member_id | service date | type | diagnosis | status |
|---|---|---|---|---|
| SYN-001 | 2026-08-14 | Office visit | I50.22, N18.31 | Paid |
| SYN-001 | 2026-11-03 | Inpatient | — | Not received |
| SYN-002 | 2026-03-10 | Office visit | E11.65 | Paid |
| SYN-002 | 2026-09-16 | PCP visit (inferred from new prescription) | — | Not received |
| SYN-003 | 2026-08-19 | ED | J45.51 | Paid |
| SYN-003 | 2026-10-03 | ED | J45.41, G89.29 | Received after cut-off, pending |
| SYN-003 | 2026-10-28 | ED | — | Not received (ADT only) |
| SYN-003 | 2026-11-06 | ED | — | Not received (ADT only) |
| SYN-004 | 2026-07-02 | BH outpatient | F31.81 | Paid |
| SYN-005 | 2026-05-12 | ED for fall | W19 | Paid |
| SYN-005 | 2026-08-28 | ED for fall | W19 | Paid |
| SYN-005 | 2026-09-01 to 2026-10-30 | Home health episode | N18.4, F03.B0 | Paid in part |

---

## Sheet 5: Pharmacy (PBM), with "covered through" = fill date + days supply

| member_id | drug | fill date | days | covered through | status | note |
|---|---|---|---|---|---|---|
| SYN-001 | Furosemide 40 mg daily | 2026-09-30 | 30 | 2026-10-30 | Paid | Ran out 4 days before admission |
| SYN-001 | Furosemide 80 mg daily | — | — | — | No claim since discharge | New dose at discharge |
| SYN-001 | Sacubitril/valsartan 24/26 mg BID | 2026-11-07 | 30 | — | Rejected: PA required (coverage determination needed) | Tier 3, est. copay $47/month |
| SYN-001 | Metoprolol succinate 50 mg | 2026-10-15 | 30 | 2026-11-14 | Paid | Pharmacy profile phone 555-0142 (2026-10-28) |
| SYN-002 | Metformin 1000 mg BID | 2026-08-02 | 90 | 2026-10-31 | Paid | |
| SYN-002 | Glipizide 5 mg | 2026-05-01 | 90 | 2026-07-30 | Paid | Stopped by PCP |
| SYN-002 | Semaglutide 0.25 mg weekly | 2026-09-16 | 28 | — | Rejected: non-formulary | Never filled; prescriber Dr T. Nguyen |
| SYN-003 | Budesonide/formoterol inhaler | 2026-10-28 | 30 | 2026-11-27 | Paid | New number 555-0188 on pharmacy profile |
| SYN-003 | Albuterol rescue inhaler | 2026-08-20 | 25 | 2026-09-14 | Paid | Rescue gap since September |
| SYN-004 | Buprenorphine/naloxone (Riverside FQHC primary care; NOT a Part 2 program, visible) | 2026-10-22 | 14 | 2026-11-05 | Paid | Supply ends on discharge day |
| SYN-004 | Lamotrigine 100 mg | 2026-11-05 | 14 | 2026-11-19 | Paid | Discharge supply |
| SYN-005 | Donepezil 10 mg | 2026-10-10 | 30 | 2026-11-09 | Paid | Due today |
| SYN-005 | Amlodipine 5 mg | 2026-10-10 | 30 | 2026-11-09 | Paid | Due today |

---

## Sheet 6: Clinical documents and labs

| member_id | source | item | date | content | status |
|---|---|---|---|---|---|
| SYN-001 | HIE query | Discharge summary | — | — | Requested 2026-11-07 15:02, not received |
| SYN-001 | HIE | Hospital med list | 2026-11-07 | Furosemide 80 mg daily; sacubitril/valsartan new; metoprolol succinate 50 mg | Received |
| SYN-001 | Lab (LOINC 33762-6) | NT-proBNP | 2026-11-04 | 4,850 pg/mL | Received |
| SYN-002 | Lab (LOINC 4548-4) | HbA1c | 2026-10-02 | 8.9% (Mar 2026: 7.6%) | Received |
| SYN-003 | HIE | ED note | 2026-11-07 | Asthma exacerbation; out of rescue inhaler | Received |
| SYN-004 | HIE | Psych discharge summary | 2026-11-05 | Bipolar I, stabilised; BH follow-up within 7 days; discharge address Riverside shelter, case desk 555-0160; release to coordinate with shelter signed 2026-11-05 | Received |
| SYN-004 | Part 2 program (New Dawn Recovery) | Counselling notes | 2026-10 | MASKED | Consent for treatment, payment and operations on file 2025-03-14 |
| SYN-005 | Lab (LOINC 33914-3) | eGFR | 2026-09-20 | 22 mL/min/1.73 m² | Received |

---

## Sheet 7: Coverage, prior auth and Medicaid services

| member_id | item | requested | status | decision due |
|---|---|---|---|---|
| SYN-001 | Sacubitril/valsartan, Part D coverage determination | Not yet requested | — | 24 h once filed as expedited (prescriber files) |
| SYN-005 | Hospital bed (DME) | 2026-10-29 | Pending, missing face-to-face note | 2026-11-05, overdue |
| SYN-005 | Aide hours (Medicaid LTSS) | Reassessed 2026-10-01 | Cut from 20 to 12 h/week (−40%) | Appeal window 60 days; file as of 2026-10-08 |

---

## Sheet 8: Contact ladder and outreach history

| member_id | number | owner | source, last verified | last outcome | best time | confidence | SMS consent |
|---|---|---|---|---|---|---|---|
| SYN-001 | 555-0142 | Member mobile | Pharmacy, 2026-10-28 | Answered pharmacy IVR | 10–12 | 0.82 | No |
| SYN-001 | 555-0143 | Wife Joan (authorised representative, manages pills) | CM note, 2026-06 | Answered | Evenings | 0.70 | No |
| SYN-001 | 555-0177 | Landline | Eligibility, 2023-02 | No answer x2 (Oct) | — | 0.35 | No |
| SYN-002 | 555-0121 | Member | Eligibility, 2025-06 | 4 English voicemails, 5–29 Oct | — | 0.60 | Yes |
| SYN-003 | 555-0188 | Member (likely) | Pharmacy, 2026-10-28 | Not yet tried | 18–19 | 0.72 | No |
| SYN-003 | 555-0110 | Member | Eligibility | Disconnected 2026-10-20 | — | 0.05 | No |
| SYN-004 | 555-0160 | Riverside shelter case desk | Discharge summary, 2026-11-05 | — | 09–17 | 0.75 | n/a (release signed) |
| SYN-004 | 555-0133 | Member | Eligibility | Disconnected; no phone minutes | — | 0.10 | No |
| SYN-004 | 555-0161 | Sister | Old note, 2025-05 | — | — | 0.40 (no authorisation: not callable) | No |
| SYN-005 | 555-0155 | Daughter Mirlande | Eligibility, 2026-03 | 3 daytime voicemails | After 19:00 (works two jobs) | 0.80 | Yes |

---

## Sheet 9: Care gaps, screens and services

| member_id | item | date | value | freshness |
|---|---|---|---|---|
| SYN-001 | Transition contact target | due 2026-11-10 17:00 | open | green |
| SYN-001 | Follow-up appointment | — | UNKNOWN (practice not connected) | grey |
| SYN-001 | HRA | 2026-03-04 | Lives with wife; independent | amber (8 months) |
| SYN-002 | Diabetes adherence (PDC) | YTD | 0.76, under 0.80 | green |
| SYN-003 | FMC 7-day follow-up | due 2026-11-13 | open | green |
| SYN-003 | Transport (NEMT) | 2026-10 | 2 no-shows, outdated pickup address | green |
| SYN-004 | Housing screen | 2025-12-01 | "Stable" (now wrong) | red (11 months) |
| SYN-004 | FUH 7-day follow-up | due 2026-11-12 | open | green |
| SYN-005 | Caregiver strain (short Zarit) | 2026-02-10 | 14 of 16, high | red (9 months) |
| SYN-005 | Home health | ended 2026-10-30 | no skilled visits since | green |

---

## Sheet 10: Imperfections log

| # | member | imperfection | why it is realistic | product handling |
|---|---|---|---|---|
| I-01 | SYN-001 | Hospital-created duplicate record | Registration creates shells | Match banner 0.86, review, no auto-merge |
| I-02 | SYN-001 | Furosemide 40 vs 80 mg | Half of discharges carry a discrepancy | Conflict card; member-reported; prescriber decides |
| I-03 | SYN-001 | Diuretic ran out before admission | Gaps hide inside fill histories | "Covered through" date surfaces it |
| I-04 | SYN-001 | Discharge summary never arrived | Push and query gaps | Document tracker + auto re-query |
| I-05 | SYN-001 | ADT without diagnosis; inpatient claim missing | Rule minimum; claims lag | "Reason unknown"; "claims as of 25 Sep" |
| I-06 | SYN-002 | "Refill gap" is a non-formulary reject | Common cause of apparent non-adherence | Non-formulary rule; formulary alternative step |
| I-07 | SYN-002 | PCP visit not in claims | Claims lag | Inferred from prescription date; unknown is not no |
| I-08 | SYN-002 | 4 English voicemails to a Vietnamese speaker | Language preference ignored | Language routing |
| I-09 | SYN-003 | Disconnected number; newer one at pharmacy | Contact data decays | Reach ladder, auto-demote |
| I-10 | SYN-003 | 2 of 4 ED visits only in ADT | Claims lag | ADT-sourced count, "claims pending" |
| I-11 | SYN-003 | No SMS consent on new number | TCPA | SMS blocked; call + CHW path |
| I-12 | SYN-004 | Part 2 counselling notes vs visible primary-care buprenorphine | Rule applies by program, not by drug | Mask the program's records only |
| I-13 | SYN-004 | Housing screen 11 months old and wrong | Rare re-screening | Re-screen prompt; shelter from discharge summary |
| I-14 | SYN-004 | Maiden-name duplicate (0.78) | Name changes | Not merged; review queue |
| I-15 | SYN-005 | Representative form expired | Admin lapse | Consent flag; renew on the call |
| I-16 | SYN-005 | LTSS file 32 days old | State file lag | "As of" stamp; M discounted 25% |
| I-17 | SYN-005 | Bed authorisation past its decision date | Missing document | Overdue timer; escalation task |

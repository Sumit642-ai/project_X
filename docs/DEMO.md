# CaseCompass demo: the 15-minute script

Synthetic data only. Every break goes through the same path as real life: feed files go through
the data-layer mock, consents arrive as snapshots, and the mock CM platform is told to go down.
`e2e/tests/demo_script.spec.ts` runs this whole script (opening, happy path, breaks 1-4) in
under 3 minutes.

## Before you start (2 minutes)

```sh
make demo
```

- **What it does:**
  - drops `data/demo/` and rebuilds the demo SQLite database: synth, ingest, identity, normalise, facts, users, then signals and scores
  - freezes the clock at **Mon 9 Nov 2026 08:00 America/New_York**
  - starts the API (:8000), the mock CM platform (:8200) and the frontend
- **When it's ready:** it prints `Demo ready in N s` (about 15 s to build and under a minute in all) and the URLs.
- **Same output every time:** two runs give the same queue. `data/demo/queue_snapshot.json` is byte-identical, and so is the `queue sha256` the build prints.
- **Two browser tabs:**
  - **Tab A (presenter):** http://127.0.0.1:5173/demo/old-way
  - **Tab B (operator):** http://127.0.0.1:5173/demo-admin. Sign in first, as anyone.
- **Live AI drafts (optional):** set `ANTHROPIC_API_KEY` before `make demo`. Without a key the Live pane says "AI draft unavailable", which is itself part of the story.
- **To start over:** click **Reset demo** in the purple demo clock bar, or in the operator panel. You get the pristine database, Monday 08:00, and an empty CM platform that is up.

## Opening: the old way (1 minute)

1. Tab A shows `/demo/old-way`: **seven portal tabs** for Raymond Tull, none connected to each other.
2. Click **2. PBM pharmacy**. Furosemide **40 mg** last paid 30 Sep, and sacubitril/valsartan **rejected, PA required**.
3. Click **3. HIE viewer**. Furosemide **80 mg** on the hospital list, discharge on 7 Nov, and a hospital record **SYN-001-H** that isn't linked to his plan record.
4. Click **7. Fax inbox**. Page 2 of the med rec is missing.
5. Click **Now the same member in CaseCompass →**.

## Happy path: Raymond (5 minutes)

1. On the sign-in page, which lists the seeded users in demo mode only, click **Sign in as Maria · RN, complex case management**.
2. **Queue:** Raymond is **#1, T0, 93.4**. Hover the score to see 40R + 30U + 20M + 10A with its inputs. The why-chips include "Furosemide ran out 2026-10-30; no fill since discharge".
3. Click **Open Raymond Tull**. The banner reads "Possible duplicate · flagged by data layer" (SYN-001-H, 0.86). Click **Same person: confirm**, and the hospital facts join his record.
4. Point out the **furosemide conflict card**: 40 mg vs 80 mg, flagged by data layer. Nothing resolves it automatically; the prescriber decides.
5. Click **Start call**, then **Dial 555-0142** (connected).
6. Click **Name and date of birth verified**, then tick **Member agreed to transcription**.
7. Optional: click **Draft note from transcript**. Each sentence cites transcript turns; UNSUPPORTED ones are struck through. Insert the draft into the notes, or type your own.
8. Click **Go to wrap-up**. Confirm the 6 high-risk medication fields **one by one**, then click **Confirm 16 low-risk fields**.
9. Click **End call and create tasks**. The new tasks include "Message prescriber: confirm loop-diuretic dose and supply" and "Track coverage request".
10. Don't save yet: break 1 starts here.

## Break 1: the CM platform goes down (2 minutes)

1. Tab B: click **Take CM platform down**.
2. Tab A: click **Save to record**. It reads **"Saved here, syncing to record"**: nothing is lost and nobody retypes anything.
3. Tab B: click **Restore CM platform**. The message reads "1 waiting save(s) synced".
4. Tab A: within 5 s the status turns synced and the app returns to the queue, where Raymond has dropped to **T2**. The CM platform holds **exactly one** entry, because the idempotency key prevents duplicates.

## Break 2: the pharmacy feed pauses (1 minute)

1. Tab B: click **Pause pharmacy feed**.
2. Tab A: reload the queue. An amber banner reads **"pharmacy (feed paused at the data layer: no new files since …)"**. Nurses know which data to distrust.
3. Tab B: click **Resume pharmacy feed**.

## Break 3: Kayla, identity and Part 2 (3 minutes)

1. Tab A: **Sign out**, then **Sign in as Alma**, then **Open Kayla Morrison**.
2. The match banner reads **SYN-004-M, match confidence 0.78**, flagged by data layer. Nothing below 0.90 merges automatically; a person decides, and charting waits.
3. The Part 2 panel shows **Records restricted**: 3 records masked. Her buprenorphine is visible, because it comes from primary care, which isn't a Part 2 program.
4. Tab B: click **Expire Kayla's Part 2 consent**.
5. Tab A: reload. The consent chip reads **"Part 2 · Evergreen · expired 2026-11-08"**, and the panel reads "No valid Part 2 consent on file: records cannot be revealed". The API refuses the reveal too (403); the screen isn't the only guard.
6. Tab B: click **Restore Kayla's Part 2 consent**. She signs a new form today.
7. Tab A: reload, then click **Reveal restricted records**, give a reason, and click **Reveal (audited)**. The notes appear with the 42 CFR Part 2 redisclosure notice, and the reveal is in the audit trail (Janet: `/audit`).

## Break 4: time passes, the data catches up (2 minutes)

1. Tab A: **Sign out**, then **Sign in as Maria**, then **Tasks**. "Message prescriber: confirm loop-diuretic dose and supply" is open.
2. In the purple demo clock bar, click **Advance to Monday 14:00**. The scripted pharmacy file arrives: Larch Street fills **furosemide 80 mg**.
3. The furosemide task turns **green** and reads "✓ Resolved by data: Furosemide 80 mg filled 2026-11-09 (fact N)". The visit/ride and HIE tasks stay open, because a fill doesn't book a visit.
4. Optional: click **Advance to Tuesday 11:00**. UM approves the sacubitril/valsartan request, and the coverage task turns green.

## Extras for questions (operator panel)

| Toggle | What to show |
|---|---|
| Pause ADT feed | Red banner: "ADT feed paused…". On a member view, **Add discharge** records a member-reported discharge, which the transition rules pick up. |
| Create a record-version conflict | Someone else edits Raymond's CM record. The next **Save to record** shows both versions and writes nothing until the nurse chooses. |
| Inject a bad pharmacy file | The new load shows **QUARANTINE** ("schema change…") in *Recent feed loads*, and the previous load stays active. |
| Make the AI draft time out | Live pane: "AI draft unavailable. Write your notes as normal." The time-out is logged in `ai_logs`. |
| Inject an unknown NDC | Darnell's record shows **Zorvantide** by its raw name, and it appears in *Unmapped codes report*. |

Every operator action is written to the audit trail as `demo_*`. All of this exists only when
`DEMO_MODE=true`: otherwise the `/demo/*` actions return 404 (`/demo/config` says demo mode is off), the clock bar and operator panel are hidden,
and the sign-in page lists no users.

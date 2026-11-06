# datalayer_mock: a stand-in for the HiLabs data layer

**This package simulates HiLabs MCheck output for the demo. It is not part of CaseCompass's scope.**

Per the caselet, ingestion, normalisation, identity matching and conflict detection belong to
the HiLabs data layer. CaseCompass needs that layer's *output*: clean, linked, normalised
records with lineage, duplicate candidates and data conflicts. This package produces that
output from the synthetic feeds so the workbench has something realistic to show.

| Module | Simulates |
|---|---|
| `ingest/` | feed landing, schema contracts, quarantine, typed staging, feed freshness |
| `normalise/` | terminology mapping (ICD-10, NDC, LOINC), unmapped-code report |
| `identity/` | golden member records, match scores, the duplicate review queue |

Conflict detection (`app/facts/conflicts.py`) is also data-layer behaviour; it lives next to the
Facts model because it reads Facts directly.

What CaseCompass builds on top: trust display (freshness, UNKNOWN, lineage), signals, scoring,
next best action (suggested) and the clinician workflow. Wherever the UI or docs show a
duplicate or a conflict, they label it **"flagged by data layer"**: CaseCompass shows these, it
does not decide them.

To swap in the real data layer later, replace these modules with an adapter that writes the same
tables (`loads`, `stg_*`, `norm_*`, `members`, `member_links`) or the same Facts.

"""Assemble the dataset and write data/raw/ plus MANIFEST.json, byte-for-byte reproducibly.

Determinism: one seeded random.Random, no wall-clock reads, insertion-ordered dicts only,
fixed line endings ("\\n" for CSV/JSON/XML, "\\r" between HL7 segments) and UTF-8.
"""

import csv
import hashlib
import io
import json
import random
import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.synth.background import COUNT, FIRST_ID, PER_KIND, add_background
from app.synth.catalog import CLAIMS_LOADED_THROUGH, DRUGS, LOAD_DATES, REF, SEED, TIER_COPAY, ndc
from app.synth.ccda_builder import build_ccda
from app.synth.dataset import IMPERFECTIONS, Dataset
from app.synth.heroes import add_heroes
from app.synth.hl7_builder import build_adt
from app.synth.layouts import LAYOUTS

FEEDS = (
    "eligibility",
    "claims",
    "pharmacy",
    "um",
    "formulary",
    "care_gaps",
    "labs",
    "documents",
    "adt",
    "cm_platform",
    "medicaid",
    "sdoh",
    "part2",
    "risk",
)
HERO_IDS = ("SYN-001", "SYN-002", "SYN-003", "SYN-004", "SYN-005")


def add_formulary(ds: Dataset) -> None:
    for drug in DRUGS:
        for strength in drug.strengths:
            ds.add(
                "formulary",
                ndc=ndc(drug.key, strength),
                drug_name=drug.name,
                strength=strength,
                tier=drug.tier,
                copay_30day=TIER_COPAY[drug.tier] if drug.tier else None,
                formulary_status="formulary" if drug.tier else "non_formulary",
                pa_required=drug.pa_required,
                step_therapy=drug.step_therapy,
                preferred_alternative=drug.alternative,
            )


def build_dataset(seed: int = SEED) -> Dataset:
    ds = Dataset()
    add_heroes(ds)
    add_background(ds, random.Random(seed))
    add_formulary(ds)
    return ds


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return "|".join(value)
    return str(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _render(ds: Dataset) -> dict[str, tuple[bytes, int]]:
    """Relative path -> (file bytes, record count)."""
    files: dict[str, tuple[bytes, int]] = {}
    for layout in LAYOUTS:
        rows = ds.rows[layout.stream]
        path = layout.file_name(LOAD_DATES[layout.load_key].strftime("%Y%m%d"))
        if layout.fmt == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(layout.columns)
            writer.writerows([_csv_value(row[c]) for c in layout.columns] for row in rows)
            content = buffer.getvalue()
        else:
            records = [{c: _json_value(row[c]) for c in layout.columns} for row in rows]
            content = json.dumps(records, indent=2, ensure_ascii=False) + "\n"
        files[path] = (content.encode("utf-8"), len(rows))
    for event in ds.adt:
        files[event.file_name] = (build_adt(event).encode("utf-8"), 1)
    for doc in ds.documents:
        files[doc.file_name] = (build_ccda(doc).encode("utf-8"), 1)
    return dict(sorted(files.items()))


def _manifest(ds: Dataset, files: dict[str, tuple[bytes, int]], seed: int) -> dict[str, Any]:
    imperfections = []
    for imp in IMPERFECTIONS:
        planted = ds.planted[imp.id]
        entry: dict[str, Any] = {
            "id": imp.id,
            "title": imp.title,
            "feeds": list(imp.feeds),
            "hero_members": planted["hero"],
            "background_members": sorted(planted["background"]),
        }
        if not imp.background:
            entry["background_note"] = (
                "Part 2 records exist for SYN-004 only"
                if imp.id == "I-12"
                else "file-level lag: the whole LTSS file is stale"
            )
        imperfections.append(entry)
    return {
        "generator": "app.synth",
        "seed": seed,
        "reference_clock": REF.isoformat(),
        "claims_loaded_through": CLAIMS_LOADED_THROUGH.isoformat(),
        "members": {
            "hero": list(HERO_IDS),
            "background": [f"SYN-{FIRST_ID + i:03d}" for i in range(COUNT)],
            "background_imperfection_rate": f"{PER_KIND} of {COUNT} per kind",
        },
        "files": [
            {
                "path": path,
                "feed": path.split("/", 1)[0],
                "rows": rows,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, (content, rows) in files.items()
        ],
        "imperfections": imperfections,
        "intentionally_absent": ds.absent,
    }


def generate(out_dir: Path, seed: int = SEED, background_members: int = 0) -> dict[str, Any]:
    """Write every raw feed file and MANIFEST.json under out_dir; return the manifest.

    background_members > 45 clones the background up to that many (performance runs only).
    """
    ds = build_dataset(seed)
    if background_members:
        from app.synth.scale import scale_dataset

        scale_dataset(ds, background_members)
    files = _render(ds)
    manifest = _manifest(ds, files, seed)

    out_dir.mkdir(parents=True, exist_ok=True)
    for feed in FEEDS:  # remove only what this generator owns
        shutil.rmtree(out_dir / feed, ignore_errors=True)
    for path, (content, _) in files.items():
        target = out_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    (out_dir / "MANIFEST.json").write_bytes(text.encode("utf-8"))
    return manifest

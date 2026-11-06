"""Acceptance tests that run ingestion over the output of `make synth`."""

import csv
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, FixedClock
from app.datalayer_mock.ingest import feed_status, ingest_all, ingest_file
from app.datalayer_mock.ingest.models import PASS, QUARANTINE, Load
from app.datalayer_mock.ingest.staging import STAGING_TABLES
from app.synth.generate import FEEDS


def test_clean_run_loads_every_feed_pass_with_manifest_row_counts(
    session: Session, clock: FixedClock, landing: Path, generated_raw: Path
) -> None:
    manifest = json.loads((generated_raw / "MANIFEST.json").read_text(encoding="utf-8"))

    loads = ingest_all(session, generated_raw, clock=clock, landing_root=landing)

    assert len(loads) == len(manifest["files"])
    assert {load.status for load in loads} == {PASS}
    assert sum(load.rejected_rows for load in loads) == 0
    assert {load.file: load.row_count for load in loads} == {
        f["path"]: f["rows"] for f in manifest["files"]
    }
    fresh = {s.feed: s for s in feed_status(session, clock)}
    assert all(fresh[feed].last_good_load_at is not None for feed in FEEDS)


def test_raymond_adt_messages_and_missing_summary_are_handled(
    session: Session, clock: FixedClock, landing: Path, generated_raw: Path
) -> None:
    ingest_all(session, generated_raw, clock=clock, landing_root=landing)

    adt = STAGING_TABLES["adt"]
    messages = session.execute(
        select(adt.c.trigger_event, adt.c.event_at, adt.c.message_at, adt.c.diagnosis_code)
        .where(adt.c.patient_id == "SYN-001-H")
        .order_by(adt.c.event_at)
    ).all()
    assert [(m.trigger_event, m.event_at, m.message_at, m.diagnosis_code) for m in messages] == [
        (
            "A01",
            datetime(2026, 11, 3, 14, 20, tzinfo=PLAN_TZ),
            datetime(2026, 11, 3, 15, 5, tzinfo=PLAN_TZ),
            None,
        ),
        (
            "A03",
            datetime(2026, 11, 7, 13, 40, tzinfo=PLAN_TZ),
            datetime(2026, 11, 7, 14, 12, tzinfo=PLAN_TZ),
            None,
        ),
    ]

    requests = STAGING_TABLES["hie_requests"]
    request = session.execute(select(requests).where(requests.c.member_id == "SYN-001")).one()
    assert (request.document_type, request.status, request.received_at) == (
        "discharge_summary",
        "not_received",
        None,
    )
    documents = STAGING_TABLES["ccda"]
    summaries = session.execute(
        select(documents.c.document_id).where(
            documents.c.patient_id.in_(["SYN-001", "SYN-001-H"]),
            documents.c.document_type_code == "18842-5",
        )
    ).all()
    assert summaries == []
    assert session.scalars(select(Load).where(Load.status != PASS)).all() == []


def _pharmacy_file(raw: Path) -> Path:
    (path,) = (raw / "pharmacy").glob("pharmacy_ncpdp_*.csv")
    return path


def test_copy_of_pharmacy_file_with_a_dropped_column_is_quarantined(
    session: Session, clock: FixedClock, landing: Path, generated_raw: Path, tmp_path: Path
) -> None:
    good = ingest_file(session, _pharmacy_file(generated_raw), clock=clock, landing_root=landing)
    with _pharmacy_file(generated_raw).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    drop = rows[0].index("days_supply")
    copy = tmp_path / "pharmacy" / "pharmacy_ncpdp_20261109.csv"
    copy.parent.mkdir()
    with copy.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(
            [c for i, c in enumerate(row) if i != drop] for row in rows
        )

    bad = ingest_file(session, copy, clock=clock, landing_root=landing)

    assert bad.status == QUARANTINE and bad.error == "schema change: missing ['days_supply']"
    session.refresh(good)
    assert good.status == PASS and good.is_active and not bad.is_active


def test_pharmacy_file_50_percent_shorter_is_quarantined(
    session: Session, clock: FixedClock, landing: Path, generated_raw: Path, tmp_path: Path
) -> None:
    good = ingest_file(session, _pharmacy_file(generated_raw), clock=clock, landing_root=landing)
    lines = _pharmacy_file(generated_raw).read_text(encoding="utf-8").splitlines()
    half = lines[: 1 + (len(lines) - 1) // 2]
    copy = tmp_path / "pharmacy" / "pharmacy_ncpdp_20261109.csv"
    copy.parent.mkdir()
    copy.write_text("\n".join(half) + "\n", encoding="utf-8")

    short = ingest_file(session, copy, clock=clock, landing_root=landing)

    assert short.status == QUARANTINE
    assert short.error is not None and "50% below last good load" in short.error
    session.refresh(good)
    assert good.is_active


def test_generated_files_land_unchanged(
    session: Session, clock: FixedClock, landing: Path, generated_raw: Path
) -> None:
    loads = ingest_all(session, generated_raw, clock=clock, landing_root=landing)
    for load in loads:
        assert (landing / str(load.landing_path)).read_bytes() == (
            generated_raw / load.file
        ).read_bytes()

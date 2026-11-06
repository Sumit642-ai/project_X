import time
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, FixedClock
from app.datalayer_mock.ingest import ingest_adt_message, ingest_file
from app.datalayer_mock.ingest.models import PASS, QUARANTINE
from app.datalayer_mock.ingest.staging import STAGING_TABLES
from app.synth.ccda_builder import CcdaDocument, Medication, build_ccda
from app.synth.hl7_builder import AdtEvent, build_adt


def _event(**overrides: object) -> AdtEvent:
    values: dict[str, object] = dict(
        control_id="SYN-ADT-900001",
        trigger="A01",
        facility_code="STBRIGID",
        facility_name="St Brigid Regional",
        event_at=datetime(2026, 11, 3, 14, 20, tzinfo=PLAN_TZ),
        received_at=datetime(2026, 11, 3, 15, 5, tzinfo=PLAN_TZ),
        patient_id="SYN-001-H",
        assigning_authority="STBRIGID",
        last_name="Tull",
        first_name="Raymond",
        dob=date(1950, 4, 12),
        sex="M",
        phone="555-0142",
        address_line1="12 Larch Street",
        city="Columbus",
        zip="43204",
        patient_class="I",
        visit_number="SYN-V-900001",
        admit_at=datetime(2026, 11, 3, 14, 20, tzinfo=PLAN_TZ),
        discharge_at=None,
        discharge_disposition=None,
    )
    values.update(overrides)
    return AdtEvent(**values)  # type: ignore[arg-type]


def test_single_adt_message_is_ingested_in_under_one_second(
    session: Session, clock: FixedClock, landing: Path
) -> None:
    raw = build_adt(_event())

    started = time.perf_counter()
    load = ingest_adt_message(raw, session=session, clock=clock, landing_root=landing)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0
    assert load.status == PASS and load.file == "realtime:SYN-ADT-900001"
    table = STAGING_TABLES["adt"]
    row = session.execute(select(table).where(table.c.load_id == load.id)).one()
    assert (row.trigger_event, row.patient_id, row.phone) == ("A01", "SYN-001-H", "555-0142")
    assert row.diagnosis_code is None  # blank in the feed, never inferred
    assert row.event_at == datetime(2026, 11, 3, 14, 20, tzinfo=PLAN_TZ)
    assert row.message_at - row.event_at == timedelta(minutes=45)
    assert load.data_as_of == date(2026, 11, 3)


def test_duplicate_adt_message_is_not_staged_twice(
    session: Session, clock: FixedClock, landing: Path
) -> None:
    raw = build_adt(_event())
    first = ingest_adt_message(raw, session=session, clock=clock, landing_root=landing)
    second = ingest_adt_message(raw, session=session, clock=clock, landing_root=landing)

    assert second.id == first.id


def test_non_hl7_message_is_quarantined(session: Session, clock: FixedClock, landing: Path) -> None:
    load = ingest_adt_message("hello", session=session, clock=clock, landing_root=landing)

    assert load.status == QUARANTINE
    assert load.error is not None and load.error.startswith("unparseable file")


def test_adt_file_and_discharge_without_admit_time(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    event = _event(
        trigger="A03",
        control_id="SYN-ADT-900002",
        admit_at=None,
        discharge_at=datetime(2026, 11, 5, 11, 0, tzinfo=PLAN_TZ),
    )
    path = tmp_path / event.file_name
    path.parent.mkdir(parents=True)
    path.write_bytes(build_adt(event).encode())

    load = ingest_file(session, path, clock=clock, landing_root=landing)

    assert load.status == PASS
    table = STAGING_TABLES["adt"]
    row = session.execute(select(table).where(table.c.load_id == load.id)).one()
    assert row.admit_at is None and row.discharge_at is not None


def test_ccda_discharge_summary_is_parsed_into_staging(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    doc = CcdaDocument(
        doc_id="SYN-DOC-9001",
        doc_type="discharge_summary",
        patient_id="SYN-004",
        last_name="Morrison",
        first_name="Kayla",
        dob=date(1992, 6, 18),
        sex="F",
        facility="Mercy BH Pavilion",
        effective_at=datetime(2026, 11, 5, 11, 0, tzinfo=PLAN_TZ),
        received=date(2026, 11, 5),
        encounter_end=datetime(2026, 11, 5, 11, 0, tzinfo=PLAN_TZ),
        disposition="Shelter",
        discharge_address="Riverside shelter",
        discharge_phone="555-0160",
        problems=((None, "Bipolar I disorder, stabilised"),),
        medications=(Medication("Lamotrigine", "100 mg", "Lamotrigine 100 mg daily"),),
        follow_up=("Behavioral health follow-up within 7 days",),
        notes=("Release to coordinate with Riverside shelter signed 2026-11-05",),
    )
    path = tmp_path / doc.file_name
    path.parent.mkdir(parents=True)
    path.write_text(build_ccda(doc), encoding="utf-8")

    load = ingest_file(session, path, clock=clock, landing_root=landing)

    assert load.status == PASS, load.error
    table = STAGING_TABLES["ccda"]
    row = session.execute(select(table).where(table.c.load_id == load.id)).one()
    assert row.document_type_code == "18842-5"
    assert row.encounter_start is None
    assert (row.discharge_address, row.discharge_phone) == ("Riverside shelter", "555-0160")
    assert row.problems == [{"code": None, "text": "Bipolar I disorder, stabilised"}]
    assert row.medications == [
        {"name": "Lamotrigine", "dose": "100 mg", "sig": "Lamotrigine 100 mg daily"}
    ]
    assert row.follow_up == ["Behavioral health follow-up within 7 days"]


def test_malformed_ccda_is_quarantined(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    path = tmp_path / "documents" / "CCDA_20261105_SYN-DOC-9002.xml"
    path.parent.mkdir(parents=True)
    path.write_text("<ClinicalDocument>", encoding="utf-8")

    load = ingest_file(session, path, clock=clock, landing_root=landing)

    assert load.status == QUARANTINE

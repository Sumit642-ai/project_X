import json
import stat
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.datalayer_mock.ingest import ingest_file
from app.datalayer_mock.ingest.contracts import CONTRACTS
from app.datalayer_mock.ingest.models import PASS, QUARANTINE, Load, LoadError
from app.datalayer_mock.ingest.staging import STAGING_TABLES
from app.synth.layouts import LAYOUTS
from tests.datalayer_mock.ingest.helpers import (
    PHARMACY_COLUMNS,
    pharmacy_rows,
    write_csv,
    write_pharmacy,
)


def staged_rows(session: Session, stream: str, load_id: int) -> int:
    table = STAGING_TABLES[stream]
    return session.scalar(select(func.count()).where(table.c.load_id == load_id)) or 0


def ingest(session: Session, path: Path, clock: FixedClock, landing: Path) -> Load:
    return ingest_file(session, path, clock=clock, landing_root=landing)


def test_every_source_layout_has_a_matching_contract() -> None:
    for layout in LAYOUTS:
        contract = CONTRACTS[layout.stream]
        assert contract.feed == layout.feed
        assert contract.columns == layout.columns, layout.stream


def test_clean_file_passes_and_reaches_staging(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    load = ingest(session, write_pharmacy(tmp_path, "20261101", pharmacy_rows(40)), clock, landing)

    assert (load.status, load.row_count, load.is_active) == (PASS, 40, True)
    assert load.data_as_of.isoformat() == "2026-11-01"  # type: ignore[union-attr]
    assert staged_rows(session, "pharmacy_ncpdp", load.id) == 40


def test_dropped_column_is_quarantined_and_previous_load_stays_active(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    good = ingest(session, write_pharmacy(tmp_path, "20261101", pharmacy_rows(40)), clock, landing)
    columns = [c for c in PHARMACY_COLUMNS if c != "days_supply"]
    bad = ingest(
        session, write_pharmacy(tmp_path, "20261108", pharmacy_rows(40), columns), clock, landing
    )

    assert bad.status == QUARANTINE
    assert bad.error == "schema change: missing ['days_supply']"
    assert staged_rows(session, "pharmacy_ncpdp", bad.id) == 0
    session.refresh(good)
    assert good.is_active and not bad.is_active


def test_added_column_is_quarantined(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    rows = [{**row, "plan_code": "X"} for row in pharmacy_rows(10)]
    load = ingest(
        session,
        write_pharmacy(tmp_path, "20261101", rows, [*PHARMACY_COLUMNS, "plan_code"]),
        clock,
        landing,
    )

    assert load.status == QUARANTINE
    assert load.error == "schema change: added ['plan_code']"


def test_file_half_as_long_is_quarantined(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    good = ingest(session, write_pharmacy(tmp_path, "20261101", pharmacy_rows(40)), clock, landing)
    short = ingest(session, write_pharmacy(tmp_path, "20261108", pharmacy_rows(20)), clock, landing)

    assert short.status == QUARANTINE
    assert short.error is not None and "50% below last good load" in short.error
    assert staged_rows(session, "pharmacy_ncpdp", short.id) == 0
    session.refresh(good)
    assert good.is_active


def test_row_count_drop_of_exactly_30_percent_still_passes(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    ingest(session, write_pharmacy(tmp_path, "20261101", pharmacy_rows(40)), clock, landing)
    load = ingest(session, write_pharmacy(tmp_path, "20261108", pharmacy_rows(28)), clock, landing)

    assert load.status == PASS


def test_new_good_snapshot_replaces_the_active_load(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    first = ingest(session, write_pharmacy(tmp_path, "20261101", pharmacy_rows(40)), clock, landing)
    second = ingest(
        session, write_pharmacy(tmp_path, "20261108", pharmacy_rows(41)), clock, landing
    )

    session.refresh(first)
    assert second.status == PASS and second.is_active and not first.is_active


def _with_bad_rows(count: int, bad: int) -> list[dict[str, str]]:
    rows = pharmacy_rows(count)
    for row in rows[:bad]:
        row["days_supply"] = "thirty"
    return rows


def test_more_than_2_percent_unparseable_rows_is_quarantined(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    load = ingest(
        session, write_pharmacy(tmp_path, "20261101", _with_bad_rows(100, 3)), clock, landing
    )

    assert load.status == QUARANTINE
    assert load.error == "3 of 100 rows unparseable (3.0%), limit 2%"
    assert staged_rows(session, "pharmacy_ncpdp", load.id) == 0


def test_up_to_2_percent_unparseable_rows_passes_and_keeps_the_errors(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    load = ingest(
        session, write_pharmacy(tmp_path, "20261101", _with_bad_rows(100, 2)), clock, landing
    )

    assert (load.status, load.rejected_rows) == (PASS, 2)
    assert staged_rows(session, "pharmacy_ncpdp", load.id) == 98
    errors = session.scalars(select(LoadError).where(LoadError.load_id == load.id)).all()
    assert [e.source_row for e in errors] == [2, 3]
    assert all("days_supply" in e.error for e in errors)


def test_non_synthetic_phone_or_id_fails_the_contract(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    rows = pharmacy_rows(2)
    rows[0]["pharmacy_phone_on_profile"] = "614-555-1234"
    rows[1]["member_id"] = "M12345"
    load = ingest(session, write_pharmacy(tmp_path, "20261101", rows), clock, landing)

    assert load.status == QUARANTINE
    assert load.rejected_rows == 2


def test_rejected_pharmacy_claim_requires_a_reason(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    rows = pharmacy_rows(1)
    rows[0]["claim_status"] = "rejected"
    load = ingest(session, write_pharmacy(tmp_path, "20261101", rows), clock, landing)

    assert load.status == QUARANTINE
    error = session.scalars(select(LoadError).where(LoadError.load_id == load.id)).one()
    assert "reject_code and reject_reason" in error.error


def test_blank_values_are_staged_as_null_not_empty_or_zero(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    rows = pharmacy_rows(1)
    rows[0]["patient_pay"] = ""
    rows[0]["prescriber"] = ""
    load = ingest(session, write_pharmacy(tmp_path, "20261101", rows), clock, landing)

    table = STAGING_TABLES["pharmacy_ncpdp"]
    staged = session.execute(select(table).where(table.c.load_id == load.id)).one()
    assert staged.patient_pay is None and staged.prescriber is None


def test_landing_copy_is_read_only_and_byte_identical(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    source = write_pharmacy(tmp_path, "20261101", pharmacy_rows(5))
    load = ingest(session, source, clock, landing)

    landed = landing / str(load.landing_path)
    assert landed.parent == landing / "pharmacy" / f"{load.id:06d}"
    assert landed.read_bytes() == source.read_bytes()
    assert not landed.stat().st_mode & stat.S_IWRITE


def test_reingesting_the_same_file_is_idempotent(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    source = write_pharmacy(tmp_path, "20261101", pharmacy_rows(5))
    first = ingest(session, source, clock, landing)
    again = ingest(session, source, clock, landing)

    assert again.id == first.id
    assert session.scalar(select(func.count()).select_from(Load)) == 1


def test_file_without_a_contract_is_quarantined(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    path = write_csv(tmp_path / "pharmacy" / "mystery_20261101.csv", ["a"], [{"a": "1"}])
    load = ingest(session, path, clock, landing)

    assert load.status == QUARANTINE
    assert load.error == "no contract for this file name"


def test_json_stream_validates_type_specific_consent_fields(
    session: Session, clock: FixedClock, landing: Path, tmp_path: Path
) -> None:
    columns = CONTRACTS["consents"].columns
    base = dict.fromkeys(columns)
    records = [
        {
            **base,
            "consent_id": f"SYN-CON-{i:04d}",
            "member_id": "SYN-002",
            "consent_type": "tcpa_sms",
            "phone": "555-0121",
            "granted_date": "2025-06-01",
        }
        for i in range(60)
    ]
    records[0]["phone"] = None  # TCPA consent is per number: a number is required
    path = tmp_path / "cm_platform" / "consents_20261109.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(records), encoding="utf-8")

    load = ingest(session, path, clock, landing)

    assert (load.status, load.rejected_rows) == (PASS, 1)
    assert staged_rows(session, "consents", load.id) == 59

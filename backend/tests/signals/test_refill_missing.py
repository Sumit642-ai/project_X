"""EXPECTED_REFILL_MISSING: silence detection on maintenance medicines."""

import csv
import shutil
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.datalayer_mock.identity import run_matching
from app.datalayer_mock.ingest import ingest_all
from app.db.session import create_db_engine, create_session_factory
from app.facts import refresh_facts
from app.facts.snapshot import member_snapshot
from app.signals.base import Signal
from app.signals.calendar import BusinessCalendar
from app.signals.rules import ExpectedRefillMissing

SILENT_AFTER = "2026-09-20"  # fills after this date never arrive for the chosen members


def evaluate(session: Session, member_id: str) -> list[Signal]:
    clock = FixedClock()
    snapshot = member_snapshot(session, member_id, clock=clock)
    return ExpectedRefillMissing(BusinessCalendar([])).evaluate(snapshot, clock)


def _pick(rows: list[dict[str, str]], drug: str, exclude: set[str]) -> str:
    candidates = sorted(
        {
            r["member_id"]
            for r in rows
            if r["drug_name"] == drug
            and r["claim_status"] == "paid"
            and r["member_id"] >= "SYN-006"
            and r["member_id"] not in exclude
        }
    )
    return candidates[0]


@pytest.fixture(scope="module")
def silent(
    generated_raw: Path, migrated_template: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[Session, str, str]]:
    """Raw feeds where two background members' refills stop arriving after 2026-09-20."""
    work = tmp_path_factory.mktemp("silent")
    raw = work / "raw"
    shutil.copytree(generated_raw, raw)
    (path,) = (raw / "pharmacy").glob("pharmacy_ncpdp_*.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    insulin = _pick(rows, "Insulin glargine", set())
    lisinopril = _pick(rows, "Lisinopril", {insulin})
    kept = [
        r
        for r in rows
        if not (
            (r["member_id"], r["drug_name"])
            in {(insulin, "Insulin glargine"), (lisinopril, "Lisinopril")}
            and r["fill_date"] > SILENT_AFTER
        )
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(kept)

    db = work / "silent.db"
    shutil.copyfile(migrated_template, db)
    engine = create_db_engine(f"sqlite:///{db}")
    clock = FixedClock()
    with create_session_factory(engine)() as session:
        ingest_all(session, raw, clock=clock, landing_root=work / "landing")
        run_matching(session, clock)
        refresh_facts(session, clock)
        session.commit()
        yield session, insulin, lisinopril
    engine.dispose()


def test_background_member_missing_insulin_refill_is_amber(
    silent: tuple[Session, str, str],
) -> None:
    session, insulin_member, _ = silent

    (signal,) = [
        s
        for s in evaluate(session, insulin_member)
        if s.insight_text.startswith("Insulin glargine")
    ]

    assert signal.severity == "amber"
    assert signal.insight_text.endswith("; none since")
    assert signal.lever and signal.key_input_date is not None
    assert signal.key_input_date <= date(2026, 9, 20)


def test_background_member_missing_routine_refill_is_info(
    silent: tuple[Session, str, str],
) -> None:
    session, _, lisinopril_member = silent

    (signal,) = [
        s for s in evaluate(session, lisinopril_member) if s.insight_text.startswith("Lisinopril")
    ]

    assert signal.severity == "info"
    assert len(signal.insight_text.split()) <= 12


def test_background_members_with_regular_fills_are_quiet(morning: Session) -> None:
    flagged = [m for m in (f"SYN-{n:03d}" for n in range(6, 51)) if evaluate(morning, m)]
    assert flagged == []


def test_hero_refill_silences(morning: Session) -> None:
    raymond = {s.insight_text: s.severity for s in evaluate(morning, "SYN-001")}
    anh = {s.insight_text: s.severity for s in evaluate(morning, "SYN-002")}
    darnell = {s.insight_text: s.severity for s in evaluate(morning, "SYN-003")}

    assert raymond == {"Furosemide refill expected 2026-10-30; none since": "amber"}
    # Glipizide ran out 2026-07-30 (over 90 days): outside the look-back, not flagged.
    assert anh == {"Metformin refill expected 2026-10-31; none since": "info"}
    assert darnell == {"Albuterol rescue inhaler refill expected 2026-09-14; none since": "amber"}
    assert evaluate(morning, "SYN-005") == []  # supplies run to today


# --- unit level: windows and rejects ----------------------------------------------------------


def _fill(
    fact_id: int,
    fill_date: date,
    days: int,
    *,
    drug_class: str = "statin",
    dispensed: bool = True,
    key: str = "atorvastatin",
) -> Any:
    value = {
        "source_kind": "pharmacy_claim",
        "dispensed": dispensed,
        "drug_class": drug_class,
        "product": key.title(),
        "fill_date": fill_date.isoformat(),
        "covered_through": (fill_date + timedelta(days=days)).isoformat() if dispensed else None,
    }
    fact = SimpleNamespace(
        id=fact_id, type="medication", key=key, value=value, event_date=fill_date
    )
    return SimpleNamespace(fact=fact, value=value, masked=False)


def _snapshot(*views: Any) -> Any:
    return SimpleNamespace(
        member=SimpleNamespace(member_id="SYN-900"), facts=list(views), contacts=[], documents=[]
    )


@pytest.mark.parametrize(
    ("days_overdue", "fires"), [(7, False), (8, True), (90, True), (91, False)]
)
def test_grace_and_look_back_windows(days_overdue: int, fires: bool) -> None:
    clock = FixedClock()
    covered = clock.now().date() - timedelta(days=days_overdue)
    snapshot = _snapshot(_fill(1, covered - timedelta(days=30), 30))

    signals = ExpectedRefillMissing(BusinessCalendar([])).evaluate(snapshot, clock)

    assert bool(signals) is fires


def test_a_reject_on_file_explains_the_gap() -> None:
    clock = FixedClock()
    last = clock.now().date() - timedelta(days=50)
    snapshot = _snapshot(
        _fill(1, last, 30), _fill(2, last + timedelta(days=29), 30, dispensed=False)
    )

    assert ExpectedRefillMissing(BusinessCalendar([])).evaluate(snapshot, clock) == []

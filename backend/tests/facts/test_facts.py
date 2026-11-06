import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, REFERENCE_INSTANT, FixedClock
from app.datalayer_mock.identity import run_matching, unmerge
from app.datalayer_mock.identity.models import MemberLink
from app.facts import (
    ConflictDecisionError,
    FactImmutableError,
    Unknown,
    build_facts,
    contact_confidence,
    detect_conflicts,
    freshness,
    get_fact_or_unknown,
    member_snapshot,
    refresh_facts,
    resolve_conflict,
    send_to_prescriber,
)
from app.facts.conflicts import conflict_fact_ids, diagnosis_findings
from app.facts.models import Conflict, Fact


def furosemide_conflict(session: Session) -> Conflict:
    return session.scalars(
        select(Conflict).where(Conflict.member_id == "SYN-001", Conflict.key == "furosemide")
    ).one()


# --- acceptance -------------------------------------------------------------------------------


def test_raymond_has_an_open_furosemide_conflict_and_no_auto_resolution(
    facts_db: Session, clock: FixedClock
) -> None:
    conflict = furosemide_conflict(facts_db)

    assert (conflict.fact_type, conflict.kind, conflict.status) == ("medication", "dose", "open")
    assert (conflict.resolution, conflict.resolved_by, conflict.resolved_at) == (None, None, None)
    facts = [facts_db.get(Fact, i) for i in conflict_fact_ids(facts_db, conflict.id)]
    assert sorted((f.source_system, f.value["strength"]) for f in facts if f) == [
        ("ccda", "80 mg"),
        ("pharmacy_ncpdp", "40 mg"),
    ]
    assert not facts_db.scalars(select(Fact).where(Fact.status == "cm_confirmed")).all()

    refresh_facts(facts_db, clock)  # re-running never resolves or duplicates
    assert furosemide_conflict(facts_db).status == "open"


def test_raymond_furosemide_covered_through_and_no_80_mg_fill(facts_db: Session) -> None:
    fills = facts_db.scalars(
        select(Fact).where(
            Fact.member_id == "SYN-001",
            Fact.type == "medication",
            Fact.source_system == "pharmacy_ncpdp",
        )
    ).all()
    furosemide = [f for f in fills if f.key == "furosemide"]

    assert [(f.value["strength"], f.value["covered_through"]) for f in furosemide] == [
        ("40 mg", "2026-10-30")
    ]
    assert not [f for f in fills if f.value["strength"] == "80 mg"]
    (arni,) = [f for f in fills if f.key == "sacubitril / valsartan"]
    assert (
        arni.value["dispensed"],
        arni.value["covered_through"],
        arni.value["reject_reason"],
    ) == (False, None, "PA required")


def test_raymond_discharge_summary_is_requested_not_received(
    facts_db: Session, clock: FixedClock
) -> None:
    documents = member_snapshot(facts_db, "SYN-001", clock=clock).documents

    (summary,) = [d for d in documents if d.type == "discharge_summary"]
    assert (summary.status, summary.received_at, summary.facility) == (
        "requested",
        None,
        "St Brigid Regional",
    )
    assert summary.requested_at == datetime(2026, 11, 7, 15, 2, tzinfo=PLAN_TZ)
    assert [(d.type, d.status) for d in documents if d.type == "medication_list"] == [
        ("medication_list", "received")
    ]


def test_raymond_contact_ladder_order(facts_db: Session, clock: FixedClock) -> None:
    ladder = member_snapshot(facts_db, "SYN-001", clock=clock).contacts

    assert [(c.number, c.confidence, c.owner) for c in ladder] == [
        ("555-0142", Decimal("0.820"), "self"),
        ("555-0143", Decimal("0.700"), "representative"),
        ("555-0177", Decimal("0.350"), "self"),
    ]
    assert ladder[1].owner_name == "Joan Tull"
    assert ladder[0].confidence_factors["formula"] == "recency x reliability x outcome"


def test_kayla_sister_is_stored_but_not_authorised(facts_db: Session, clock: FixedClock) -> None:
    contacts = {c.number: c for c in member_snapshot(facts_db, "SYN-004", clock=clock).contacts}

    sister = contacts["555-0161"]
    assert (sister.owner, sister.authorised, sister.callable) == ("third_party", False, False)
    shelter = contacts["555-0160"]  # third party with a signed release
    assert (shelter.owner, shelter.authorised, shelter.callable) == ("third_party", True, True)


def test_kayla_housing_and_anh_hba1c_are_red(facts_db: Session, clock: FixedClock) -> None:
    housing = get_fact_or_unknown(facts_db, "SYN-004", "sdoh", "housing", clock=clock)
    hba1c = get_fact_or_unknown(facts_db, "SYN-002", "lab", "hba1c", clock=clock)

    assert isinstance(housing, Fact) and isinstance(hba1c, Fact)
    assert (housing.event_date, freshness(housing, clock)) == (date(2025, 12, 1), "red")
    assert hba1c.event_date == date(2026, 10, 2)
    assert (clock.now().date() - hba1c.event_date).days == 38
    assert freshness(hba1c, clock) == "red"


def test_raymond_appointment_is_unknown_because_practice_not_connected(
    facts_db: Session, clock: FixedClock
) -> None:
    appointment = get_fact_or_unknown(facts_db, "SYN-001", "appointment", None, clock=clock)

    assert isinstance(appointment, Unknown)
    assert (str(appointment), appointment.reason) == ("UNKNOWN", "practice not connected")
    assert freshness(appointment, clock) == "grey"


# --- rules ------------------------------------------------------------------------------------


def test_inpatient_claim_unknown_cites_claims_lag(facts_db: Session, clock: FixedClock) -> None:
    claim = get_fact_or_unknown(facts_db, "SYN-001", "event", "claim:inpatient", clock=clock)

    assert isinstance(claim, Unknown)
    assert claim.reason == "claims loaded through 2026-09-25"


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (0, "green"),
        (6, "green"),
        (7, "amber"),
        (30, "amber"),
        (31, "red"),
    ],
)
def test_freshness_bands_use_event_date(age: int, expected: str) -> None:
    clock = FixedClock()
    fact = SimpleNamespace(
        event_date=clock.now().date() - timedelta(days=age), loaded_at=clock.now()
    )
    assert freshness(fact, clock) == expected  # type: ignore[arg-type]


def test_freshness_ignores_loaded_at_and_undated_facts_are_grey() -> None:
    clock = FixedClock()
    old_event_loaded_now = SimpleNamespace(event_date=date(2026, 1, 1), loaded_at=clock.now())
    assert freshness(old_event_loaded_now, clock) == "red"  # type: ignore[arg-type]
    assert freshness(SimpleNamespace(event_date=None), clock) == "grey"  # type: ignore[arg-type]


def test_disconnected_numbers_score_below_0_1_and_are_not_callable(
    facts_db: Session, clock: FixedClock
) -> None:
    for member_id, number in (("SYN-003", "555-0110"), ("SYN-004", "555-0133")):
        contacts = {c.number: c for c in member_snapshot(facts_db, member_id, clock=clock).contacts}
        assert contacts[number].confidence < Decimal("0.1")
        assert not contacts[number].callable

    best_case = contact_confidence("pharmacy", date(2026, 11, 8), "disconnected", date(2026, 11, 9))
    assert best_case.confidence <= Decimal("0.09")


def test_hero_contact_confidences_are_within_0_02_of_the_annex(
    facts_db: Session, clock: FixedClock
) -> None:
    annex = {
        "555-0142": "0.82",
        "555-0143": "0.70",
        "555-0177": "0.35",
        "555-0121": "0.60",
        "555-0188": "0.72",
        "555-0160": "0.75",
        "555-0161": "0.40",
        "555-0155": "0.80",
    }
    scores = {
        c.number: c.confidence
        for m in ("SYN-001", "SYN-002", "SYN-003", "SYN-004", "SYN-005")
        for c in member_snapshot(facts_db, m, clock=clock).contacts
    }
    for number, expected in annex.items():
        assert abs(scores[number] - Decimal(expected)) <= Decimal("0.02"), number


def test_sms_consent_is_per_number(facts_db: Session, clock: FixedClock) -> None:
    darnell = {
        c.number: c.consent_sms for c in member_snapshot(facts_db, "SYN-003", clock=clock).contacts
    }
    anh = {
        c.number: c.consent_sms for c in member_snapshot(facts_db, "SYN-002", clock=clock).contacts
    }
    assert darnell == {"555-0188": False, "555-0110": False}
    assert anh == {"555-0121": True}


def test_expired_representative_consent_is_not_valid(facts_db: Session, clock: FixedClock) -> None:
    consents = member_snapshot(facts_db, "SYN-005", clock=clock).consents

    (rep,) = [c for c in consents if c.consent.type == "personal_representative"]
    assert (rep.consent.party_name, rep.consent.valid_to, rep.valid) == (
        "Mirlande Joseph",
        date(2026, 9, 30),
        False,
    )


def test_part2_notes_are_masked_but_primary_care_buprenorphine_is_visible(
    facts_db: Session, clock: FixedClock
) -> None:
    snapshot = member_snapshot(facts_db, "SYN-004", clock=clock)

    notes = snapshot.facts_of("event", "part2:counselling_note")
    assert len(notes) == 3 and all(n.masked and n.value["masked"] for n in notes)
    assert all("note_text" not in n.value for n in notes)
    (bup,) = [
        f
        for f in snapshot.facts_of("medication", "buprenorphine / naloxone")
        if f.fact.source_system == "pharmacy_ncpdp"
    ]
    assert not bup.masked and bup.value["strength"] == "8/2 mg"


def test_member_snapshot_has_every_section(facts_db: Session, clock: FixedClock) -> None:
    snapshot = member_snapshot(facts_db, "SYN-001", clock=clock)

    assert snapshot.member.member_id == "SYN-001"
    assert {f.fact.type for f in snapshot.facts} >= {
        "medication",
        "diagnosis",
        "event",
        "lab",
        "contact_point",
        "coverage",
        "care_gap",
        "consent",
        "sdoh",
        "preference",
    }
    assert snapshot.conflicts and snapshot.documents and snapshot.contacts
    assert snapshot.consents and snapshot.pending_links == []  # SYN-001-H already confirmed


def test_every_fact_carries_its_lineage(facts_db: Session) -> None:
    facts = facts_db.scalars(select(Fact)).all()
    assert facts
    for fact in facts:
        assert fact.source_system and fact.source_record_id and fact.load_id
        assert fact.source_row is not None and fact.loaded_at and fact.link_id
        assert fact.status in ("raw", "member_reported", "cm_confirmed")


def test_conflicts_appear_only_where_sources_disagree(
    facts_db: Session, generated_raw: Path
) -> None:
    manifest = json.loads((generated_raw / "MANIFEST.json").read_text(encoding="utf-8"))
    i02 = next(i for i in manifest["imperfections"] if i["id"] == "I-02")

    conflicts = facts_db.scalars(select(Conflict)).all()
    dose = sorted(c.member_id for c in conflicts if c.kind == "dose")
    assert dose == sorted(["SYN-001", *i02["background_members"]])
    presence = [(c.member_id, c.key) for c in conflicts if c.kind == "presence"]
    # Kayla's FQHC buprenorphine is missing from the psychiatric discharge medication list.
    assert presence == [("SYN-004", "buprenorphine / naloxone")]


# --- identity gating, immutability, idempotency -----------------------------------------------


def test_hospital_facts_wait_for_a_confirmed_identity_link(
    ingested: Session, clock: FixedClock
) -> None:
    run_matching(ingested, clock)
    refresh_facts(ingested, clock)

    sources = {
        f.source_system
        for f in ingested.scalars(
            select(Fact).where(Fact.member_id == "SYN-001", Fact.key == "furosemide")
        )
    }
    assert sources == {"pharmacy_ncpdp"}
    assert not ingested.scalars(select(Conflict).where(Conflict.member_id == "SYN-001")).all()
    pending = member_snapshot(ingested, "SYN-001", clock=clock).pending_links
    assert [(p.source_record_id, p.status) for p in pending] == [("SYN-001-H", "needs_review")]


def test_unmerge_hides_hospital_facts_without_deleting_them(
    facts_db: Session, clock: FixedClock
) -> None:
    link = facts_db.scalars(
        select(MemberLink).where(MemberLink.source_record_id == "SYN-001-H")
    ).one()
    stored = len(facts_db.scalars(select(Fact).where(Fact.link_id == link.id)).all())

    unmerge(facts_db, "SYN-001", link.id, "maria.cm", clock=clock)
    refresh_facts(facts_db, clock)

    snapshot = member_snapshot(facts_db, "SYN-001", clock=clock)
    assert {f.fact.source_system for f in snapshot.facts_of("medication", "furosemide")} == {
        "pharmacy_ncpdp"
    }
    assert len(facts_db.scalars(select(Fact).where(Fact.link_id == link.id)).all()) == stored


def test_facts_cannot_be_changed_or_deleted(facts_db: Session) -> None:
    fact = facts_db.scalars(select(Fact).where(Fact.key == "furosemide")).first()
    assert fact is not None

    fact.value = {"strength": "80 mg"}
    with pytest.raises(FactImmutableError):
        facts_db.flush()
    facts_db.rollback()

    facts_db.delete(facts_db.get(Fact, fact.id))
    with pytest.raises(FactImmutableError):
        facts_db.flush()
    facts_db.rollback()


def test_database_trigger_blocks_raw_sql_changes(facts_db: Session) -> None:
    fact_id = facts_db.scalars(select(Fact.id)).first()

    for statement in (
        "UPDATE facts SET key = 'x' WHERE id = :id",
        "DELETE FROM facts WHERE id = :id",
    ):
        with pytest.raises(DatabaseError, match="append-only"):
            facts_db.execute(text(statement), {"id": fact_id})
        facts_db.rollback()
    # The single permitted write: superseded_by, once, from NULL.
    other = facts_db.scalars(select(Fact.id).where(Fact.id != fact_id)).first()
    facts_db.execute(
        text("UPDATE facts SET superseded_by = :o WHERE id = :id"), {"o": other, "id": fact_id}
    )
    with pytest.raises(DatabaseError, match="append-only"):
        facts_db.execute(
            text("UPDATE facts SET superseded_by = NULL WHERE id = :id"), {"id": fact_id}
        )


def test_building_twice_creates_no_new_facts(facts_db: Session, clock: FixedClock) -> None:
    summary = build_facts(facts_db, clock)

    assert (summary.created, summary.superseded) == (0, 0)
    assert summary.unchanged > 1000


def test_corrections_create_a_new_fact_and_supersede_the_old(
    facts_db: Session, clock: FixedClock, landing: Path, generated_raw: Path, tmp_path: Path
) -> None:
    import csv

    from app.datalayer_mock.ingest import ingest_file

    (path,) = (generated_raw / "pharmacy").glob("pharmacy_ncpdp_*.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["member_id"] == "SYN-001" and row["drug_name"] == "Metoprolol succinate":
            row["prescriber"] = "Dr A. Lindqvist (corrected)"
    corrected = tmp_path / "pharmacy" / "pharmacy_ncpdp_20261109.csv"
    corrected.parent.mkdir()
    with corrected.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    ingest_file(facts_db, corrected, clock=clock, landing_root=landing)

    summary = build_facts(facts_db, clock)

    assert summary.superseded == 1
    versions = facts_db.scalars(
        select(Fact)
        .where(
            Fact.member_id == "SYN-001",
            Fact.key == "metoprolol succinate",
            Fact.source_system == "pharmacy_ncpdp",
        )
        .order_by(Fact.id)
    ).all()
    old, new = versions
    assert old.superseded_by == new.id and new.superseded_by is None
    assert old.value["prescriber"] == "Dr A. Lindqvist"


# --- conflict decisions -----------------------------------------------------------------------


def test_only_people_move_a_conflict_forward(facts_db: Session, clock: FixedClock) -> None:
    conflict = furosemide_conflict(facts_db)

    with pytest.raises(ConflictDecisionError):
        resolve_conflict(facts_db, conflict.id, "system:ai", {"dose": "80 mg"}, clock=clock)
    send_to_prescriber(facts_db, conflict.id, "maria.cm", clock=clock)
    later = FixedClock(REFERENCE_INSTANT + timedelta(hours=3))
    resolve_conflict(
        facts_db,
        conflict.id,
        "maria.cm",
        {"prescriber_decision": "furosemide 80 mg daily"},
        clock=later,
    )

    assert (conflict.status, conflict.resolved_by, conflict.resolved_at) == (
        "resolved",
        "maria.cm",
        later.now(),
    )
    assert conflict.resolution is not None
    assert conflict.resolution["prescriber_decision"] == "furosemide 80 mg daily"
    detect_conflicts(facts_db, clock)  # the same disagreement is not reopened
    assert (
        len(
            facts_db.scalars(
                select(Conflict).where(
                    Conflict.member_id == "SYN-001", Conflict.key == "furosemide"
                )
            ).all()
        )
        == 1
    )


def _diagnosis(fact_id: int, system: str, code: str, group: str) -> Any:
    return SimpleNamespace(
        id=fact_id,
        member_id="SYN-900",
        type="diagnosis",
        key=code,
        source_system=system,
        value={"condition_group": group, "mapped": True},
    )


def test_diagnosis_conflict_when_sources_code_a_condition_differently() -> None:
    findings = diagnosis_findings(
        [
            _diagnosis(1, "claims_837", "N18.31", "CKD"),
            _diagnosis(2, "ccda", "N18.4", "CKD"),
            _diagnosis(3, "claims_837", "I10", "hypertension"),
            _diagnosis(4, "ccda", "I10", "hypertension"),
        ]
    )

    assert [(f.key, f.kind, f.fact_ids) for f in findings] == [("CKD", "code", (1, 2))]


def test_one_source_changing_codes_over_time_is_not_a_conflict() -> None:
    findings = diagnosis_findings(
        [
            _diagnosis(1, "claims_837", "J45.51", "asthma"),
            _diagnosis(2, "claims_837", "J45.41", "asthma"),
        ]
    )
    assert findings == []


@pytest.mark.parametrize(
    ("kind", "age", "value", "expected"),
    [
        ("sdoh", 150, {}, "green"),  # 5 months
        ("sdoh", 250, {}, "amber"),  # Raymond's HRA, 4 Mar: "amber (8 months)"
        ("sdoh", 272, {}, "red"),  # Rose-Marie's caregiver screen, 10 Feb: "red (9 months)"
        ("care_gap", 312, {"status": "open", "due_date": "2026-12-31"}, "green"),  # open, ahead
        ("care_gap", 40, {"status": "open", "due_date": "2026-10-01"}, "red"),  # deadline gone
        ("service", 31, {}, "green"),  # transport no-show last month
        ("service", 75, {}, "amber"),
        ("service", 120, {}, "red"),
    ],
)
def test_freshness_depends_on_the_kind_of_fact(
    kind: str, age: int, value: dict[str, str], expected: str
) -> None:
    clock = FixedClock()
    fact = SimpleNamespace(
        type=kind, value=value, event_date=clock.now().date() - timedelta(days=age)
    )
    assert freshness(fact, clock) == expected  # type: ignore[arg-type]

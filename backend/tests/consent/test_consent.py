import csv
import io
import re
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.consent import policy
from app.core.clock import FixedClock
from app.datalayer_mock.ingest import ingest_file
from app.facts import refresh_facts
from app.workbench.models import AuditEvent
from tests.api.conftest import Api

APP_DIR = Path(__file__).resolve().parents[2] / "app"
DIRECT_CHECKS = [
    re.compile(r"\.authorised\b"),
    re.compile(r"\.consent_sms\b"),
    re.compile(r"\.is_valid\("),
    re.compile(r"sensitivity\s*[!=]="),
    re.compile(r'\.type\s*==\s*"(tcpa_sms|part2|personal_representative|third_party_release)"'),
    re.compile(r"consent_type\s*=="),
]


def test_consent_is_checked_in_one_place() -> None:
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if path.parent.name == "consent":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if any(pattern.search(line) for pattern in DIRECT_CHECKS):
                offenders.append(f"{path.relative_to(APP_DIR)}:{number}: {line.strip()}")
    assert offenders == [], "consent checks outside app/consent/policy.py:\n" + "\n".join(offenders)


def test_policy_decisions_for_the_heroes(api: Api) -> None:
    clock = FixedClock()
    with api.session() as session:
        assert not policy.can_sms(session, "SYN-003", "555-0188", clock=clock)
        assert policy.can_sms(session, "SYN-002", "555-0121", clock=clock)
        assert not policy.can_call(session, "SYN-004", "555-0161", clock=clock)  # sister
        assert policy.can_call(session, "SYN-004", "555-0160", clock=clock)  # shelter, release
        assert policy.program_sensitivity("New Dawn Recovery") == "part2"
        assert policy.program_sensitivity("Some Other Program") == "unverified"


# --- Part 2 -----------------------------------------------------------------------------------


def _add_unknown_program_note(api: Api, generated_raw: Path, tmp_path: Path) -> None:
    (source,) = (generated_raw / "part2").glob("new_dawn_notes_*.csv")
    rows = source.read_text(encoding="utf-8").splitlines()
    extra = (
        "SYN-P2N-000099,SYN-004,Riverbend Wellness Collective,2026-10-27,counselling,"
        "K. Ortiz,Session note from a program not yet classified.,Y"
    )
    target = tmp_path / "part2" / "new_dawn_notes_20261109.csv"
    target.parent.mkdir()
    target.write_text("\n".join([*rows, extra]) + "\n", encoding="utf-8")
    clock = FixedClock()
    with api.session() as session:
        assert (
            ingest_file(session, target, clock=clock, landing_root=tmp_path / "landing").status
            == "PASS"
        )
        refresh_facts(session, clock)
        session.commit()


def test_part2_tagging_buprenorphine_visible_notes_masked_unknown_program_masked(
    api: Api, generated_raw: Path, tmp_path: Path
) -> None:
    _add_unknown_program_note(api, generated_raw, tmp_path)
    alma = api.as_("alma")

    facts = api.client.get("/members/SYN-004/360", headers=alma).json()["facts"]

    bup = [
        f
        for f in facts
        if f["key"] == "buprenorphine / naloxone" and f["source_system"] == "pharmacy_ncpdp"
    ]
    assert bup and not bup[0]["masked"] and bup[0]["value"]["strength"] == "8/2 mg"
    notes = [f for f in facts if f["key"] == "part2:counselling_note"]
    assert len(notes) == 4 and all(n["masked"] for n in notes)
    assert all("note_text" not in n["value"] for n in notes)

    revealed = api.client.post(
        "/members/SYN-004/part2/reveal", json={"reason": "coordinate MOUD"}, headers=alma
    ).json()
    programs = {n["program"] for n in revealed["notes"]}
    assert programs == {"New Dawn Recovery"}  # the unverified program stays masked
    assert len(revealed["notes"]) == 3


# --- minimum necessary -------------------------------------------------------------------------


def test_call_agent_cannot_read_medications(api: Api) -> None:
    sam = api.as_("sam")

    assert api.client.get("/members/SYN-001/medications", headers=sam).status_code == 403
    assert api.client.get("/members/SYN-001/360", headers=sam).status_code == 403
    card = api.client.get("/members/SYN-001/contact-card", headers=sam)
    assert card.status_code == 200
    body = card.json()
    assert set(body) == {"member_id", "name", "dob", "contacts", "why_we_called", "assigned_cm"}
    assert not re.search(r"furosemide|heart|discharge|diuretic", card.text, re.I)
    meds = api.client.get("/members/SYN-001/medications", headers=api.as_("maria")).json()
    assert any(m["key"] == "furosemide" for m in meds)


# --- audit ------------------------------------------------------------------------------------


def test_app_db_user_cannot_update_or_delete_audit_rows(api: Api) -> None:
    api.client.get("/members/SYN-004/360", headers=api.as_("alma"))  # writes an audit row
    with api.session() as session:
        row_id = session.scalars(select(AuditEvent.id)).first()
        for statement in (
            "UPDATE audit_events SET actor = 'mallory' WHERE id = :id",
            "DELETE FROM audit_events WHERE id = :id",
        ):
            with pytest.raises(DatabaseError, match="append-only"):
                session.execute(text(statement), {"id": row_id})
            session.rollback()


def test_supervisor_reads_and_exports_the_audit_trail(api: Api) -> None:
    api.client.get("/members/SYN-004/360", headers=api.as_("alma"))
    janet = api.as_("janet")

    rows = api.client.get("/audit?member_id=SYN-004", headers=janet).json()
    assert [(r["actor"], r["action"]) for r in rows] == [("alma", "view_360")]
    exported = api.client.get("/audit?member_id=SYN-004&format=csv", headers=janet)
    assert exported.headers["content-type"].startswith("text/csv")
    table = list(csv.reader(io.StringIO(exported.text)))
    assert table[0][:4] == ["id", "at", "actor", "action"] and table[1][2:4] == ["alma", "view_360"]
    assert api.client.get("/audit", headers=api.as_("maria")).status_code == 403

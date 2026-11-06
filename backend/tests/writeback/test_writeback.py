from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.core.clock import REFERENCE_INSTANT, FixedClock
from app.encounters.models import Notification
from app.facts.models import Conflict, Fact
from app.writeback.models import WritebackOutbox
from tests.api.conftest import Api

MEDS = [
    "loop_diuretic",
    "hf_therapy",
    "beta_blocker",
    "discharge_med_list",
    "supply_on_hand",
    "pharmacy",
]


def ready_to_save(api: Api) -> int:
    """Raymond's call: duplicate confirmed, connected, verified, wrapped, meds confirmed."""
    maria = api.as_("maria")
    link_id = api.client.get("/members/SYN-001/360", headers=maria).json()["pending_links"][0]["id"]
    api.client.post(f"/members/SYN-001/links/{link_id}/confirm", headers=maria)
    encounter = api.client.post(
        "/encounters", json={"member_id": "SYN-001", "number": "555-0142"}, headers=maria
    ).json()
    eid: int = encounter["id"]
    api.client.post(f"/encounters/{eid}/verify-identity", headers=maria)
    api.client.post(
        f"/encounters/{eid}/wrap-up", json={"notes": "Reached Raymond and Joan."}, headers=maria
    )
    for field_id in MEDS:
        api.client.post(
            f"/encounters/{eid}/fields/{field_id}/confirm",
            json={"time_on_field_ms": 3000},
            headers=maria,
        )
    return eid


def save(api: Api, eid: int, body: dict[str, Any] | None = None) -> Any:
    return api.client.post(f"/encounters/{eid}/save", json=body, headers=api.as_("maria"))


def cm_entries(api: Api, member_id: str = "SYN-001") -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = api.cm.get(f"/admin/entries?member_id={member_id}").json()
    return entries


def run_writeback(api: Api, minutes_later: float) -> dict[str, Any]:
    api.set_clock(FixedClock(REFERENCE_INSTANT + timedelta(minutes=minutes_later)))
    body: dict[str, Any] = api.client.post("/admin/writeback/run", headers=api.as_("janet")).json()
    return body


def confirmed_facts(api: Api) -> list[Fact]:
    with api.session() as session:
        return list(
            session.scalars(
                select(Fact).where(Fact.member_id == "SYN-001", Fact.status == "cm_confirmed")
            )
        )


# --- acceptance -------------------------------------------------------------------------------


def test_save_while_cm_is_down_syncs_exactly_once_when_it_returns(api: Api) -> None:
    eid = ready_to_save(api)
    api.cm.post("/admin/mode", json={"mode": "down"})

    saved = save(api, eid).json()

    assert saved["status"] == "syncing"
    assert cm_entries(api) == [] and confirmed_facts(api) == []
    assert run_writeback(api, 1)["retrying"]  # still down: backs off

    api.cm.post("/admin/mode", json={"mode": "up"})
    result = run_writeback(api, 10)
    assert len(result["synced"]) == 1
    run_writeback(api, 60)  # nothing left to send

    entries = cm_entries(api)
    assert len(entries) == 1 and entries[0]["note"]["body"] == "Reached Raymond and Joan."
    status = api.client.get(f"/encounters/{eid}", headers=api.as_("maria")).json()["status"]
    assert status == "synced"
    assert len(confirmed_facts(api)) == 6


def test_saving_twice_with_the_same_payload_creates_one_record(api: Api) -> None:
    eid = ready_to_save(api)

    first, second = save(api, eid).json(), save(api, eid).json()

    assert first["status"] == second["status"] == "synced"
    assert len(cm_entries(api)) == 1
    with api.session() as session:
        assert len(session.scalars(select(WritebackOutbox)).all()) == 1


def test_a_retried_write_with_the_same_key_is_not_duplicated(api: Api) -> None:
    payload = {"note": {"body": "x"}, "assessment": {}, "tasks": []}
    version = api.cm.get("/members/SYN-009/record").json()["version"]
    first = api.cm.put(
        "/members/SYN-009/entries/key-1", json=payload, headers={"If-Match": str(version)}
    )
    retry = api.cm.put(
        "/members/SYN-009/entries/key-1", json=payload, headers={"If-Match": str(version)}
    )

    assert (first.status_code, retry.status_code) == (201, 200)
    assert retry.json()["status"] == "duplicate"
    assert len(cm_entries(api, "SYN-009")) == 1


def test_version_conflict_returns_both_versions_and_writes_nothing(api: Api) -> None:
    eid = ready_to_save(api)
    api.cm.post("/admin/touch/SYN-001")  # someone else edited the CM record

    response = save(api, eid)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert (detail["base_version"], detail["current_version"]) == (1, 2)
    assert detail["ours"]["note"]["body"] == "Reached Raymond and Joan."
    assert detail["theirs"]["version"] == 2
    assert cm_entries(api) == [] and confirmed_facts(api) == []
    with api.session() as session:
        assert session.scalars(select(WritebackOutbox)).all() == []
    assert (
        api.client.get(f"/encounters/{eid}", headers=api.as_("maria")).json()["status"] == "wrapped"
    )

    # After reviewing both versions, the nurse saves against the newer one.
    assert save(api, eid, {"acknowledged_version": 2}).json()["status"] == "synced"
    assert len(cm_entries(api)) == 1


# --- retries, alerts, conflicts closing -------------------------------------------------------


def test_after_two_hours_of_failures_a_supervisor_is_alerted(api: Api) -> None:
    eid = ready_to_save(api)
    api.cm.post("/admin/mode", json={"mode": "down"})
    save(api, eid)

    result: dict[str, Any] = {}
    for minutes in (1, 3, 7, 15, 31, 61, 91, 121):
        result = run_writeback(api, minutes)
    assert len(result["alerted"]) == 1
    with api.session() as session:
        (alert,) = session.scalars(
            select(Notification).where(Notification.kind == "writeback_failed")
        )
        outbox = session.scalars(select(WritebackOutbox)).one()
    assert alert.recipient == "janet" and outbox.status == "alerted"
    assert outbox.attempts == 9  # first try + 8 retries with growing gaps


def test_backoff_doubles_between_attempts(api: Api) -> None:
    eid = ready_to_save(api)
    api.cm.post("/admin/mode", json={"mode": "down"})
    save(api, eid)
    gaps = []
    for minutes in (1, 3, 7):
        run_writeback(api, minutes)
        with api.session() as session:
            outbox = session.scalars(select(WritebackOutbox)).one()
            gaps.append((outbox.next_attempt_at - REFERENCE_INSTANT).total_seconds() / 60 - minutes)
    assert gaps == [1.0, 2.0, 4.0]


def test_resolved_conflicts_close_when_the_save_syncs(api: Api) -> None:
    eid = ready_to_save(api)
    maria = api.as_("maria")
    conflict_id = api.client.get("/members/SYN-001/360", headers=maria).json()["conflicts"][0]["id"]

    nurse_only = api.client.post(
        f"/encounters/{eid}/conflicts/{conflict_id}/resolution",
        json={"resolution": "takes 80 mg"},
        headers=maria,
    )
    assert nurse_only.status_code == 422  # medication: the prescriber decides
    api.client.post(
        f"/encounters/{eid}/conflicts/{conflict_id}/resolution",
        json={
            "resolution": "Prescriber confirmed furosemide 80 mg daily",
            "decided_by_prescriber": True,
        },
        headers=maria,
    )
    with api.session() as session:
        assert session.get(Conflict, conflict_id).status == "open"  # type: ignore[union-attr]

    save(api, eid)

    with api.session() as session:
        conflict = session.get(Conflict, conflict_id)
        assert conflict is not None and conflict.status == "resolved"
        assert conflict.resolution is not None and conflict.resolution["decided_by_prescriber"]
        sources = session.scalars(
            select(Fact).where(Fact.member_id == "SYN-001", Fact.key == "furosemide")
        ).all()
    assert len(sources) >= 2  # source Facts are never deleted

"""Demo mode: build, clock steps, operator toggles. Each toggle goes through the real path."""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.core.clock import REFERENCE_INSTANT
from app.datalayer_mock.ingest.models import PASS, QUARANTINE, Load
from app.demo.build import build
from app.demo.state import load_state
from app.encounters.models import Task
from tests.demo.conftest import DemoApi, demo_settings
from tests.writeback.test_writeback import MEDS


def queue(demo: DemoApi, user: str = "maria") -> dict[str, Any]:
    body: dict[str, Any] = demo.client.get("/queue", headers=demo.as_(user)).json()
    return body


def raymond_call_wrapped(demo: DemoApi) -> int:
    """Maria's happy path up to wrap-up: tasks are created from Raymond's signals."""
    maria = demo.as_("maria")
    link = demo.client.get("/members/SYN-001/360", headers=maria).json()["pending_links"][0]
    demo.client.post(f"/members/SYN-001/links/{link['id']}/confirm", headers=maria)
    eid: int = demo.client.post(
        "/encounters", json={"member_id": "SYN-001", "number": "555-0142"}, headers=maria
    ).json()["id"]
    demo.client.post(f"/encounters/{eid}/verify-identity", headers=maria)
    demo.client.post(
        f"/encounters/{eid}/wrap-up", json={"notes": "Reached Raymond."}, headers=maria
    )
    for field_id in MEDS:
        demo.client.post(
            f"/encounters/{eid}/fields/{field_id}/confirm",
            json={"time_on_field_ms": 3000},
            headers=maria,
        )
    return eid


def tasks(demo: DemoApi) -> list[dict[str, Any]]:
    body: list[dict[str, Any]] = demo.client.get("/tasks", headers=demo.as_("maria")).json()
    return body


# --- build ------------------------------------------------------------------------------------


def test_two_builds_give_identical_queue_output(demo_template: Path, tmp_path: Path) -> None:
    again = tmp_path / "again"
    build(demo_settings(again), log=lambda _line: None)
    first = (demo_template / "queue_snapshot.json").read_text(encoding="utf-8")
    second = (again / "queue_snapshot.json").read_text(encoding="utf-8")
    assert first == second
    rows = json.loads(first)["rows"]
    assert [r["member_id"] for r in rows[:2]] == ["SYN-001", "SYN-004"]


def test_build_freezes_the_clock_and_keeps_a_pristine_copy(demo: DemoApi) -> None:
    assert load_state(demo.settings).instant == REFERENCE_INSTANT
    assert demo.settings.demo_pristine_db.is_file()
    state = demo.client.get("/demo/state", headers=demo.as_("janet")).json()
    assert state["instant"] == "2026-11-09T08:00:00-05:00"
    assert [s["id"] for s in state["steps"] if s["available"]] == ["mon_1400", "tue_1100"]


def test_sign_in_users_are_listed_only_in_demo_mode(demo: DemoApi) -> None:
    config = demo.client.get("/demo/config").json()
    assert config["demo_mode"] is True
    assert [u["username"] for u in config["users"]][:3] == ["maria", "devon", "alma"]


def test_demo_routes_are_hidden_without_demo_mode(client: Any) -> None:
    assert client.get("/demo/config").json() == {"demo_mode": False, "users": []}


# --- clock ------------------------------------------------------------------------------------


def test_advancing_to_1400_loads_the_fill_and_turns_the_furosemide_task_green(
    demo: DemoApi,
) -> None:
    raymond_call_wrapped(demo)
    before = {t["title"]: t for t in tasks(demo)}
    diuretic = next(t for t in before.values() if "loop-diuretic" in t["title"])
    assert diuretic["status"] == "open"

    result = demo.post("/demo/clock/advance/mon_1400")

    assert diuretic["id"] in result["resolved_tasks"]  # type: ignore[operator]
    after = {t["id"]: t for t in tasks(demo)}[diuretic["id"]]
    assert after["status"] == "done"
    assert "Furosemide 80 mg filled 2026-11-09" in after["resolution"]
    assert after["resolution_fact_ids"]
    by_kind = {t["kind"]: t for t in tasks(demo)}
    assert by_kind["coverage_request"]["status"] == "open"  # approval only comes on Tuesday
    # The call answered the transition-contact signal, but a fill does not book a visit:
    # tasks from other rules are closed by a person, never by unrelated data.
    assert by_kind["pcp_visit_ride"]["status"] == "open"
    assert by_kind["hie_requery"]["status"] == "open"
    header = queue(demo)["header"]
    assert header["now"].startswith("2026-11-09T14:00")


def test_tuesday_1100_brings_the_coverage_approval(demo: DemoApi) -> None:
    raymond_call_wrapped(demo)
    demo.post("/demo/clock/advance/tue_1100")  # passes 14:00 Monday on the way
    by_kind = {t["kind"]: t for t in tasks(demo)}
    assert by_kind["prescriber_message"]["status"] == "done"
    assert by_kind["coverage_request"]["status"] == "done"
    assert "approved" in by_kind["coverage_request"]["resolution"]
    assert queue(demo)["header"]["scored_on"] == "2026-11-10"
    again = demo.client.post("/demo/clock/advance/mon_1400", headers=demo.as_("janet"))
    assert again.status_code == 409  # the clock never moves backwards


def test_reset_returns_to_monday_0800_with_the_pristine_data(demo: DemoApi) -> None:
    eid = raymond_call_wrapped(demo)
    demo.post("/demo/clock/advance/mon_1400")
    demo.post("/demo/feeds/pharmacy/pause")

    demo.post("/demo/clock/reset")

    assert load_state(demo.settings).instant == REFERENCE_INSTANT
    assert load_state(demo.settings).paused_feeds == []
    assert tasks(demo) == []
    gone = demo.client.get(f"/encounters/{eid}", headers=demo.as_("maria"))
    assert gone.status_code == 404
    assert queue(demo)["rows"][0]["member_id"] == "SYN-001"


# --- feeds ------------------------------------------------------------------------------------


def test_pausing_pharmacy_shows_a_stale_feed_and_holds_the_1400_file(demo: DemoApi) -> None:
    raymond_call_wrapped(demo)
    demo.post("/demo/feeds/pharmacy/pause")

    stale = queue(demo)["header"]["stale_feeds"]
    assert any(s["feed"] == "pharmacy" and "paused" in s["reason"] for s in stale)
    demo.post("/demo/clock/advance/mon_1400")
    assert next(t for t in tasks(demo) if "loop-diuretic" in t["title"])["status"] == "open"

    resumed = demo.post("/demo/feeds/pharmacy/resume")

    assert resumed["resolved_tasks"]  # the held fill arrived and closed the task
    assert not any(s["feed"] == "pharmacy" for s in queue(demo)["header"]["stale_feeds"])


def test_pausing_adt_shows_a_red_feed_and_a_discharge_can_be_added(demo: DemoApi) -> None:
    demo.post("/demo/feeds/adt/pause")
    devon = demo.as_("devon")
    view = demo.client.get("/members/SYN-003/360", headers=devon).json()
    assert view["adt_feed_stale"] is True
    assert any(s["feed"] == "adt" for s in queue(demo, "devon")["header"]["stale_feeds"])

    added = demo.client.post(
        "/members/SYN-003/discharges",
        json={"facility": "St Brigid Regional", "discharge_at": "2026-11-08T16:30:00-05:00"},
        headers=devon,
    )

    assert added.status_code == 201 and added.json()["status"] == "member_reported"
    facts = demo.client.get("/members/SYN-003/360", headers=devon).json()["facts"]
    assert any(f["key"] == "manual:discharge" for f in facts)


def test_a_bad_pharmacy_file_is_quarantined_and_the_last_good_load_stays(demo: DemoApi) -> None:
    result = demo.post("/demo/inject/bad-pharmacy-file")
    assert result["status"] == QUARANTINE and "schema change" in str(result["error"])
    with demo.session() as session:
        active = session.scalars(
            select(Load).where(Load.stream == "pharmacy_ncpdp", Load.is_active.is_(True))
        ).all()
    assert len(active) == 1 and active[0].status == PASS and active[0].id != result["load_id"]


def test_an_unknown_ndc_shows_its_raw_name_and_is_reported(demo: DemoApi) -> None:
    demo.post("/demo/inject/unknown-ndc")

    report = demo.client.get("/admin/unmapped-codes", headers=demo.as_("janet")).json()
    assert any(r["code"] == "99999-0042-30" and "Zorvantide" in r["display"] for r in report)
    facts = demo.client.get("/members/SYN-003/360", headers=demo.as_("devon")).json()["facts"]
    assert any("Zorvantide" in json.dumps(f["value"]) for f in facts)


# --- consent, CM platform, AI -----------------------------------------------------------------


def test_kaylas_part2_reveal_is_blocked_when_consent_expires_and_allowed_when_restored(
    demo: DemoApi,
) -> None:
    alma = demo.as_("alma")
    reveal = {"reason": "coordinate MOUD with the clinic"}
    demo.post("/demo/consent/kayla-part2/expire")
    blocked = demo.client.post("/members/SYN-004/part2/reveal", json=reveal, headers=alma)
    assert blocked.status_code == 403

    demo.post("/demo/consent/kayla-part2/restore")
    allowed = demo.client.post(
        "/members/SYN-004/part2/reveal", json=reveal, headers=demo.as_("alma")
    )
    assert allowed.status_code == 200 and allowed.json()["notes"]


def test_cm_down_then_up_syncs_the_save_exactly_once(demo: DemoApi) -> None:
    eid = raymond_call_wrapped(demo)
    demo.post("/demo/cm/down")
    saved = demo.client.post(f"/encounters/{eid}/save", headers=demo.as_("maria")).json()
    assert saved["status"] == "syncing"

    restored = demo.post("/demo/cm/up")

    assert len(restored["synced"]) == 1  # type: ignore[arg-type]
    entries = demo.cm.get("/admin/entries?member_id=SYN-001").json()
    assert len(entries) == 1
    status = demo.client.get(f"/encounters/{eid}", headers=demo.as_("maria")).json()["status"]
    assert status == "synced"


def test_a_record_version_conflict_returns_both_versions(demo: DemoApi) -> None:
    eid = raymond_call_wrapped(demo)
    demo.post("/demo/cm/conflict")
    response = demo.client.post(f"/encounters/{eid}/save", headers=demo.as_("maria"))
    assert response.status_code == 409 and response.json()["detail"]["current_version"] == 2


def test_the_ai_draft_can_be_made_to_time_out(demo: DemoApi) -> None:
    maria = demo.as_("maria")
    link = demo.client.get("/members/SYN-001/360", headers=maria).json()["pending_links"][0]
    demo.client.post(f"/members/SYN-001/links/{link['id']}/confirm", headers=maria)
    eid = demo.client.post(
        "/encounters", json={"member_id": "SYN-001", "number": "555-0142"}, headers=maria
    ).json()["id"]
    demo.client.post(f"/encounters/{eid}/verify-identity", headers=maria)
    demo.client.post(
        f"/encounters/{eid}/autosave",
        json={"payload": {"transcription_consent": True}},
        headers=maria,
    )
    demo.post("/demo/ai-timeout/on")

    result = demo.client.post(f"/encounters/{eid}/ai-draft", headers=maria).json()

    assert result["available"] is False and result["reason"] == "AI draft unavailable"
    with demo.session() as session:
        from app.ai_draft.models import AiLog

        assert session.scalars(select(AiLog.status)).one() == "timeout"


def test_operator_actions_are_audited(demo: DemoApi) -> None:
    demo.post("/demo/feeds/pharmacy/pause")
    rows = demo.client.get("/audit", headers=demo.as_("janet")).json()
    assert any(r["action"] == "demo_pause_pharmacy" for r in rows)


def test_task_resolution_needs_new_evidence(demo: DemoApi) -> None:
    """A signal that stops for another reason (no new Fact) does not close the task."""
    raymond_call_wrapped(demo)
    from app.encounters.service import resolve_tasks_by_data
    from app.signals.models import SignalRecord

    with demo.session() as session:
        session.execute(delete(SignalRecord))
        assert resolve_tasks_by_data(session, demo_clock_now(demo)) == []
        assert all(t.status == "open" for t in session.scalars(select(Task)))


def demo_clock_now(demo: DemoApi) -> Any:
    from app.demo.state import demo_clock

    return demo_clock(demo.settings)

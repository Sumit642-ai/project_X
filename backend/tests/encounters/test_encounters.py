from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.core.clock import REFERENCE_INSTANT, FixedClock
from app.encounters.models import Notification, SignalHandle
from app.encounters.service import CRISIS_LINES
from app.facts.models import Fact
from app.workbench.models import AuditEvent
from tests.api.conftest import Api

HIGH_RISK_MEDS = [
    "loop_diuretic",
    "hf_therapy",
    "beta_blocker",
    "discharge_med_list",
    "supply_on_hand",
    "pharmacy",
]


def confirm_raymond_duplicate(api: Api) -> None:
    maria = api.as_("maria")
    link_id = api.client.get("/members/SYN-001/360", headers=maria).json()["pending_links"][0]["id"]
    assert (
        api.client.post(f"/members/SYN-001/links/{link_id}/confirm", headers=maria).status_code
        == 200
    )


def call(api: Api, user: str, member: str, number: str, **extra: Any) -> Any:
    return api.client.post(
        "/encounters", json={"member_id": member, "number": number, **extra}, headers=api.as_(user)
    )


def raymond_call(api: Api) -> dict[str, Any]:
    confirm_raymond_duplicate(api)
    response = call(api, "maria", "SYN-001", "555-0142")
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def audit_rows(api: Api, action: str) -> list[AuditEvent]:
    with api.session() as session:
        return list(session.scalars(select(AuditEvent).where(AuditEvent.action == action)))


# --- acceptance -------------------------------------------------------------------------------


def test_raymond_template_counts(api: Api) -> None:
    encounter = raymond_call(api)

    assert encounter["outcome"] == "connected"
    assert encounter["counts"] == {"prefilled_fresh": 22, "prefilled_stale": 8, "live_only": 10}
    fields = {f["field_id"]: f for f in encounter["fields"]}
    assert len(fields) == 40
    for field in fields.values():
        if field["status"] == "prefilled_fresh":
            assert field["source_fact_ids"], field["field_id"]
    assert fields["home_address"]["reason"].startswith("source older than 180 days")
    assert fields["food_security"]["reason"] == "no feed supplies this yet: ask"
    assert {f for f, v in fields.items() if v["risk"] == "high"} == {
        *HIGH_RISK_MEDS,
        "allergies",
        "doses_taken",
    }


def test_bulk_confirm_refuses_medication_fields(api: Api) -> None:
    encounter = raymond_call(api)
    maria = api.as_("maria")
    api.client.post(f"/encounters/{encounter['id']}/verify-identity", headers=maria)

    refused = api.client.post(
        f"/encounters/{encounter['id']}/fields/bulk-confirm",
        json={"field_ids": ["full_name", "loop_diuretic"]},
        headers=maria,
    )
    assert refused.status_code == 422
    assert "loop_diuretic" in refused.json()["detail"]["reason"]

    low_risk = [
        f["field_id"]
        for f in encounter["fields"]
        if f["status"] == "prefilled_fresh" and f["risk"] == "low"
    ]
    accepted = api.client.post(
        f"/encounters/{encounter['id']}/fields/bulk-confirm",
        json={"field_ids": low_risk},
        headers=maria,
    )
    assert accepted.status_code == 200 and len(low_risk) == 16


def test_dialing_a_disconnected_number_reranks_darnells_ladder(api: Api) -> None:
    response = call(api, "devon", "SYN-003", "555-0110")

    assert response.json()["outcome"] == "disconnected"
    plan = api.client.get("/members/SYN-003/call-plan", headers=api.as_("devon")).json()
    numbers = [(e["number"], e["channel"]) for e in plan["ladder"]]
    assert numbers[0] == ("555-0188", "phone")
    disconnected = next(e for e in plan["ladder"] if e["number"] == "555-0110")
    assert float(disconnected["confidence"]) < 0.1 and not disconnected["callable"]
    with api.session() as session:
        attempt = session.scalars(
            select(Fact).where(Fact.member_id == "SYN-003", Fact.source_system == "cm_workbench")
        ).one()
        assert attempt.value["outcome"] == "disconnected"


def test_sms_without_tcpa_consent_is_blocked_and_audited(api: Api) -> None:
    response = api.client.post(
        "/members/SYN-003/sms", json={"number": "555-0188", "text": "Hi"}, headers=api.as_("devon")
    )

    assert response.status_code == 403
    assert "no TCPA consent" in response.json()["detail"]["reason"]
    (row,) = audit_rows(api, "sms_blocked")
    assert (row.actor, row.object_id, row.member_id) == ("devon", "555-0188", "SYN-003")
    # No override exists: extra fields are ignored and the block still applies.
    again = api.client.post(
        "/members/SYN-003/sms",
        json={"number": "555-0188", "text": "Hi", "override": True},
        headers=api.as_("devon"),
    )
    assert again.status_code == 403


def test_inbound_call_from_555_0188_routes_to_devon(api: Api) -> None:
    body = api.client.post(
        "/inbound-call", json={"from_number": "555-0188"}, headers=api.as_("sam")
    ).json()

    assert (body["matched"], body["member_id"], body["route_to"]) == (True, "SYN-003", "devon")
    assert body["why_we_called"].startswith("We called Darnell about:")
    assert "Verify name and date of birth" in body["why_we_called"]


def test_unmatched_inbound_call_offers_name_and_dob_search(api: Api) -> None:
    sam = api.as_("sam")
    body = api.client.post("/inbound-call", json={"from_number": "555-0199"}, headers=sam).json()

    assert (body["matched"], body["next_step"]) == (False, "search_by_name_and_dob")
    found = api.client.get("/members/search?last_name=pruitt&dob=1972-02-03", headers=sam).json()
    assert found == [{"member_id": "SYN-003", "name": "Darnell Pruitt"}]


# --- dialer, channels and guards --------------------------------------------------------------


def test_scripted_outcome_changes_by_weekday(api: Api) -> None:
    assert call(api, "devon", "SYN-003", "555-0188").json()["outcome"] == "no_answer"  # Monday
    api.set_clock(FixedClock(REFERENCE_INSTANT + timedelta(days=1)))
    assert call(api, "devon", "SYN-003", "555-0188").json()["outcome"] == "connected"  # Tuesday


def test_sms_appears_only_with_consent_and_text_comes_first(api: Api) -> None:
    rose = api.client.get("/members/SYN-005/call-plan", headers=api.as_("maria")).json()
    darnell = api.client.get("/members/SYN-003/call-plan", headers=api.as_("devon")).json()

    assert [(e["number"], e["channel"]) for e in rose["ladder"][:2]] == [
        ("555-0155", "sms"),
        ("555-0155", "phone"),
    ]
    assert rose["summary"] == "Text first, then call 19:00"
    assert all(e["channel"] != "sms" for e in darnell["ladder"])
    assert all(e["channel"] != "video" for e in rose["ladder"] + darnell["ladder"])


def test_unauthorised_number_cannot_be_dialled(api: Api) -> None:
    response = call(api, "alma", "SYN-004", "555-0161")  # Kayla's sister: no authorisation
    assert response.status_code == 403


def test_non_english_clinical_call_needs_an_interpreter(api: Api) -> None:
    janet = api.as_("janet")
    api.client.post(
        "/queue/reassign",
        json={
            "member_id": "SYN-002",
            "to_cm": "maria",
            "override_reason": "interim cover with interpreter",
        },
        headers=janet,
    )

    blocked = call(api, "maria", "SYN-002", "555-0121")
    assert blocked.status_code == 409
    assert "reschedule with an interpreter or reroute" in blocked.json()["detail"]["reason"]
    assert call(api, "maria", "SYN-002", "555-0121", interpreter_booked=True).status_code == 201


def test_calling_rose_marie_daughter_in_english_needs_no_interpreter(api: Api) -> None:
    assert call(api, "maria", "SYN-005", "555-0155").status_code == 201


def test_calls_wait_for_the_duplicate_decision(api: Api) -> None:
    response = call(api, "maria", "SYN-001", "555-0142")
    assert response.status_code == 409
    assert "possible duplicate" in response.json()["detail"]["reason"]


def test_crisis_line_number_is_not_a_member_contact(api: Api) -> None:
    with api.session() as session:
        numbers = {
            f.value.get("number")
            for f in session.scalars(select(Fact).where(Fact.type == "contact_point"))
        }
    assert all(line["number"] not in numbers for line in CRISIS_LINES)


# --- assessment, wrap-up and re-ranking -------------------------------------------------------


def test_health_details_wait_for_identity_verification(api: Api) -> None:
    encounter = raymond_call(api)
    response = api.client.post(
        f"/encounters/{encounter['id']}/fields/full_name/confirm", json={}, headers=api.as_("maria")
    )
    assert response.status_code == 409


def test_high_risk_fields_record_time_on_field(api: Api) -> None:
    encounter = raymond_call(api)
    maria = api.as_("maria")
    api.client.post(f"/encounters/{encounter['id']}/verify-identity", headers=maria)

    missing_time = api.client.post(
        f"/encounters/{encounter['id']}/fields/loop_diuretic/confirm", json={}, headers=maria
    )
    assert missing_time.status_code == 422
    done = api.client.post(
        f"/encounters/{encounter['id']}/fields/loop_diuretic/confirm",
        json={"answer": "Takes 40 mg, has 2 days left", "time_on_field_ms": 8200},
        headers=maria,
    ).json()
    assert (done["confirmed"], done["method"], done["time_on_field_ms"]) == (True, "single", 8200)


def test_wrap_up_creates_tasks_and_raymond_drops_to_t2(api: Api) -> None:
    encounter = raymond_call(api)
    maria = api.as_("maria")
    eid = encounter["id"]
    api.client.post(f"/encounters/{eid}/verify-identity", headers=maria)

    wrapped = api.client.post(
        f"/encounters/{eid}/wrap-up",
        json={"notes": "Reached Raymond; Joan manages pills."},
        headers=maria,
    ).json()

    kinds = {t["kind"] for t in wrapped["tasks"]}
    assert {"prescriber_message", "coverage_request", "hie_requery"} <= kinds
    assert all(t["signal_rule_id"] and t["signal_input_fact_ids"] for t in wrapped["tasks"])
    with api.session() as session:
        handled = {
            h.rule_id
            for h in session.scalars(
                select(SignalHandle).where(SignalHandle.member_id == "SYN-001")
            )
        }
    assert {
        "NO_CRITICAL_MED_ON_HAND",
        "DRUG_REJECTED_NO_REQUEST",
        "DISCHARGE_SUMMARY_MISSING",
    } <= handled

    row = next(
        r
        for r in api.client.get("/queue", headers=maria).json()["rows"]
        if r["member_id"] == "SYN-001"
    )
    assert row["tier"] == "T2"
    explain = api.client.get("/members/SYN-001/score/explain", headers=maria).json()
    assert explain["explanation"] == "35.2 + 9 + 20 + 8.2 = 72.4"
    assert explain["u_deadline"] == "0.0000"  # transition contact made


def test_save_requires_high_risk_confirmations_then_writes_confirmed_facts(api: Api) -> None:
    encounter = raymond_call(api)
    maria = api.as_("maria")
    eid = encounter["id"]
    api.client.post(f"/encounters/{eid}/verify-identity", headers=maria)
    api.client.post(f"/encounters/{eid}/wrap-up", json={}, headers=maria)

    refused = api.client.post(f"/encounters/{eid}/save", headers=maria)
    assert refused.status_code == 422
    for field_id in HIGH_RISK_MEDS:
        api.client.post(
            f"/encounters/{eid}/fields/{field_id}/confirm",
            json={"time_on_field_ms": 4000},
            headers=maria,
        )
    saved = api.client.post(f"/encounters/{eid}/save", headers=maria).json()

    assert saved["status"] == "synced"
    with api.session() as session:
        confirmed = session.scalars(
            select(Fact).where(Fact.member_id == "SYN-001", Fact.status == "cm_confirmed")
        ).all()
    assert len(confirmed) == 6
    assert all(f.value["source_fact_ids"] for f in confirmed)


def test_autosave_and_resume(api: Api) -> None:
    encounter = raymond_call(api)
    maria = api.as_("maria")
    api.client.post(
        f"/encounters/{encounter['id']}/autosave",
        json={
            "payload": {"notes": "Joan on speaker", "pane": "live", "transcription_consent": True}
        },
        headers=maria,
    )

    plan = api.client.get("/members/SYN-001/call-plan", headers=maria).json()
    assert plan["resumable_encounter_id"] == encounter["id"]
    resumed = api.client.get(f"/encounters/{encounter['id']}", headers=maria).json()
    assert resumed["autosave"]["pane"] == "live"
    assert (resumed["notes"], resumed["transcription_consent"]) == ("Joan on speaker", True)


def test_crisis_protocol_answers_immediately_and_notifies_supervisor(api: Api) -> None:
    encounter = raymond_call(api)

    body = api.client.post(f"/encounters/{encounter['id']}/crisis", headers=api.as_("maria")).json()

    assert body["supervisor_notified"] == ["janet"]
    assert body["transfer_lines"][0]["number"] == "988"
    assert body["instructions"][0] == "Stay on the line. Do not end the call."
    with api.session() as session:
        (note,) = session.scalars(select(Notification).where(Notification.kind == "crisis"))
        assert note.recipient == "janet"
    assert len(audit_rows(api, "crisis_protocol")) == 1

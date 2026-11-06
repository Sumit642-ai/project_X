import time
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.core.clock import REFERENCE_INSTANT, FixedClock
from app.facts.models import ConsentRecord, Fact
from app.workbench.models import Assignment, AuditEvent
from tests.api.conftest import Api


def queue(api: Api, user: str, cm: str = "me") -> dict[str, Any]:
    response = api.client.get(f"/queue?cm={cm}", headers=api.as_(user))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def audit_rows(api: Api, action: str) -> list[AuditEvent]:
    with api.session() as session:
        return list(session.scalars(select(AuditEvent).where(AuditEvent.action == action)))


# --- acceptance -------------------------------------------------------------------------------


def test_maria_sees_raymond_then_rose_marie(api: Api) -> None:
    body = queue(api, "maria")

    rows = body["rows"]
    assert [(r["member_id"], r["tier"]) for r in rows[:2]] == [("SYN-001", "T0"), ("SYN-005", "T1")]
    assert all(r["assigned_cm"] == "maria" for r in rows)
    raymond = rows[0]
    assert raymond["score"] == "93.4"
    assert raymond["why"][0] == "Furosemide ran out 2026-10-30; no fill since discharge"
    assert len(raymond["why"]) == 3
    assert raymond["next_best_action"]["text"].startswith("Confirm diuretic supply")
    assert raymond["next_best_action"]["reason"] == raymond["why"][0]
    assert raymond["due_at"] == "2026-11-10T22:00:00Z"
    assert raymond["due_tz"] == "America/New_York"
    assert raymond["duplicate"]["flagged"] is True
    assert raymond["duplicate"]["label"] == "flagged by data layer"
    header = body["header"]
    assert header["capacity"] == {"active": len(rows), "target": 45}
    assert sum(header["tier_counts"].values()) == len(rows)


def test_devon_sees_darnell_and_alma_sees_kayla(api: Api) -> None:
    devon = [r["member_id"] for r in queue(api, "devon")["rows"]]
    alma = [r["member_id"] for r in queue(api, "alma")["rows"]]

    assert devon[0] == "SYN-003" and "SYN-001" not in devon
    assert alma[0] == "SYN-004" and "SYN-003" not in alma


def test_kayla_part2_notes_are_masked_in_360(api: Api) -> None:
    body = api.client.get("/members/SYN-004/360", headers=api.as_("alma")).json()

    notes = [f for f in body["facts"] if f["key"] == "part2:counselling_note"]
    assert len(notes) == 3
    assert all(n["masked"] and n["value"]["masked"] for n in notes)
    assert all("note_text" not in n["value"] for n in notes)


def test_part2_reveal_with_expired_consent_is_refused(api: Api) -> None:
    with api.session() as session:  # test fixture: the Part 2 consent has lapsed
        consent = session.scalars(
            select(ConsentRecord).where(
                ConsentRecord.member_id == "SYN-004", ConsentRecord.type == "part2"
            )
        ).one()
        consent.valid_to = date(2026, 1, 31)
        session.commit()

    response = api.client.post(
        "/members/SYN-004/part2/reveal",
        json={"reason": "coordinate MOUD after discharge"},
        headers=api.as_("alma"),
    )

    assert response.status_code == 403
    assert "not valid" in response.json()["detail"]["reason"]
    (denied,) = audit_rows(api, "part2_reveal_denied")
    assert (denied.actor, denied.member_id) == ("alma", "SYN-004")
    assert audit_rows(api, "part2_reveal") == []


def test_part2_reveal_with_consent_returns_notes_and_audits(api: Api) -> None:
    response = api.client.post(
        "/members/SYN-004/part2/reveal",
        json={"reason": "coordinate MOUD after discharge"},
        headers=api.as_("alma"),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["notes"]) == 3 and body["notes"][0]["program"] == "New Dawn Recovery"
    assert body["notes"][0]["note_text"]
    assert "42 CFR Part 2" in body["redisclosure_notice"]
    (event,) = audit_rows(api, "part2_reveal")
    assert (event.id, event.actor, event.reason) == (
        body["audit_event_id"],
        "alma",
        "coordinate MOUD after discharge",
    )
    # The 360 stays masked after a reveal.
    after = api.client.get("/members/SYN-004/360", headers=api.as_("alma")).json()
    assert all(f["masked"] for f in after["facts"] if f["key"] == "part2:counselling_note")


def test_reassigning_an_ohio_member_to_priya_is_refused(api: Api) -> None:
    response = api.client.post(
        "/queue/reassign", json={"member_id": "SYN-002", "to_cm": "priya"}, headers=api.as_("janet")
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "priya is not licensed in OH (licensed: TX)"
    assert audit_rows(api, "reassignment") == []


def test_stale_pharmacy_feed_is_listed_when_31_hours_old(api: Api) -> None:
    api.set_clock(FixedClock(REFERENCE_INSTANT + timedelta(hours=31)))

    header = queue_with(api, api.as_("maria"))["header"]

    stale = {s["feed"]: s["reason"] for s in header["stale_feeds"]}
    assert "pharmacy" in stale
    assert stale["pharmacy"] == "last load 31 h ago (expected within 30 h)"


def queue_with(api: Api, headers: dict[str, str]) -> dict[str, Any]:
    response = api.client.get("/queue?cm=me", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_fresh_feeds_are_not_listed_at_0800(api: Api) -> None:
    stale = {s["stream"] for s in queue(api, "maria")["header"]["stale_feeds"]}
    assert stale == {"claims_837", "ltss_aide_hours"}  # data 45 and 32 days old


# --- auth and access --------------------------------------------------------------------------


def test_requests_need_a_signed_in_user(api: Api) -> None:
    assert api.client.get("/queue").status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert api.client.get("/queue", headers=bad).status_code == 401
    assert api.client.post("/auth/login", json={"username": "mallory"}).status_code == 401


def test_tokens_expire_on_the_clock(api: Api) -> None:
    headers = api.as_("maria")
    api.set_clock(FixedClock(REFERENCE_INSTANT + timedelta(hours=9)))
    assert api.client.get("/queue", headers=headers).status_code == 401


def test_case_managers_only_reach_their_own_members(api: Api) -> None:
    maria = api.as_("maria")
    assert api.client.get("/members/SYN-004/360", headers=maria).status_code == 403
    assert api.client.get("/queue?cm=alma", headers=maria).status_code == 403
    assert api.client.get("/members/SYN-001/360", headers=maria).status_code == 200


def test_call_agent_and_supervisor_roles(api: Api) -> None:
    sam, janet = api.as_("sam"), api.as_("janet")
    assert api.client.get("/queue", headers=sam).status_code == 403
    assert api.client.get("/members/SYN-001/360", headers=sam).status_code == 403
    assert api.client.get("/feeds/status", headers=sam).status_code == 200
    assert api.client.get("/members/SYN-004/360", headers=janet).status_code == 200
    assert (
        api.client.post(
            "/members/SYN-004/part2/reveal", json={"reason": "supervisor look"}, headers=janet
        ).status_code
        == 403
    )  # minimum necessary
    assert (
        api.client.post(
            "/queue/reassign",
            json={"member_id": "SYN-002", "to_cm": "maria"},
            headers=api.as_("maria"),
        ).status_code
        == 403
    )


def test_unknown_member_is_404(api: Api) -> None:
    assert api.client.get("/members/SYN-999/360", headers=api.as_("janet")).status_code == 404


# --- 360 contents -----------------------------------------------------------------------------


def test_raymond_360(api: Api) -> None:
    response = api.client.get("/members/SYN-001/360", headers=api.as_("maria"))
    body = response.json()

    assert body["since_last_contact"]["reference"] == "last answered call 2026-06-01"
    assert body["last_call_note"] == {
        "value": "UNKNOWN",
        "type": "call_note",
        "key": None,
        "reason": "no completed encounter recorded",
        "as_of": None,
    }
    assert {"type": "appointment", "reason": "practice not connected"}.items() <= body["unknowns"][
        0
    ].items()
    assert [c["number"] for c in body["contacts"]] == ["555-0142", "555-0143", "555-0177"]
    assert [(d["type"], d["status"]) for d in body["documents"]] == [
        ("discharge_summary", "requested")
    ]
    assert body["risk"] == {
        "value": "0.880",
        "basis": "plan",
        "verify": False,
        "model": "Evergreen readmission risk v3",
        "scored_at": "2026-11-01",
    }
    assert all(f["freshness"] in ("green", "amber", "red", "grey") for f in body["facts"])
    assert [p["source_record_id"] for p in body["pending_links"]] == ["SYN-001-H"]
    roles = {m["role"]: m["name"] for m in body["care_team"]}
    assert roles["PCP"] == "Dr A. Lindqvist" and roles["Representative"] == "Joan Tull"
    assert len(audit_rows(api, "view_360")) == 1


def test_kayla_contact_ladder_lists_unauthorised_sister_as_not_callable(api: Api) -> None:
    contacts = {
        c["number"]: c
        for c in api.client.get("/members/SYN-004/360", headers=api.as_("alma")).json()["contacts"]
    }

    assert (contacts["555-0161"]["callable"], contacts["555-0161"]["not_callable_reason"]) == (
        False,
        "not authorised",
    )
    assert contacts["555-0133"]["not_callable_reason"] == "disconnected"
    assert contacts["555-0160"]["callable"] is True


def test_darnell_without_pcp_shows_unknown(api: Api) -> None:
    body = api.client.get("/members/SYN-003/360", headers=api.as_("devon")).json()
    pcp = next(m for m in body["care_team"] if m["role"] == "PCP")
    assert pcp["name"]["value"] == "UNKNOWN"


def test_explain_endpoint(api: Api) -> None:
    body = api.client.get("/members/SYN-001/score/explain", headers=api.as_("maria")).json()
    assert body["explanation"] == "35.2 + 30 + 20 + 8.2 = 93.4"
    assert (body["tier"], body["deadline_source"], body["a_contact"]) == (
        "T0",
        "HF_DISCHARGE",
        "555-0142",
    )


# --- actions ----------------------------------------------------------------------------------


def test_confirming_raymonds_link_surfaces_the_furosemide_conflict(api: Api) -> None:
    maria = api.as_("maria")
    before = api.client.get("/members/SYN-001/360", headers=maria).json()
    assert before["conflicts"] == []
    link_id = before["pending_links"][0]["id"]

    response = api.client.post(f"/members/SYN-001/links/{link_id}/confirm", headers=maria)

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["decided_by"]) == ("confirmed", "maria")
    after = api.client.get("/members/SYN-001/360", headers=maria).json()
    assert [(c["key"], c["kind"], c["status"]) for c in after["conflicts"]] == [
        ("furosemide", "dose", "open")
    ]
    assert after["pending_links"] == []
    assert (
        api.client.get("/members/SYN-001/score/explain", headers=maria).json()["explanation"]
        == "35.2 + 30 + 20 + 8.2 = 93.4"
    )
    assert len(audit_rows(api, "link_confirmed")) == 1


def test_rejecting_a_link_is_audited(api: Api) -> None:
    alma = api.as_("alma")
    with api.session() as session:
        from app.datalayer_mock.identity.models import MemberLink

        link_id = session.scalars(
            select(MemberLink.id).where(MemberLink.source_record_id == "SYN-004-M")
        ).one()

    response = api.client.post(f"/members/SYN-004/links/{link_id}/reject", headers=alma)

    assert response.json()["status"] == "rejected"
    assert len(audit_rows(api, "link_rejected")) == 1
    again = api.client.post(f"/members/SYN-004/links/{link_id}/reject", headers=alma)
    assert again.status_code == 409


def _confirm_raymond(api: Api) -> int:
    maria = api.as_("maria")
    link_id = api.client.get("/members/SYN-001/360", headers=maria).json()["pending_links"][0]["id"]
    api.client.post(f"/members/SYN-001/links/{link_id}/confirm", headers=maria)
    conflicts = api.client.get("/members/SYN-001/360", headers=maria).json()["conflicts"]
    conflict_id: int = conflicts[0]["id"]
    return conflict_id


def test_member_report_is_stored_and_conflict_stays_open(api: Api) -> None:
    conflict_id = _confirm_raymond(api)

    response = api.client.post(
        f"/conflicts/{conflict_id}/member-reports",
        json={"value": "Takes two 40 mg tablets each morning"},
        headers=api.as_("maria"),
    )

    assert response.status_code == 201
    assert response.json()["conflict_status"] == "open"
    with api.session() as session:
        fact = session.get(Fact, response.json()["fact_id"])
        assert fact is not None
        assert (fact.status, fact.key, fact.value["reported"]) == (
            "member_reported",
            "furosemide",
            "Takes two 40 mg tablets each morning",
        )


def test_send_to_prescriber(api: Api) -> None:
    conflict_id = _confirm_raymond(api)

    response = api.client.post(
        f"/conflicts/{conflict_id}/send-to-prescriber", headers=api.as_("maria")
    )

    assert response.json()["status"] == "sent_to_prescriber"
    assert len(audit_rows(api, "sent_to_prescriber")) == 1


def test_not_for_me_moves_member_to_unassigned(api: Api) -> None:
    response = api.client.post(
        "/members/SYN-005/not-for-me",
        json={"reason": "family conflict of interest"},
        headers=api.as_("maria"),
    )

    assert response.json()["status"] == "declined"
    assert "SYN-005" not in [r["member_id"] for r in queue(api, "maria")["rows"]]
    assert "SYN-005" in [r["member_id"] for r in queue(api, "janet", "unassigned")["rows"]]
    (override,) = audit_rows(api, "override_not_for_me")
    assert override.reason == "family conflict of interest"


def test_reassign_checks_language_and_records_overrides(api: Api) -> None:
    janet = api.as_("janet")
    refused = api.client.post(
        "/queue/reassign", json={"member_id": "SYN-002", "to_cm": "maria"}, headers=janet
    )
    assert refused.status_code == 422
    assert "does not speak" in refused.json()["detail"]["reason"]

    allowed = api.client.post(
        "/queue/reassign",
        json={
            "member_id": "SYN-002",
            "to_cm": "maria",
            "override_reason": "interim cover with a Vietnamese interpreter",
        },
        headers=janet,
    )

    assert allowed.status_code == 200 and allowed.json()["cm_username"] == "maria"
    assert len(audit_rows(api, "reassignment")) == 1
    assert len(audit_rows(api, "override_language")) == 1
    assert "SYN-002" in [r["member_id"] for r in queue(api, "maria")["rows"]]


def test_reassign_to_a_matching_cm_closes_the_old_assignment(api: Api) -> None:
    response = api.client.post(
        "/queue/reassign", json={"member_id": "SYN-001", "to_cm": "devon"}, headers=api.as_("janet")
    )

    assert response.status_code == 200
    with api.session() as session:
        history = [
            (a.cm_username, a.status)
            for a in session.scalars(
                select(Assignment).where(Assignment.member_id == "SYN-001").order_by(Assignment.id)
            )
        ]
    assert history == [("maria", "reassigned"), ("devon", "active")]


def test_document_requery(api: Api) -> None:
    maria = api.as_("maria")
    doc_id = api.client.get("/members/SYN-001/360", headers=maria).json()["documents"][0]["id"]

    response = api.client.post(f"/documents/{doc_id}/requery", headers=maria)

    assert response.status_code == 202
    assert response.json()["requested_at"] == "2026-11-09T13:00:00Z"
    assert len(audit_rows(api, "document_requery")) == 1


def test_feeds_status(api: Api) -> None:
    rows = api.client.get("/feeds/status", headers=api.as_("janet")).json()
    by_stream = {r["stream"]: r for r in rows}
    assert by_stream["claims_837"]["data_as_of"] == "2026-09-25"
    assert by_stream["pharmacy_ncpdp"]["stale"] is False


def test_openapi_docs_are_served(api: Api) -> None:
    assert api.client.get("/docs").status_code == 200
    paths = api.client.get("/openapi.json").json()["paths"]
    assert {"/queue", "/members/{member_id}/360", "/queue/reassign"} <= set(paths)


# --- performance ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "user"), [("/queue?cm=me", "maria"), ("/members/SYN-001/360", "maria")]
)
def test_p95_under_300_ms(api: Api, path: str, user: str) -> None:
    headers = api.as_(user)
    api.client.get(path, headers=headers)  # warm up
    timings = []
    for _ in range(60):  # enough samples for a real 95th percentile
        started = time.perf_counter()
        assert api.client.get(path, headers=headers).status_code == 200
        timings.append(time.perf_counter() - started)
    p95 = sorted(timings)[int(len(timings) * 0.95) - 1]
    assert p95 < 0.300, f"p95 {p95 * 1000:.0f} ms"


def test_queue_rows_carry_plan_age_and_score_inputs(api: Api) -> None:
    body = queue(api, "maria")
    raymond = body["rows"][0]

    assert (raymond["lob"], raymond["age"]) == ("MA-PPO", 76)
    assert raymond["score_inputs"] == {"r": "0.880", "u": "1.0000", "m": "1.000", "a": "0.820"}
    assert body["header"]["now"] == "2026-11-09T08:00:00-05:00"


def test_360_header_has_plan_language_and_claims_stamp(api: Api) -> None:
    body = api.client.get("/members/SYN-005/360", headers=api.as_("maria")).json()

    assert (body["member"]["language"], body["member"]["proxy_language"]) == ("ht", "en")
    assert (body["member"]["plan"], body["member"]["age"]) == ("Evergreen", 84)
    assert body["claims_as_of"] == "2026-09-25"


def test_snooze_hides_member_until_return_date(api: Api) -> None:
    maria = api.as_("maria")
    too_far = api.client.post(
        "/members/SYN-005/snooze",
        json={"reason": "in hospital, family will call", "until": "2027-01-01"},
        headers=maria,
    )
    assert too_far.status_code == 422

    response = api.client.post(
        "/members/SYN-005/snooze",
        json={"reason": "in hospital, family will call", "until": "2026-11-12"},
        headers=maria,
    )

    assert response.status_code == 200
    assert "SYN-005" not in [r["member_id"] for r in queue(api, "maria")["rows"]]
    api.set_clock(FixedClock(REFERENCE_INSTANT + timedelta(days=3)))
    assert "SYN-005" in [r["member_id"] for r in queue_with(api, api.as_("maria"))["rows"]]
    assert len(audit_rows(api, "override_snooze")) == 1


def test_not_now_is_audited(api: Api) -> None:
    response = api.client.post(
        "/members/SYN-001/not-now",
        json={"reason": "member asked to call after 2pm", "rule_id": "NO_CRITICAL_MED_ON_HAND"},
        headers=api.as_("maria"),
    )

    assert response.status_code == 200
    (event,) = audit_rows(api, "override_not_now")
    assert event.detail == {"rule_id": "NO_CRITICAL_MED_ON_HAND"}

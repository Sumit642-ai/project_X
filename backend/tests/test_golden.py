"""Golden test: every number in the blueprint (annex.md) at 2026-11-09 08:00 America/New_York.

Where our computation differs from the annex, the test is xfail(strict=True) and names the
input that differs; nothing is tuned to force a match (score weights and confidence formulas
stay as specified).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.encounters.service import channel_ladder
from app.facts.snapshot import member_snapshot
from app.scoring.models import MemberScore
from app.scoring.service import explain
from tests.api.conftest import Api, api, api_template  # noqa: F401  (API fixtures)

NY = ZoneInfo("America/New_York")
CLOCK = FixedClock()

# --- Sheet 1 and the score worked examples ----------------------------------------------------

GOLDEN: dict[str, dict[str, Any]] = {
    "SYN-001": dict(r="0.88", u="1.0", m="1.0", a="0.82", score="93.4", tier="T0", h="33"),
    "SYN-004": dict(r="0.74", u="1.0", m="1.0", a="0.75", score="87.1", tier="T0", h="81"),
    "SYN-003": dict(r="0.71", u="0.6", m="1.0", a="0.72", score="73.6", tier="T1", h="105"),
    "SYN-005": dict(r="0.69", u="0.6", m="0.75", a="0.80", score="68.6", tier="T1", h=None),
    "SYN-002": dict(r="0.41", u="0.3", m="0.75", a="0.60", score="46.4", tier="T2", h=None),
}
# A comes from the contact-confidence formula (recency x reliability x outcome), calibrated to
# reproduce Raymond exactly. Not adjusted to match these two.
A_DIFFERS = {
    "SYN-005": "A = 0.85 recency (253 days) x 0.95 eligibility x 1.0 voicemail = 0.81, not 0.80",
    "SYN-002": "A = 0.625 recency (526 days) x 0.95 eligibility x 1.0 voicemail = 0.59, not 0.60",
}
DEADLINES = {
    # member: (deadline rule, local due time, hours h, U_deadline)
    "SYN-001": ("HF_DISCHARGE", datetime(2026, 11, 10, 17, 0, tzinfo=NY), "33", "0.725"),
    "SYN-004": ("FUH_DUE", datetime(2026, 11, 12, 17, 0, tzinfo=NY), "81", "0.325"),
    "SYN-003": ("FMC_DUE", datetime(2026, 11, 13, 17, 0, tzinfo=NY), "105", "0.125"),
}


@pytest.mark.parametrize(
    "member_id",
    [
        pytest.param(m, marks=pytest.mark.xfail(reason=A_DIFFERS[m], strict=True))
        if m in A_DIFFERS
        else m
        for m in GOLDEN
    ],
)
def test_scores_and_inputs_match_the_annex(scores: dict[str, MemberScore], member_id: str) -> None:
    row, want = scores[member_id], GOLDEN[member_id]
    assert (row.r, row.u, row.m, row.a) == tuple(Decimal(want[k]) for k in "ruma")
    assert (row.score, row.tier) == (Decimal(want["score"]), want["tier"])


@pytest.mark.parametrize("member_id", list(GOLDEN))
def test_tiers_match_the_annex(scores: dict[str, MemberScore], member_id: str) -> None:
    assert scores[member_id].tier == GOLDEN[member_id]["tier"]


@pytest.mark.parametrize("member_id", list(A_DIFFERS))
def test_where_scores_differ_only_contact_confidence_differs(
    scores: dict[str, MemberScore], member_id: str
) -> None:
    row, want = scores[member_id], GOLDEN[member_id]
    assert (row.r, row.u, row.m) == tuple(Decimal(want[k]) for k in "rum")
    assert abs(row.a - Decimal(want["a"])) == Decimal("0.01")
    with_annex_a = 40 * row.r + 30 * row.u + 20 * row.m + 10 * Decimal(want["a"])
    assert with_annex_a.quantize(Decimal("0.1")) == Decimal(want["score"])


def test_score_arithmetic_matches_the_worked_examples(
    scores: dict[str, MemberScore], morning: Session
) -> None:
    assert explain(morning, "SYN-001") == "35.2 + 30 + 20 + 8.2 = 93.4"
    assert explain(morning, "SYN-004") == "29.6 + 30 + 20 + 7.5 = 87.1"
    assert explain(morning, "SYN-003") == "28.4 + 18 + 20 + 7.2 = 73.6"


@pytest.mark.parametrize("member_id", list(DEADLINES))
def test_deadlines_hours_and_deadline_urgency(
    scores: dict[str, MemberScore], member_id: str
) -> None:
    rule, due, hours, u_deadline = DEADLINES[member_id]
    row = scores[member_id]
    assert row.deadline_source == rule
    assert row.deadline_at is not None and row.deadline_at.astimezone(NY) == due
    assert (row.hours_to_deadline, row.u_deadline) == (Decimal(hours), Decimal(u_deadline))


def test_no_deadline_is_scored_for_rose_marie_or_anh(scores: dict[str, MemberScore]) -> None:
    # SYN-005: the DME deadline is UM-owned; SYN-002: the PDC gap is outside 120 h.
    for member_id in ("SYN-005", "SYN-002"):
        assert scores[member_id].u_deadline == Decimal("0")


def test_heroes_rank_in_annex_order(scores: dict[str, MemberScore]) -> None:
    assert sorted(GOLDEN, key=lambda m: scores[m].rank) == list(GOLDEN)


# --- Sheet 1 duplicates: match confidences ----------------------------------------------------


def test_duplicate_match_confidences(morning: Session) -> None:
    raymond = member_snapshot(morning, "SYN-001", clock=CLOCK).pending_links
    kayla = member_snapshot(morning, "SYN-004", clock=CLOCK).pending_links
    assert [(link.source_record_id, round(link.confidence, 2)) for link in raymond] == [
        ("SYN-001-H", Decimal("0.86"))
    ]
    assert [(link.source_record_id, round(link.confidence, 2)) for link in kayla] == [
        ("SYN-004-M", Decimal("0.78"))
    ]
    for link in raymond + kayla:  # below 0.90: never merged automatically
        assert link.confidence < Decimal("0.90") and link.status == "needs_review"


# --- Sheet 5: pharmacy covered-through --------------------------------------------------------


def test_raymonds_furosemide_covered_through(morning: Session) -> None:
    fills = [
        v
        for v in member_snapshot(morning, "SYN-001", clock=CLOCK).facts
        if v.fact.type == "medication" and v.fact.key == "furosemide"
    ]
    claim = next(v for v in fills if v.value.get("strength") == "40 mg")
    assert (claim.value["fill_date"], claim.value["covered_through"]) == (
        "2026-09-30",
        "2026-10-30",
    )


# --- Sheet 8: contact ladders -----------------------------------------------------------------

LADDERS = {
    # member: [(number, confidence)] in ladder order, as in annex Sheet 8
    "SYN-001": [("555-0142", "0.82"), ("555-0143", "0.70"), ("555-0177", "0.35")],
    "SYN-003": [("555-0188", "0.72"), ("555-0110", "0.05")],
    "SYN-004": [("555-0160", "0.75"), ("555-0161", "0.40"), ("555-0133", "0.10")],
    "SYN-005": [("555-0155", "0.80")],
    "SYN-002": [("555-0121", "0.60")],
}
CONFIDENCE_DIFFERS = {
    "SYN-003": "555-0110 disconnected: 0.60 recency (undated) x 0.95 eligibility x 0.10 "
    "= 0.06, annex 0.05",
    "SYN-004": "555-0133 disconnected: 0.60 recency (undated) x 0.95 eligibility x 0.10 "
    "= 0.06, annex 0.10",
    "SYN-005": A_DIFFERS["SYN-005"],
    "SYN-002": A_DIFFERS["SYN-002"],
}


def _phone_ladder(morning: Session, member_id: str) -> list[tuple[str, Decimal, bool]]:
    entries = [e for e in channel_ladder(morning, member_id, CLOCK) if e.channel == "phone"]
    return [(e.number, e.confidence, e.callable) for e in entries]


@pytest.mark.parametrize("member_id", list(LADDERS))
def test_contact_ladder_order(morning: Session, member_id: str) -> None:
    order = [number for number, _, _ in _phone_ladder(morning, member_id)]
    assert order == [number for number, _ in LADDERS[member_id]]


@pytest.mark.parametrize(
    "member_id",
    [
        pytest.param(m, marks=pytest.mark.xfail(reason=CONFIDENCE_DIFFERS[m], strict=True))
        if m in CONFIDENCE_DIFFERS
        else m
        for m in LADDERS
    ],
)
def test_contact_confidences(morning: Session, member_id: str) -> None:
    got = [(n, c) for n, c, _ in _phone_ladder(morning, member_id)]
    assert got == [(n, Decimal(c)) for n, c in LADDERS[member_id]]


def test_who_may_be_called(morning: Session) -> None:
    kayla = {n: callable_ for n, _, callable_ in _phone_ladder(morning, "SYN-004")}
    darnell = {n: callable_ for n, _, callable_ in _phone_ladder(morning, "SYN-003")}
    # Shelter: release signed. Sister: no authorisation. Old member numbers: disconnected.
    assert kayla == {"555-0160": True, "555-0161": False, "555-0133": False}
    assert darnell == {"555-0188": True, "555-0110": False}


# --- Sheet 9: freshness colours ---------------------------------------------------------------

FRESHNESS = [
    # (member, fact type, key, colour)
    ("SYN-001", "care_gap", "TRC", "green"),  # transition contact due 10 Nov, open
    ("SYN-001", "sdoh", "general", "amber"),  # HRA 2026-03-04, 8 months
    ("SYN-002", "care_gap", "PDC", "green"),  # PDC YTD, open
    ("SYN-003", "care_gap", "FMC", "green"),  # FMC due 13 Nov, open
    ("SYN-003", "service", "nemt", "green"),  # transport no-shows in October
    ("SYN-004", "sdoh", "housing", "red"),  # housing screen 2025-12-01, 11 months
    ("SYN-004", "care_gap", "FUH", "green"),  # FUH due 12 Nov, open
    ("SYN-005", "sdoh", "caregiver_strain", "red"),  # caregiver strain 2026-02-10, 9 months
]


@pytest.mark.parametrize(("member_id", "kind", "key", "colour"), FRESHNESS)
def test_freshness_colours(
    morning: Session, member_id: str, kind: str, key: str, colour: str
) -> None:
    views = [
        v
        for v in member_snapshot(morning, member_id, clock=CLOCK).facts
        if v.fact.type == kind and v.fact.key == key
    ]
    assert views, f"no {kind}:{key} fact for {member_id}"
    assert {v.freshness for v in views} == {colour}


def test_raymonds_follow_up_appointment_is_unknown_and_grey(morning: Session) -> None:
    from app.facts.freshness import freshness
    from app.facts.unknown import Unknown, get_fact_or_unknown

    appointment = get_fact_or_unknown(morning, "SYN-001", "appointment", None, clock=CLOCK)
    assert isinstance(appointment, Unknown) and freshness(appointment, CLOCK) == "grey"


# --- Raymond's call: the 40-field template --------------------------------------------------


def test_raymonds_template_is_22_to_confirm_8_to_reask_10_live_only(api: Api) -> None:
    maria = api.as_("maria")
    link_id = api.client.get("/members/SYN-001/360", headers=maria).json()["pending_links"][0]["id"]
    api.client.post(f"/members/SYN-001/links/{link_id}/confirm", headers=maria)
    encounter = api.client.post(
        "/encounters", json={"member_id": "SYN-001", "number": "555-0142"}, headers=maria
    ).json()
    assert encounter["counts"] == {"prefilled_fresh": 22, "prefilled_stale": 8, "live_only": 10}
    assert len(encounter["fields"]) == 40

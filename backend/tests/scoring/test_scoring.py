from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.datalayer_mock.identity import confirm_link
from app.datalayer_mock.identity.models import MemberLink
from app.facts import refresh_facts
from app.facts.contacts import contact_confidence
from app.scoring.backtest import Candidate, Readmission, compare
from app.scoring.models import MemberScore
from app.scoring.score import compute_score, fmt, tier_for
from app.scoring.service import score_members
from app.signals.base import Signal

NY = ZoneInfo("America/New_York")


def test_queue_sorts_by_tier_then_score(scores: dict[str, MemberScore]) -> None:
    ranked = sorted(scores.values(), key=lambda s: s.rank)
    keys = [(s.tier, -s.score) for s in ranked]
    assert keys == sorted(keys)


def test_um_owned_deadline_is_not_scored(scores: dict[str, MemberScore]) -> None:
    rose = scores["SYN-005"]  # DME decision overdue since 2026-11-05, owned by UM
    assert (rose.u_deadline, rose.hours_to_deadline) == (Decimal("0"), None)


def test_stale_lever_discounts_m(scores: dict[str, MemberScore]) -> None:
    rose, anh = scores["SYN-005"], scores["SYN-002"]
    assert (rose.m_lever, rose.m_key_input_date) == ("LTSS_HOURS_CUT", date(2026, 10, 8))
    assert (anh.m_lever, anh.m_key_input_date) == ("NONFORMULARY_NEVER_FILLED", date(2026, 9, 16))


def test_every_score_stores_its_inputs(scores: dict[str, MemberScore]) -> None:
    raymond = scores["SYN-001"]
    assert raymond.input_fact_ids and raymond.input_signal_ids
    assert raymond.components == {"R": "35.2", "U": "30", "M": "20", "A": "8.2"}
    assert raymond.a_contact == "555-0142"


def test_missing_risk_uses_cohort_median_and_flags_verify(
    scores: dict[str, MemberScore],
) -> None:
    flagged = [s for s in scores.values() if s.verify]
    assert len(flagged) == 4
    assert all(s.r_source == "cohort_median" and Decimal(0) < s.r < Decimal(1) for s in flagged)
    assert not any(
        scores[m].verify for m in ("SYN-001", "SYN-002", "SYN-003", "SYN-004", "SYN-005")
    )


def test_confirming_raymonds_match_does_not_change_his_score(morning: Session) -> None:
    clock = FixedClock()
    link = morning.scalars(
        select(MemberLink).where(MemberLink.source_record_id == "SYN-001-H")
    ).one()
    confirm_link(morning, link.id, "maria.cm", clock=clock)
    refresh_facts(morning, clock)

    raymond = next(r for r in score_members(morning, clock) if r.member_id == "SYN-001")
    assert raymond.explanation == "35.2 + 30 + 20 + 8.2 = 93.4"


# --- unit level -------------------------------------------------------------------------------


def _snapshot(contacts: list[Any] | None = None) -> Any:
    member = SimpleNamespace(member_id="SYN-900")
    return SimpleNamespace(member=member, facts=[], contacts=contacts or [])


def _signal(**overrides: Any) -> Signal:
    values: dict[str, Any] = dict(
        member_id="SYN-900",
        rule_id="T",
        rule_version="1",
        input_fact_ids=(1,),
        insight_text="t",
        severity="info",
        suggested_step="s",
    )
    values.update(overrides)
    return Signal(**values)


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (-5, "1"),
        (0, "1"),
        (60, "0.5"),
        (120, "0"),
        (200, "0"),
    ],
)
def test_u_deadline_is_clamped(hours: int, expected: str) -> None:
    clock = FixedClock()
    due = clock.now().astimezone(UTC) + timedelta(hours=hours)
    signal = _signal(due_at=due, due_tz="America/New_York", deadline_kind="member_contact")

    result = compute_score(_snapshot(), [signal], clock, {None: Decimal("0.5")})

    assert result.u_deadline == Decimal(expected)


def test_a_ignores_unauthorised_and_disconnected_contacts() -> None:
    contacts = [
        SimpleNamespace(
            number="555-0101",
            confidence=Decimal("0.9"),
            authorised=False,
            callable=False,
            fact_ids=[1],
        ),
        SimpleNamespace(
            number="555-0102",
            confidence=Decimal("0.06"),
            authorised=True,
            callable=False,
            fact_ids=[2],
        ),
        SimpleNamespace(
            number="555-0103",
            confidence=Decimal("0.4"),
            authorised=True,
            callable=True,
            fact_ids=[3],
        ),
    ]
    result = compute_score(_snapshot(contacts), [], FixedClock(), {None: Decimal("0.5")})
    assert (result.a, result.a_contact) == (Decimal("0.4"), "555-0103")


def test_tiers_and_number_format() -> None:
    assert [tier_for(Decimal(u)) for u in ("1", "0.9", "0.89", "0.5", "0.49")] == [
        "T0",
        "T0",
        "T1",
        "T1",
        "T2",
    ]
    assert [fmt(Decimal(v)) for v in ("35.20", "30.0", "21.75", "8.2")] == [
        "35.2",
        "30",
        "21.75",
        "8.2",
    ]


def test_contact_formula_reproduces_the_differing_heroes() -> None:
    today = date(2026, 11, 9)
    assert contact_confidence(
        "eligibility", date(2026, 3, 1), "voicemail", today
    ).confidence == Decimal("0.81")
    assert contact_confidence(
        "eligibility", date(2025, 6, 1), "voicemail", today
    ).confidence == Decimal("0.59")


# --- back-test --------------------------------------------------------------------------------


def _candidate(member: str, arrival_hour: int, risk: str, tier: str, score: str) -> Candidate:
    return Candidate(
        member, datetime(2026, 10, 1, arrival_hour, tzinfo=NY), Decimal(risk), tier, Decimal(score)
    )


def test_backtest_compares_orderings_on_captured_readmissions() -> None:
    # Top-1 per day. SYN-A arrives first, SYN-B has the highest risk, SYN-C is T0 for us.
    day = date(2026, 10, 2)
    daily = {
        day: [
            _candidate("SYN-A", 1, "0.2", "T2", "20"),
            _candidate("SYN-B", 2, "0.9", "T1", "60"),
            _candidate("SYN-C", 3, "0.5", "T0", "70"),
        ]
    }
    readmissions = [Readmission("SYN-C", date(2026, 10, 1), date(2026, 10, 5))]

    results = compare(daily, readmissions, top_n=1)

    assert {name: r.captured for name, r in results.items()} == {
        "casecompass": ["SYN-C"],
        "arrival": [],
        "risk_only": [],
    }
    assert results["casecompass"].rate == 1.0


def test_backtest_only_counts_days_between_discharge_and_readmission() -> None:
    daily = {date(2026, 10, 1): [_candidate("SYN-C", 1, "0.5", "T0", "70")]}
    readmissions = [Readmission("SYN-C", date(2026, 10, 1), date(2026, 10, 5))]

    assert compare(daily, readmissions, top_n=1)["casecompass"].captured == []


def test_backtest_runs_on_synthetic_background_members(morning: Session) -> None:
    from app.scoring.backtest import backtest

    result = backtest(morning, date(2026, 10, 1), date(2026, 11, 9))

    assert result.discharges > 0
    # The synthetic background has no readmissions yet, so every ordering scores 0 of 0.
    assert result.readmissions == []
    assert {name: (len(r.captured), r.total) for name, r in result.orderings.items()} == {
        "casecompass": (0, 0),
        "arrival": (0, 0),
        "risk_only": (0, 0),
    }
    assert "0 readmissions" in result.summary()

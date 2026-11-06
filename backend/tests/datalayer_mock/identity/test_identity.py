from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.datalayer_mock.identity import (
    LinkDecisionError,
    classify,
    confirm_link,
    is_linked,
    member_history,
    record_daily_metrics,
    reject_link,
    run_matching,
    score,
    unlinked_adt_events,
    unmerge,
)
from app.datalayer_mock.identity.jaro_winkler import jaro_winkler
from app.datalayer_mock.identity.models import (
    AUTO_LINKED,
    CONFIRMED,
    NEEDS_REVIEW,
    REJECTED,
    LinkAudit,
    Member,
    MemberLink,
)
from app.datalayer_mock.identity.scoring import Demographics

HEROES = ("SYN-001", "SYN-002", "SYN-003", "SYN-004", "SYN-005")


def link_for(session: Session, source_record_id: str) -> MemberLink:
    return session.scalars(
        select(MemberLink).where(MemberLink.source_record_id == source_record_id)
    ).one()


def audit_actions(session: Session, link_id: int) -> list[tuple[str, str, str]]:
    return [
        (a.action, a.actor, a.to_status)
        for a in session.scalars(
            select(LinkAudit).where(LinkAudit.link_id == link_id).order_by(LinkAudit.id)
        )
    ]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("MARTHA", "MARHTA", 0.961),
        ("DWAYNE", "DUANE", 0.840),
        ("DIXON", "DICKSONX", 0.813),
        ("TULL", "TULL", 1.0),
        ("", "TULL", 0.0),
    ],
)
def test_jaro_winkler_reference_values(a: str, b: str, expected: float) -> None:
    assert jaro_winkler(a, b) == pytest.approx(expected, abs=0.001)


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        ("1.000", AUTO_LINKED),
        ("0.900", AUTO_LINKED),
        ("0.899", NEEDS_REVIEW),
        ("0.700", NEEDS_REVIEW),
        ("0.699", None),
    ],
)
def test_confidence_thresholds(confidence: str, expected: str | None) -> None:
    assert classify(Decimal(confidence)) == expected


def test_hospital_duplicate_links_to_raymond_for_review(
    ingested: Session, clock: FixedClock
) -> None:
    run_matching(ingested, clock)

    link = link_for(ingested, "SYN-001-H")
    assert (link.source_system, link.member_id, link.match_method, link.status) == (
        "hospital",
        "SYN-001",
        "probabilistic",
        NEEDS_REVIEW,
    )
    assert abs(link.confidence - Decimal("0.86")) <= Decimal("0.02")
    # Explainable: per-field contributions add up to the confidence, inputs are referenced.
    fields = link.field_scores or {}
    assert sum(Decimal(str(f["contribution"])) for f in fields.values()) == link.confidence
    assert fields["phone"]["level"] == "different"
    assert fields["address"]["level"] == "exact"  # "12 Larch Street" == "12 Larch St"
    streams = sorted({e["stream"] for e in link.evidence})
    assert streams == ["adt", "ccda", "eligibility_834"]
    assert audit_actions(ingested, link.id) == [("suggested", "system:matcher", NEEDS_REVIEW)]


def test_maiden_name_record_links_to_kayla_for_review(ingested: Session, clock: FixedClock) -> None:
    run_matching(ingested, clock)

    link = link_for(ingested, "SYN-004-M")
    assert (link.source_system, link.member_id, link.status) == (
        "eligibility",
        "SYN-004",
        NEEDS_REVIEW,
    )
    assert abs(link.confidence - Decimal("0.78")) <= Decimal("0.02")
    fields = link.field_scores or {}
    assert fields["last_name"]["level"] == "possible surname change"
    assert (fields["last_name"]["source"], fields["last_name"]["candidate"]) == (
        "DELANEY",
        "MORRISON",
    )
    assert ingested.get(Member, "SYN-004-M") is None  # terminated record: not a golden member


def test_no_hero_is_auto_merged_except_by_exact_plan_id(
    ingested: Session, clock: FixedClock
) -> None:
    run_matching(ingested, clock)

    hero_links = ingested.scalars(select(MemberLink).where(MemberLink.member_id.in_(HEROES))).all()
    auto = [link for link in hero_links if link.status == AUTO_LINKED]
    assert auto and all(link.match_method == "exact_id" for link in auto)
    assert all(link.source_record_id in HEROES for link in auto)
    probabilistic = sorted(
        (link.source_record_id, link.status)
        for link in hero_links
        if link.match_method == "probabilistic"
    )
    assert probabilistic == [("SYN-001-H", NEEDS_REVIEW), ("SYN-004-M", NEEDS_REVIEW)]


def test_background_duplicates_land_in_the_review_queue(
    ingested: Session, clock: FixedClock
) -> None:
    run_matching(ingested, clock)

    probabilistic = ingested.scalars(
        select(MemberLink).where(MemberLink.match_method == "probabilistic")
    ).all()
    assert len(probabilistic) == 12  # 1 + 5 hospital shells, 1 + 5 previous-name records
    assert {link.status for link in probabilistic} == {NEEDS_REVIEW}
    assert all(link.member_id == link.source_record_id[:7] for link in probabilistic)


def test_rejected_link_is_not_recreated_by_rematching(ingested: Session, clock: FixedClock) -> None:
    run_matching(ingested, clock)
    link = link_for(ingested, "SYN-004-M")

    reject_link(ingested, link.id, "alma.cm", clock=clock)
    summary = run_matching(ingested, clock)

    again = ingested.scalars(
        select(MemberLink).where(MemberLink.source_record_id == "SYN-004-M")
    ).all()
    assert [(x.id, x.status, x.decided_by) for x in again] == [(link.id, REJECTED, "alma.cm")]
    assert summary.created == {}
    assert audit_actions(ingested, link.id)[-1] == ("rejected", "alma.cm", REJECTED)


def test_confirm_link_records_who_and_when(ingested: Session, clock: FixedClock) -> None:
    run_matching(ingested, clock)
    link = link_for(ingested, "SYN-001-H")

    confirm_link(ingested, link.id, "maria.cm", clock=clock)

    assert (link.status, link.decided_by, link.decided_at) == (CONFIRMED, "maria.cm", clock.now())
    assert audit_actions(ingested, link.id)[-1] == ("confirmed", "maria.cm", CONFIRMED)
    assert is_linked(ingested, "hospital", "SYN-001-H")


def test_decisions_need_a_human_and_a_valid_state(ingested: Session, clock: FixedClock) -> None:
    run_matching(ingested, clock)
    link = link_for(ingested, "SYN-001-H")

    with pytest.raises(LinkDecisionError):
        confirm_link(ingested, link.id, "system:ai", clock=clock)
    reject_link(ingested, link.id, "maria.cm", clock=clock)
    with pytest.raises(LinkDecisionError):
        confirm_link(ingested, link.id, "maria.cm", clock=clock)


def test_unmerge_restores_both_histories(ingested: Session, clock: FixedClock) -> None:
    run_matching(ingested, clock)
    link = link_for(ingested, "SYN-001-H")
    confirm_link(ingested, link.id, "maria.cm", clock=clock)
    merged = member_history(ingested, "SYN-001")
    shell_events = next(h.evidence for h in merged if h.source_record_id == "SYN-001-H")
    assert len([e for e in shell_events if e["stream"] == "adt"]) == 2

    unmerge(ingested, "SYN-001", link.id, "maria.cm", clock=clock)

    after = member_history(ingested, "SYN-001")
    assert [h.source_record_id for h in after] == [
        h.source_record_id for h in merged if h.source_record_id != "SYN-001-H"
    ]
    assert not is_linked(ingested, "hospital", "SYN-001-H")
    assert link.evidence[: len(shell_events)] == shell_events  # the shell keeps its records
    assert [a for a, _, _ in audit_actions(ingested, link.id)] == [
        "suggested",
        "confirmed",
        "unmerged",
    ]
    run_matching(ingested, clock)
    assert link_for(ingested, "SYN-001-H").status == REJECTED  # not re-suggested


def test_unmerge_checks_the_member(ingested: Session, clock: FixedClock) -> None:
    run_matching(ingested, clock)
    link = link_for(ingested, "SYN-001-H")
    confirm_link(ingested, link.id, "maria.cm", clock=clock)

    with pytest.raises(LinkDecisionError):
        unmerge(ingested, "SYN-002", link.id, "maria.cm", clock=clock)


def test_daily_metric_counts_unlinked_adt_events(ingested: Session, clock: FixedClock) -> None:
    run_matching(ingested, clock)
    assert unlinked_adt_events(ingested) == 12  # 6 shells x 2 messages, all in review

    confirm_link(ingested, link_for(ingested, "SYN-001-H").id, "maria.cm", clock=clock)
    metric = record_daily_metrics(ingested, clock)

    assert (metric.metric, metric.day, metric.value) == (
        "unlinked_adt_events",
        date(2026, 11, 9),
        10,
    )
    assert record_daily_metrics(ingested, clock).id == metric.id  # one row per day


def test_missing_fields_never_count_as_agreement() -> None:
    known = Demographics(
        "Raymond", "Tull", date(1950, 4, 12), "M", "12 Larch St", "Columbus", "43204", "555-0177"
    )
    sparse = Demographics("Raymond", "Tull", None, None, None, None, None, None)

    result = score(sparse, known)

    assert result.confidence == Decimal("0.400")
    assert {k for k, f in result.fields.items() if f.level == "missing"} == {
        "dob",
        "sex",
        "address",
        "phone",
    }

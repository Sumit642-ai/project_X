"""One test per rule against the hero members at 2026-11-09 08:00 America/New_York."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.datalayer_mock.identity.models import DailyMetric
from app.facts.models import Fact
from app.facts.snapshot import member_snapshot
from app.signals.base import Rule, Signal
from app.signals.calendar import BusinessCalendar, due_at
from app.signals.engine import evaluate_signals
from app.signals.models import SignalRecord
from app.signals.rules import (
    RULES,
    CaregiverStrain,
    ContactDisconnected,
    DischargeSummaryMissing,
    DmeAuthOverdue,
    DrugRejectedNoRequest,
    EdRepeat90d,
    FmcDue,
    FuhDue,
    HfDischarge,
    LanguageMismatchOutreach,
    LtssHoursCut,
    NoCriticalMedOnHand,
    NonformularyNeverFilled,
    PsychDischargeNoContact,
    RescueMedGapAfterEd,
    StaleSdoh,
)

NY = ZoneInfo("America/New_York")
NO_HOLIDAYS = BusinessCalendar([])


def run(
    rule: type[Rule], session: Session, member_id: str, calendar: BusinessCalendar = NO_HOLIDAYS
) -> list[Signal]:
    clock = FixedClock()
    return rule(calendar).evaluate(member_snapshot(session, member_id, clock=clock), clock)


def one(rule: type[Rule], session: Session, member_id: str) -> Signal:
    (signal,) = run(rule, session, member_id)
    return signal


def fact_keys(session: Session, signal: Signal) -> set[str]:
    return {
        f"{f.type}:{f.key}"
        for f in session.scalars(select(Fact).where(Fact.id.in_(signal.input_fact_ids)))
    }


def test_hf_discharge_sets_transition_due_two_business_days_later(morning: Session) -> None:
    signal = one(HfDischarge, morning, "SYN-001")

    assert signal.due_at == datetime(2026, 11, 10, 22, 0, tzinfo=UTC)  # stored in UTC
    assert signal.due_at.astimezone(NY) == datetime(2026, 11, 10, 17, 0, tzinfo=NY)
    assert (signal.due_tz, signal.deadline_kind) == ("America/New_York", "member_contact")
    assert signal.insight_text == "HF discharge 2026-11-07; transition contact due Tue 17:00"
    assert "diagnosis:I50.22" in fact_keys(morning, signal)
    assert run(HfDischarge, morning, "SYN-002") == []


def test_hf_discharge_skips_plan_holidays(morning: Session) -> None:
    signal = one_with(HfDischarge, morning, "SYN-001", BusinessCalendar([date(2026, 11, 10)]))
    assert signal.due_at is not None
    assert signal.due_at.astimezone(NY).date() == date(2026, 11, 11)


def one_with(
    rule: type[Rule], session: Session, member_id: str, calendar: BusinessCalendar
) -> Signal:
    (signal,) = run(rule, session, member_id, calendar)
    return signal


def test_no_critical_med_on_hand_is_red_for_raymond(morning: Session) -> None:
    signal = one(NoCriticalMedOnHand, morning, "SYN-001")

    assert (signal.severity, signal.lever) == ("red", True)
    assert signal.insight_text == "Furosemide ran out 2026-10-30; no fill since discharge"
    assert "medication:furosemide" in fact_keys(morning, signal)
    assert run(NoCriticalMedOnHand, morning, "SYN-003") == []


def test_drug_rejected_without_request(morning: Session) -> None:
    signal = one(DrugRejectedNoRequest, morning, "SYN-001")

    assert signal.insight_text == (
        "Sacubitril/valsartan rejected (PA required); no coverage request filed"
    )
    assert signal.key_input_date == date(2026, 11, 7)
    assert run(DrugRejectedNoRequest, morning, "SYN-002") == []  # non-formulary: its own rule


def test_discharge_summary_missing(morning: Session) -> None:
    signal = one(DischargeSummaryMissing, morning, "SYN-001")

    assert signal.insight_text == "Discharge summary requested 2026-11-07, not received"
    assert fact_keys(morning, signal) == {"event:document_request:discharge_summary"}
    assert run(DischargeSummaryMissing, morning, "SYN-004") == []  # Kayla's summary arrived


def test_ed_repeat_counts_adt_and_claims_once(morning: Session) -> None:
    signal = one(EdRepeat90d, morning, "SYN-003")

    assert signal.insight_text == "4 ED visits in 90 days; 2 only in ADT"
    assert signal.severity == "amber"
    assert run(EdRepeat90d, morning, "SYN-005") == []  # one ED visit in the last 90 days


def test_rescue_med_gap_after_ed(morning: Session) -> None:
    signal = one(RescueMedGapAfterEd, morning, "SYN-003")

    assert signal.severity == "amber"
    assert signal.insight_text == "ED visit 2026-11-06; no rescue inhaler since 2026-09-14"
    assert "medication:albuterol" in fact_keys(morning, signal)
    assert run(RescueMedGapAfterEd, morning, "SYN-001") == []


def test_fmc_due_seven_days_after_ed_visit(morning: Session) -> None:
    signal = one(FmcDue, morning, "SYN-003")

    assert signal.due_at is not None
    assert signal.due_at.astimezone(NY) == datetime(2026, 11, 13, 17, 0, tzinfo=NY)
    assert run(FmcDue, morning, "SYN-001") == []


def test_psych_discharge_without_contact_is_red(morning: Session) -> None:
    signal = one(PsychDischargeNoContact, morning, "SYN-004")

    assert signal.severity == "red"
    assert signal.insight_text == "Psychiatric discharge 2026-11-05; no successful contact since"
    assert run(PsychDischargeNoContact, morning, "SYN-001") == []


def test_fuh_due(morning: Session) -> None:
    signal = one(FuhDue, morning, "SYN-004")

    assert signal.due_at is not None
    assert signal.due_at.astimezone(NY) == datetime(2026, 11, 12, 17, 0, tzinfo=NY)
    assert signal.deadline_kind == "member_contact"


def test_ltss_hours_cut(morning: Session) -> None:
    signal = one(LtssHoursCut, morning, "SYN-005")

    assert signal.insight_text == "Aide hours cut 20 to 12 (-40%); appeal by 2026-11-30"
    assert (signal.deadline_kind, signal.key_input_date) == ("appeal", date(2026, 10, 8))
    assert run(LtssHoursCut, morning, "SYN-001") == []


def test_dme_auth_overdue_is_um_owned(morning: Session) -> None:
    signal = one(DmeAuthOverdue, morning, "SYN-005")

    assert signal.insight_text == "Hospital bed (DME) authorisation overdue since 2026-11-05"
    assert (signal.deadline_kind, signal.lever) == ("um", False)
    assert "Face-to-face encounter note" in signal.suggested_step


def test_caregiver_strain(morning: Session) -> None:
    signal = one(CaregiverStrain, morning, "SYN-005")

    assert (signal.severity, signal.insight_text) == ("amber", "Caregiver strain high: 14 of 16")
    assert run(CaregiverStrain, morning, "SYN-001") == []


def test_nonformulary_never_filled(morning: Session) -> None:
    signal = one(NonformularyNeverFilled, morning, "SYN-002")

    assert signal.insight_text == "Semaglutide rejected as non-formulary; never filled"
    assert signal.key_input_date == date(2026, 9, 16)


def test_language_mismatch_outreach(morning: Session) -> None:
    signal = one(LanguageMismatchOutreach, morning, "SYN-002")

    assert signal.insight_text == "4 English calls to a Vietnamese speaker"
    # Rose-Marie's calls go to her English-speaking daughter (proxy language): no mismatch.
    assert run(LanguageMismatchOutreach, morning, "SYN-005") == []


def test_stale_sdoh(morning: Session) -> None:
    assert [s.insight_text for s in run(StaleSdoh, morning, "SYN-004")] == [
        "Housing screen 343 days old"
    ]
    assert [s.insight_text for s in run(StaleSdoh, morning, "SYN-001")] == ["HRA 250 days old"]
    assert run(StaleSdoh, morning, "SYN-002") == []


def test_contact_disconnected(morning: Session) -> None:
    assert one(ContactDisconnected, morning, "SYN-003").insight_text == (
        "Number 555-0110 disconnected; newer 555-0188 available"
    )
    assert one(ContactDisconnected, morning, "SYN-004").insight_text == (
        "Number 555-0133 disconnected"
    )
    assert run(ContactDisconnected, morning, "SYN-001") == []


# --- framework --------------------------------------------------------------------------------


def test_every_rule_declares_its_metadata() -> None:
    assert len(RULES) == 17
    for rule in RULES:
        assert rule.rule_id and rule.version and rule.owner and rule.description
        assert rule.severity in ("red", "amber", "info")


def test_signals_need_short_insight_and_input_facts() -> None:
    base = dict(
        member_id="SYN-001", rule_id="X", rule_version="1", severity="info", suggested_step="s"
    )
    with pytest.raises(ValueError, match="12"):
        Signal(input_fact_ids=(1,), insight_text=" ".join(["word"] * 13), **base)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="input facts"):
        Signal(input_fact_ids=(), insight_text="ok", **base)  # type: ignore[arg-type]


def test_every_stored_signal_is_short_and_cites_real_facts(morning: Session) -> None:
    run_ = evaluate_signals(morning, FixedClock())

    assert run_.signals
    fact_ids = set(morning.scalars(select(Fact.id)))
    for record in run_.signals:
        assert len(record.insight_text.split()) <= 12
        assert record.input_fact_ids and set(record.input_fact_ids) <= fact_ids


def test_kill_switch_and_daily_counts(morning: Session) -> None:
    evaluate_signals(morning, FixedClock(), disabled=["ED_REPEAT_90D"])

    rules = set(morning.scalars(select(SignalRecord.rule_id)))
    assert "ED_REPEAT_90D" not in rules and "HF_DISCHARGE" in rules
    counts = {
        m.metric: m.value
        for m in morning.scalars(select(DailyMetric).where(DailyMetric.day == date(2026, 11, 9)))
    }
    assert "signals.ED_REPEAT_90D" not in counts
    stored = len(
        morning.scalars(select(SignalRecord).where(SignalRecord.rule_id == "HF_DISCHARGE")).all()
    )
    assert counts["signals.HF_DISCHARGE"] == stored >= 1


def test_kill_switch_reads_settings(morning: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config
    from app.signals import engine

    settings = config.Settings(disabled_rules=["STALE_SDOH"])
    monkeypatch.setattr(engine, "get_settings", lambda: settings)
    evaluate_signals(morning, FixedClock())

    assert "STALE_SDOH" not in set(morning.scalars(select(SignalRecord.rule_id)))


def test_rerunning_a_day_replaces_its_signals(morning: Session) -> None:
    first = len(evaluate_signals(morning, FixedClock()).signals)
    evaluate_signals(morning, FixedClock())

    assert len(morning.scalars(select(SignalRecord)).all()) == first


def test_business_calendar_and_utc_deadlines() -> None:
    calendar = BusinessCalendar([date(2026, 11, 26), date(2026, 11, 27)])

    assert calendar.add_business_days(date(2026, 11, 7), 2) == date(2026, 11, 10)  # Sat -> Tue
    assert calendar.add_business_days(date(2026, 11, 25), 2) == date(2026, 12, 1)  # Thanksgiving
    assert due_at(date(2026, 7, 1), "America/New_York") == datetime(
        2026, 7, 1, 21, 0, tzinfo=UTC
    )  # EDT
    assert due_at(date(2026, 11, 10), "America/New_York") == datetime(
        2026, 11, 10, 22, 0, tzinfo=UTC
    )  # EST

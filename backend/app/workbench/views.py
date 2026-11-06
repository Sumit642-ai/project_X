"""Read models for the workbench: the ranked queue and the member 360."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import schemas
from app.consent import policy
from app.core.clock import PLAN_TZ, Clock
from app.datalayer_mock.identity.models import NEEDS_REVIEW, Member, MemberLink
from app.datalayer_mock.ingest.models import PASS, Load
from app.facts.conflicts import conflict_fact_ids
from app.facts.snapshot import FactView, member_snapshot
from app.facts.unknown import Unknown, get_fact_or_unknown
from app.scoring.models import MemberScore
from app.scoring.service import handled_by_member
from app.signals.models import SignalRecord
from app.workbench.access import active_assignment, assigned_members, unassigned_members
from app.workbench.feeds import stale_streams
from app.workbench.models import Assignment, Snooze, User

SEVERITY_ORDER = {"red": 0, "amber": 1, "info": 2}


def age_on(dob: date, clock: Clock) -> int:
    today = clock.now().astimezone(PLAN_TZ).date()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _unknown(item: Unknown) -> schemas.UnknownOut:
    return schemas.UnknownOut(type=item.type, key=item.key, reason=item.reason, as_of=item.as_of)


def _latest_run_day(session: Session, clock: Clock) -> date | None:
    today = clock.now().astimezone(PLAN_TZ).date()
    result: date | None = session.scalar(
        select(func.max(MemberScore.run_day)).where(MemberScore.run_day <= today)
    )
    return result


def _ordered(signals: list[SignalRecord]) -> list[SignalRecord]:
    return sorted(
        signals,
        key=lambda s: (
            SEVERITY_ORDER[s.severity],
            not s.lever,
            s.due_at or datetime.max.replace(tzinfo=PLAN_TZ),
            s.rule_id,
        ),
    )


def build_queue(
    session: Session, clock: Clock, *, scope: str, user: User | None
) -> schemas.QueueOut:
    """scope: a CM username, 'unassigned', or 'all'."""
    run_day = _latest_run_day(session, clock)
    rows = (
        list(
            session.scalars(
                select(MemberScore).where(MemberScore.run_day == run_day).order_by(MemberScore.rank)
            )
        )
        if run_day
        else []
    )
    all_ids = {r.member_id for r in rows}
    if scope == "all":
        keep = all_ids
    elif scope == "unassigned":
        keep = unassigned_members(session, all_ids)
    else:
        keep = assigned_members(session, scope)
    if user is not None and scope == user.username:
        today = clock.now().astimezone(PLAN_TZ).date()
        snoozed = set(
            session.scalars(
                select(Snooze.member_id).where(
                    Snooze.cm_username == user.username, Snooze.until > today
                )
            )
        )
        keep -= snoozed
    rows = [r for r in rows if r.member_id in keep]

    shown = [r.member_id for r in rows]
    signals: dict[str, list[SignalRecord]] = {}
    for record in session.scalars(
        select(SignalRecord).where(
            SignalRecord.run_day == run_day, SignalRecord.member_id.in_(shown)
        )
    ):
        signals.setdefault(record.member_id, []).append(record)
    handled = handled_by_member(session)
    assignments = {
        a.member_id: a
        for a in session.scalars(select(Assignment).where(Assignment.status == "active"))
    }
    pending: dict[str, list[int]] = {}
    for link in session.scalars(select(MemberLink).where(MemberLink.status == NEEDS_REVIEW)):
        pending.setdefault(link.member_id, []).append(link.id)
    members = {m.member_id: m for m in session.scalars(select(Member))}
    names = {k: f"{m.first_name} {m.last_name}" for k, m in members.items()}

    out_rows = []
    for position, row in enumerate(rows, start=1):
        member_handled = handled.get(row.member_id, frozenset())
        ordered = _ordered(
            [
                s
                for s in signals.get(row.member_id, [])
                if (s.rule_id, tuple(sorted(s.input_fact_ids))) not in member_handled
            ]
        )
        top = ordered[0] if ordered else None
        tz = next((s.due_tz for s in ordered if s.due_tz), None)
        assignment = assignments.get(row.member_id)
        links = pending.get(row.member_id, [])
        out_rows.append(
            schemas.QueueRow(
                rank=position,
                member_id=row.member_id,
                name=names.get(row.member_id, "UNKNOWN"),
                lob=members[row.member_id].lob if row.member_id in members else None,
                age=age_on(members[row.member_id].dob, clock) if row.member_id in members else None,
                score_inputs=schemas.ScoreInputs(r=row.r, u=row.u, m=row.m, a=row.a),
                tier=row.tier,
                score=row.score,
                why=[s.insight_text for s in ordered[:3]],
                due_at=row.deadline_at,
                due_tz=tz if row.deadline_at else None,
                next_best_action=schemas.NextBestAction(
                    text=top.suggested_step, reason=top.insight_text, rule_id=top.rule_id
                )
                if top
                else None,
                duplicate=schemas.DuplicateFlag(
                    flagged=bool(links),
                    label="flagged by data layer" if links else None,
                    link_ids=links,
                ),
                assigned_cm=assignment.cm_username if assignment else None,
            )
        )

    tier_counts = {"T0": 0, "T1": 0, "T2": 0}
    for row in rows:
        tier_counts[row.tier] += 1
    capacity = None
    if user is not None and user.role == "cm" and scope == user.username:
        capacity = schemas.Capacity(
            active=len(assigned_members(session, user.username)), target=user.capacity_target
        )
    header = schemas.QueueHeader(
        now=clock.now(),
        data_as_of=max((r.computed_at for r in rows), default=None),
        scored_on=run_day,
        stale_feeds=[
            schemas.StaleFeed(feed=s.feed, stream=s.stream, reason=s.reason or "")
            for s in stale_streams(session, clock)
        ],
        tier_counts=tier_counts,
        capacity=capacity,
    )
    return schemas.QueueOut(header=header, rows=out_rows)


# --- member 360 -------------------------------------------------------------------------------


def _fact_out(view: FactView) -> schemas.FactOut:
    f = view.fact
    return schemas.FactOut(
        id=f.id,
        type=f.type,
        key=f.key,
        value=view.value,
        event_date=f.event_date,
        loaded_at=f.loaded_at,
        source_system=f.source_system,
        source_record_id=f.source_record_id,
        status=f.status,
        confidence=f.confidence,
        freshness=view.freshness,
        masked=view.masked,
    )


def _signal_out(record: SignalRecord) -> schemas.SignalOut:
    return schemas.SignalOut(
        rule_id=record.rule_id,
        severity=record.severity,
        insight_text=record.insight_text,
        suggested_step=record.suggested_step,
        due_at=record.due_at,
        input_fact_ids=record.input_fact_ids,
    )


def _value(view: FactView) -> dict[str, Any]:
    return view.value


def build_360(session: Session, member_id: str, clock: Clock) -> schemas.Member360:
    member = session.get(Member, member_id)
    if member is None:
        raise KeyError(member_id)
    snapshot = member_snapshot(session, member_id, clock=clock)
    run_day = _latest_run_day(session, clock)
    signals = _ordered(
        list(
            session.scalars(
                select(SignalRecord).where(
                    SignalRecord.run_day == run_day, SignalRecord.member_id == member_id
                )
            )
        )
    )
    assignment = active_assignment(session, member_id)

    # Since last contact: until encounters exist (phase 8), the last answered outreach.
    answered = [
        v
        for v in snapshot.facts
        if v.fact.type == "event"
        and v.fact.key.startswith("outreach:")
        and v.value.get("outcome") == "answered"
    ]
    last = max(answered, key=lambda v: v.value.get("attempted_at") or "", default=None)
    since = datetime.fromisoformat(last.value["attempted_at"]) if last else None
    since_day = since.astimezone(PLAN_TZ).date() if since else None
    newer = [
        v
        for v in snapshot.facts
        if since_day is None or (v.fact.event_date and v.fact.event_date > since_day)
    ]
    reference = (
        f"last answered call {since_day}"
        if since_day
        else "no completed contact on record: everything is new"
    )

    coverage = [
        v for v in snapshot.facts if v.fact.type == "coverage" and v.fact.key.startswith("plan:")
    ]
    plan = _value(coverage[-1]) if coverage else {}
    care_team: list[schemas.CareTeamMember] = [
        schemas.CareTeamMember(
            role="PCP",
            name=plan.get("pcp")
            or schemas.UnknownOut(
                type="care_team", key="pcp", reason="no PCP attributed in eligibility"
            ),
        ),
        schemas.CareTeamMember(
            role="Case manager",
            name=assignment.cm_username
            if assignment
            else schemas.UnknownOut(type="care_team", key="cm", reason="not assigned"),
        ),
    ]
    for item in snapshot.consents:
        if policy.is_representative(item.consent) and item.consent.party_name:
            state = "valid" if item.valid else f"form expired {item.consent.valid_to}"
            care_team.append(
                schemas.CareTeamMember(
                    role="Representative",
                    name=item.consent.party_name,
                    detail=f"{item.consent.relationship or ''}, {state}".strip(", "),
                )
            )
    pharmacies = [
        v
        for v in snapshot.facts
        if v.fact.type == "medication" and v.value.get("source_kind") == "pharmacy_claim"
    ]
    if pharmacies:
        latest_fill = max(pharmacies, key=lambda v: (v.fact.event_date or date.min, v.fact.id))
        care_team.append(
            schemas.CareTeamMember(
                role="Pharmacy", name=latest_fill.value.get("pharmacy") or "UNKNOWN"
            )
        )

    contacts = []
    for c in snapshot.contacts:
        reachable, why_not = policy.contact_status(c)
        contacts.append(
            schemas.ContactOut(
                number=c.number,
                owner=c.owner,
                owner_name=c.owner_name,
                relationship=c.relationship,
                source=c.source,
                last_verified=c.last_verified,
                last_outcome=c.last_outcome,
                best_window=c.best_window,
                confidence=c.confidence,
                consent_sms=policy.has_sms_consent(c),
                authorised=policy.is_authorised(c),
                callable=reachable,
                not_callable_reason=why_not,
            )
        )

    score = session.scalars(
        select(MemberScore).where(
            MemberScore.member_id == member_id, MemberScore.run_day == run_day
        )
    ).first()
    risk_facts = [v for v in snapshot.facts if v.fact.type == "risk"]
    risk_fact = risk_facts[-1] if risk_facts else None
    if score is not None:
        risk_value: Decimal | schemas.UnknownOut = score.r
        basis, verify = score.r_source, score.verify
    elif risk_fact is not None:
        risk_value, basis, verify = Decimal(str(risk_fact.value["score"])), "plan", False
    else:
        risk_value = schemas.UnknownOut(type="risk", reason="no plan risk score")
        basis, verify = "cohort_median", True
    risk = schemas.RiskOut(
        value=risk_value,
        basis=basis,
        verify=verify,
        model=risk_fact.value.get("model") if risk_fact else None,
        scored_at=risk_fact.fact.event_date if risk_fact else None,
    )

    unknowns = [get_fact_or_unknown(session, member_id, "appointment", None, clock=clock)]
    preference = next(
        (v.value for v in reversed(snapshot.facts) if v.fact.type == "preference"), {}
    )
    claims_as_of = session.scalar(
        select(Load.data_as_of)
        .where(Load.stream == "claims_837", Load.status == PASS, Load.is_active.is_(True))
        .order_by(Load.id.desc())
    )
    return schemas.Member360(
        now=clock.now(),
        claims_as_of=claims_as_of,
        member=schemas.MemberHeader(
            member_id=member.member_id,
            name=f"{member.first_name} {member.last_name}",
            dob=member.dob,
            age=age_on(member.dob, clock),
            lob=member.lob,
            plan=plan.get("plan"),
            language=preference.get("preferred_language") or plan.get("language"),
            proxy_language=preference.get("proxy_language"),
            assigned_cm=assignment.cm_username if assignment else None,
        ),
        since_last_contact=schemas.SinceLastContact(
            reference=reference,
            since=since,
            facts=[_fact_out(v) for v in newer],
            signals=[_signal_out(s) for s in signals],
        ),
        last_call_note=schemas.UnknownOut(
            type="call_note", reason="no completed encounter recorded"
        ),
        member_goal=schemas.UnknownOut(type="member_goal", reason="no goal recorded"),
        conflicts=[
            schemas.ConflictOut(
                id=c.conflict.id,
                fact_type=c.conflict.fact_type,
                key=c.conflict.key,
                kind=c.conflict.kind,
                summary=c.conflict.summary,
                status=c.conflict.status,
                fact_ids=conflict_fact_ids(session, c.conflict.id),
                detected_at=c.conflict.detected_at,
            )
            for c in snapshot.conflicts
        ],
        contacts=contacts,
        care_team=care_team,
        documents=[
            schemas.DocumentOut(
                id=d.id,
                type=d.type,
                facility=d.facility,
                status=d.status,
                requested_at=d.requested_at,
                received_at=d.received_at,
            )
            for d in snapshot.documents
        ],
        consents=[
            schemas.ConsentOut(
                id=c.consent.id,
                type=c.consent.type,
                party=c.consent.party_name,
                phone=c.consent.phone,
                program=c.consent.program,
                scope=c.consent.scope,
                valid_from=c.consent.valid_from,
                valid_to=c.consent.valid_to,
                valid=c.valid,
            )
            for c in snapshot.consents
        ],
        facts=[_fact_out(v) for v in snapshot.facts],
        unknowns=[_unknown(u) for u in unknowns if isinstance(u, Unknown)],
        risk=risk,
        pending_links=[
            schemas.PendingLinkOut(
                id=link.id,
                source_system=link.source_system,
                source_record_id=link.source_record_id,
                confidence=link.confidence,
                status=link.status,
            )
            for link in snapshot.pending_links
        ],
        adt_feed_stale=any(st.feed == "adt" for st in stale_streams(session, clock)),
    )

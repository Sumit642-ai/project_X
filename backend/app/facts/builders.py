"""Turn normalised staging rows into Facts.

Only source records attributed to a member by an auto_linked or confirmed identity link
produce Facts (records behind a needs_review link wait for a human). Building is idempotent:
a Fact is identified by (source_system, source_record_id, type, key); an identical value is
skipped, a changed value becomes a new Fact and the old one is superseded.
"""

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Row, select
from sqlalchemy.orm import Session

from app.consent import policy
from app.core.clock import PLAN_TZ, Clock
from app.datalayer_mock.identity.models import LINKED_STATUSES, Member, MemberLink
from app.datalayer_mock.identity.sources import PLAN_KEYED_STREAMS, active_rows, adt_source_key
from app.datalayer_mock.ingest.models import Load
from app.datalayer_mock.normalise.concepts import (
    normalise_icd10,
    normalise_lab_row,
    normalise_medication_name,
    normalise_ndc,
)
from app.facts.models import Fact


@dataclass(frozen=True)
class FactSpec:
    type: str
    key: str
    value: dict[str, Any]
    source_record_id: str
    event_date: date | None
    confidence: Decimal = Decimal("1.000")
    sensitivity: str = "none"


@dataclass
class BuildSummary:
    created: int = 0
    unchanged: int = 0
    superseded: int = 0
    unattributed: dict[str, int] = field(default_factory=dict)


def _json(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def value_hash(spec: FactSpec) -> str:
    canonical = json.dumps(
        [
            spec.type,
            spec.key,
            _json(spec.value),
            spec.event_date and spec.event_date.isoformat(),
            str(spec.confidence),
            spec.sensitivity,
        ],
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _local_date(value: datetime | None) -> date | None:
    return value.astimezone(PLAN_TZ).date() if value else None


def _drug_key(concept_ingredient: str | None, fallback: str) -> str:
    return concept_ingredient or fallback


# --- per-stream fact definitions ------------------------------------------------------------

Builder = Callable[[Row[Any], dict[str, Any]], Iterator[FactSpec]]


def pharmacy_facts(row: Row[Any], ctx: dict[str, Any]) -> Iterator[FactSpec]:
    concept = normalise_ndc(row.ndc, f"{row.drug_name} {row.strength}")
    dispensed = row.claim_status == "paid"
    formulary = ctx["formulary"].get(row.ndc)
    yield FactSpec(
        "medication",
        _drug_key(concept.ingredient, f"NDC:{row.ndc}"),
        {
            "source_kind": "pharmacy_claim",
            "ndc": row.ndc,
            "product": row.drug_name,
            "strength": row.strength,
            "sig": row.sig,
            "quantity": row.quantity,
            "fill_date": row.fill_date,
            "days_supply": row.days_supply,
            # annex convention: covered through = fill date + days supply
            "covered_through": row.fill_date + timedelta(days=row.days_supply)
            if dispensed
            else None,
            "claim_status": row.claim_status,
            "dispensed": dispensed,
            "reject_code": row.reject_code,
            "reject_reason": row.reject_reason,
            "prescriber": row.prescriber,
            "pharmacy": row.pharmacy_name,
            "drug_class": concept.drug_class,
            "mapped": concept.mapped,
            "formulary_tier": formulary.tier if formulary else None,
            "formulary_status": formulary.formulary_status if formulary else None,
            "pa_required": formulary.pa_required if formulary else None,
        },
        row.rx_claim_id,
        row.fill_date,
    )
    if row.pharmacy_phone_on_profile:
        yield FactSpec(
            "contact_point",
            row.pharmacy_phone_on_profile,
            {
                "number": row.pharmacy_phone_on_profile,
                "source": "pharmacy",
                "owner_type": "member",
                "pharmacy": row.pharmacy_name,
            },
            f"profile:{row.member_id}:{row.pharmacy_phone_on_profile}",
            row.profile_phone_as_of,
        )


def claim_facts(row: Row[Any], ctx: dict[str, Any]) -> Iterator[FactSpec]:
    yield FactSpec(
        "event",
        f"claim:{row.claim_type}",
        {
            "claim_id": row.claim_id,
            "claim_type": row.claim_type,
            "claim_form": row.claim_form,
            "service_date": row.service_date,
            "service_end_date": row.service_end_date,
            "status": row.status,
            "received_date": row.received_date,
            "paid_date": row.paid_date,
            "claims_loaded_through": row.claims_loaded_through,
            "icd10_codes": row.icd10_codes,
        },
        row.claim_id,
        row.service_date,
    )
    for code in row.icd10_codes or []:
        concept = normalise_icd10(code)
        yield FactSpec(
            "diagnosis",
            code,
            {
                "code": code,
                "display": concept.display,
                "condition_group": concept.condition_group,
                "mapped": concept.mapped,
                "source_kind": "claim",
                "claim_id": row.claim_id,
            },
            f"{row.claim_id}#{code}",
            row.service_date,
        )


def lab_facts(row: Row[Any], ctx: dict[str, Any]) -> Iterator[FactSpec]:
    concept = normalise_lab_row(row)
    yield FactSpec(
        "lab",
        concept.concept or f"LOINC:{row.loinc}",
        {
            "loinc": row.loinc,
            "test_name": row.test_name,
            "value": row.result_value,
            "unit": row.unit,
            "mapped": concept.mapped,
            "source": row.source,
        },
        row.result_id,
        row.collected_date,
    )


def eligibility_facts(row: Row[Any], ctx: dict[str, Any]) -> Iterator[FactSpec]:
    yield FactSpec(
        "coverage",
        f"plan:{row.lob}",
        {
            "plan": row.plan,
            "state": row.state,
            "lob": row.lob,
            "effective_date": row.effective_date,
            "term_date": row.term_date,
            "pcp": row.pcp,
            "language": row.language,
            "medicaid_redetermination_due": row.medicaid_redetermination_due,
        },
        row.member_id,
        row.effective_date,
    )
    if row.phone:
        yield FactSpec(
            "contact_point",
            row.phone,
            {
                "number": row.phone,
                "source": "eligibility",
                "owner_type": "member",
                "phone_type": row.phone_type,
            },
            f"{row.member_id}#phone",
            row.phone_as_of,
        )
    if row.address_line1:
        yield FactSpec(
            "contact_point",
            "address",
            {
                "address_line1": row.address_line1,
                "city": row.city,
                "zip": row.zip,
                "source": "eligibility",
            },
            f"{row.member_id}#address",
            row.address_as_of,
        )
    if row.rep_name:
        yield FactSpec(
            "consent",
            "personal_representative",
            {
                "consent_type": "personal_representative",
                "representative_name": row.rep_name,
                "relationship": row.rep_relationship,
                "expires_date": row.rep_form_expires,
                "source": "eligibility",
            },
            f"{row.member_id}#rep",
            None,
        )


def adt_facts(row: Row[Any], ctx: dict[str, Any]) -> Iterator[FactSpec]:
    kind = {"A01": "admission", "A03": "discharge", "A04": "registration"}[row.trigger_event]
    yield FactSpec(
        "event",
        f"adt:{kind}",
        {
            "trigger": row.trigger_event,
            "facility": row.sending_facility,
            "patient_class": row.patient_class,
            "admit_at": row.admit_at,
            "discharge_at": row.discharge_at,
            "discharge_disposition": row.discharge_disposition,
            # ADT carries no diagnosis: the reason for the visit stays unknown, never inferred.
            "diagnosis_code": row.diagnosis_code,
            "message_at": row.message_at,
            "visit_number": row.visit_number,
            "patient_id": row.patient_id,
        },
        row.message_control_id,
        _local_date(row.event_at or row.message_at),
    )


DOCUMENT_TYPES = {
    "18842-5": "discharge_summary",
    "34111-5": "ed_note",
    "10160-0": "medication_list",
}


def document_facts(row: Row[Any], ctx: dict[str, Any]) -> Iterator[FactSpec]:
    doc_type = DOCUMENT_TYPES[row.document_type_code]
    day = _local_date(row.effective_at)
    base = {
        "document_id": row.document_id,
        "document_type": doc_type,
        "facility": row.author_organization,
    }
    for index, med in enumerate(row.medications or []):
        concept = normalise_medication_name(med.get("name"), med.get("dose"))
        yield FactSpec(
            "medication",
            _drug_key(concept.ingredient, f"name:{med.get('name')}"),
            {
                **base,
                "source_kind": "hospital_document",
                "product": med.get("name"),
                "strength": med.get("dose"),
                "sig": med.get("sig"),
                "drug_class": concept.drug_class,
                "mapped": concept.mapped,
            },
            f"{row.document_id}#med{index}",
            day,
        )
    for index, problem in enumerate(row.problems or []):
        diagnosis = normalise_icd10(problem.get("code"), problem.get("text"))
        yield FactSpec(
            "diagnosis",
            problem.get("code") or f"text:{problem.get('text')}",
            {
                **base,
                "source_kind": "hospital_document",
                "code": problem.get("code"),
                "display": diagnosis.display or problem.get("text"),
                "condition_group": diagnosis.condition_group,
                "mapped": diagnosis.mapped,
            },
            f"{row.document_id}#problem{index}",
            day,
        )
    yield FactSpec(
        "event",
        f"document:{doc_type}",
        {
            **base,
            "encounter_start": row.encounter_start,
            "encounter_end": row.encounter_end,
            "discharge_disposition": row.discharge_disposition,
            "discharge_address": row.discharge_address,
            "follow_up": row.follow_up,
            "notes": row.notes,
        },
        row.document_id,
        day,
    )
    if row.discharge_phone:
        yield FactSpec(
            "contact_point",
            row.discharge_phone,
            {
                **base,
                "number": row.discharge_phone,
                "source": "discharge summary",
                "owner_type": "facility",
                "address": row.discharge_address,
            },
            f"{row.document_id}#phone",
            day,
        )


def _simple(
    fact_type: str,
    key: Callable[[Row[Any]], str],
    id_column: str,
    date_column: str | None,
    sensitivity: str = "none",
) -> Builder:
    def build(row: Row[Any], ctx: dict[str, Any]) -> Iterator[FactSpec]:
        values = {
            k: v
            for k, v in row._mapping.items()
            if k not in ("id", "load_id", "source_row", "member_id")
        }
        event_date = getattr(row, date_column) if date_column else None
        if isinstance(event_date, datetime):
            event_date = _local_date(event_date)
        yield FactSpec(
            fact_type,
            key(row),
            values,
            str(getattr(row, id_column)),
            event_date,
            sensitivity=sensitivity,
        )

    return build


def contact_point_facts(row: Row[Any], ctx: dict[str, Any]) -> Iterator[FactSpec]:
    yield FactSpec(
        "contact_point",
        row.phone,
        {
            "number": row.phone,
            "source": row.source,
            "owner_type": row.owner_type,
            "owner_name": row.owner_name,
            "relationship": row.relationship,
            "last_verified": row.last_verified,
            "last_outcome": row.last_outcome,
            "best_time": row.best_time,
            "cm_confidence": row.confidence,
            "authorized": row.authorized,
            "from_cm_platform": True,
        },
        row.contact_id,
        row.last_verified,
    )


def program_note_facts(row: Row[Any], ctx: dict[str, Any]) -> Iterator[FactSpec]:
    """Substance-use program records: Part 2 only if the program is on the allowlist;
    any other program is masked as unverified until someone classifies it."""
    values = {
        k: v
        for k, v in row._mapping.items()
        if k not in ("id", "load_id", "source_row", "member_id")
    }
    yield FactSpec(
        "event",
        "part2:counselling_note",
        values,
        row.note_id,
        row.service_date,
        sensitivity=policy.program_sensitivity(row.program_name),
    )


BUILDERS: dict[str, Builder] = {
    "pharmacy_ncpdp": pharmacy_facts,
    "claims_837": claim_facts,
    "lab_results": lab_facts,
    "eligibility_834": eligibility_facts,
    "adt": adt_facts,
    "ccda": document_facts,
    "auth_requests": _simple(
        "coverage", lambda r: f"auth:{r.item_code or r.item}", "auth_id", "requested_date"
    ),
    "care_gaps": _simple("care_gap", lambda r: r.measure, "gap_id", "anchor_date"),
    "ltss_aide_hours": _simple("service", lambda r: r.service, "member_id", "as_of"),
    "nemt_trips": _simple("service", lambda r: "nemt", "trip_id", "trip_date"),
    "screens": _simple("sdoh", lambda r: r.domain, "screen_id", "screen_date"),
    "new_dawn_notes": program_note_facts,
    "consents": _simple("consent", lambda r: r.consent_type, "consent_id", "granted_date"),
    "contact_points": contact_point_facts,
    "outreach": _simple("event", lambda r: f"outreach:{r.channel}", "outreach_id", "attempted_at"),
    "preferences": _simple("preference", lambda r: "language", "member_id", None),
    "risk_scores": _simple("risk", lambda r: "plan_risk", "member_id", "scored_at"),
    "hie_requests": _simple(
        "event", lambda r: f"document_request:{r.document_type}", "request_id", "requested_at"
    ),
}


# --- attribution and writing ----------------------------------------------------------------


def _source_key(stream: str, row: Row[Any], members: set[str]) -> tuple[str, str]:
    if stream == "eligibility_834":
        return "eligibility", row.member_id
    if stream == "adt":
        return adt_source_key(row.assigning_authority, row.patient_id)
    if stream == "ccda":
        return ("ccda" if row.patient_id in members else "hospital"), row.patient_id
    if stream in PLAN_KEYED_STREAMS:
        return stream, row.member_id
    raise KeyError(stream)


def _attribution(session: Session) -> dict[tuple[str, str], MemberLink]:
    links = session.scalars(
        select(MemberLink).where(MemberLink.status.in_(LINKED_STATUSES)).order_by(MemberLink.id)
    )
    return {(link.source_system, link.source_record_id): link for link in links}


def build_facts(session: Session, clock: Clock) -> BuildSummary:
    members = set(session.scalars(select(Member.member_id)))
    links = _attribution(session)
    loaded_at = {load.id: load.loaded_at for load in session.scalars(select(Load))}
    current: dict[tuple[str, str, str, str], Fact] = {
        (f.source_system, f.source_record_id, f.type, f.key): f
        for f in session.scalars(select(Fact).where(Fact.superseded_by.is_(None)))
    }
    ctx: dict[str, Any] = {
        "formulary": {row.ndc: row for row in active_rows(session, "formulary")},
    }
    summary = BuildSummary()
    now = clock.now()

    # Several rows can describe the same fact (e.g. the pharmacy profile phone on every fill):
    # keep one spec per identity, the latest-dated, so repeated builds are stable.
    wanted: dict[tuple[str, str, str, str], tuple[FactSpec, str, Row[Any], MemberLink]] = {}
    for stream, builder in BUILDERS.items():
        for row in active_rows(session, stream):
            link = links.get(_source_key(stream, row, members))
            if link is None:
                summary.unattributed[stream] = summary.unattributed.get(stream, 0) + 1
                continue
            for spec in builder(row, ctx):
                identity = (stream, spec.source_record_id, spec.type, spec.key)
                digest = value_hash(spec)
                chosen = wanted.get(identity)
                if chosen is None or (spec.event_date or date.min, digest) > (
                    chosen[0].event_date or date.min,
                    chosen[1],
                ):
                    wanted[identity] = (spec, digest, row, link)

    for identity, (spec, digest, row, link) in wanted.items():
        previous = current.get(identity)
        if previous is not None and previous.value_hash == digest:
            summary.unchanged += 1
            continue
        fact = Fact(
            member_id=link.member_id,
            link_id=link.id,
            type=spec.type,
            key=spec.key,
            value=_json(spec.value),
            source_system=identity[0],
            source_record_id=spec.source_record_id,
            load_id=row.load_id,
            source_row=row.source_row,
            event_date=spec.event_date,
            loaded_at=loaded_at.get(row.load_id) or now,
            confidence=spec.confidence,
            status="raw",
            sensitivity=spec.sensitivity,
            value_hash=digest,
            created_at=now,
        )
        session.add(fact)
        session.flush()
        if previous is not None:
            previous.superseded_by = fact.id  # corrections create new Facts
            summary.superseded += 1
        summary.created += 1
    session.flush()
    return summary

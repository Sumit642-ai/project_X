"""Identity-bearing source records, read from the active staging loads.

- eligibility rows: keyed by plan member ID, with demographics
- hospital records (ADT and C-CDA) whose patient ID is not plan-assigned: grouped by patient ID
  under source_system "hospital", demographics from the latest ADT message (else the document)
- every other feed: keyed by the plan member ID it carries, no demographics
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Row, select
from sqlalchemy.orm import Session

from app.datalayer_mock.identity.scoring import Demographics
from app.datalayer_mock.ingest.models import PASS, Load
from app.datalayer_mock.ingest.staging import STAGING_TABLES

PLAN_AUTHORITY = "EVERGREEN"
PLAN_KEYED_STREAMS = (
    "claims_837",
    "pharmacy_ncpdp",
    "auth_requests",
    "care_gaps",
    "lab_results",
    "hie_requests",
    "ltss_aide_hours",
    "nemt_trips",
    "screens",
    "new_dawn_notes",
    "consents",
    "contact_points",
    "outreach",
    "preferences",
    "risk_scores",
)


@dataclass
class SourceRecord:
    source_system: str
    source_record_id: str
    plan_member_id: str | None
    demographics: Demographics | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    term_date: date | None = None


def _ref(stream: str, row: Row[Any]) -> dict[str, Any]:
    return {"stream": stream, "load_id": row.load_id, "source_row": row.source_row}


def active_rows(session: Session, stream: str) -> list[Row[Any]]:
    table = STAGING_TABLES[stream]
    active = select(Load.id).where(
        Load.stream == stream, Load.status == PASS, Load.is_active.is_(True)
    )
    return list(
        session.execute(select(table).where(table.c.load_id.in_(active)).order_by(table.c.id))
    )


def adt_source_key(assigning_authority: str | None, patient_id: str) -> tuple[str, str]:
    """(source_system, source_record_id) for an ADT patient."""
    if assigning_authority == PLAN_AUTHORITY:
        return "adt", patient_id
    return "hospital", patient_id


def eligibility_demographics(row: Row[Any]) -> Demographics:
    return Demographics(
        row.first_name,
        row.last_name,
        row.dob,
        row.sex,
        row.address_line1,
        row.city,
        row.zip,
        row.phone,
    )


def extract_sources(session: Session, member_ids: set[str]) -> list[SourceRecord]:
    sources: dict[tuple[str, str], SourceRecord] = {}

    def record(system: str, record_id: str, plan_id: str | None) -> SourceRecord:
        key = (system, record_id)
        if key not in sources:
            sources[key] = SourceRecord(system, record_id, plan_id)
        return sources[key]

    for row in active_rows(session, "eligibility_834"):
        source = record("eligibility", row.member_id, row.member_id)
        source.demographics = eligibility_demographics(row)
        source.term_date = row.term_date
        source.evidence.append(_ref("eligibility_834", row))

    latest_adt: dict[tuple[str, str], Any] = {}
    for row in active_rows(session, "adt"):
        system, record_id = adt_source_key(row.assigning_authority, row.patient_id)
        source = record(system, record_id, record_id if system == "adt" else None)
        source.evidence.append(_ref("adt", row))
        if system == "hospital":
            previous = latest_adt.get((system, record_id))
            if previous is None or row.message_at >= previous.message_at:
                latest_adt[(system, record_id)] = row
                source.demographics = Demographics(
                    row.first_name,
                    row.last_name,
                    row.dob,
                    row.sex,
                    row.address_line1,
                    row.city,
                    row.zip,
                    row.phone,
                )

    for row in active_rows(session, "ccda"):
        plan_assigned = row.patient_id in member_ids
        system = "ccda" if plan_assigned else "hospital"
        source = record(system, row.patient_id, row.patient_id if plan_assigned else None)
        source.evidence.append(_ref("ccda", row))
        if not plan_assigned and source.demographics is None:
            source.demographics = Demographics(
                row.first_name, row.last_name, row.dob, row.sex, None, None, None, None
            )

    for stream in PLAN_KEYED_STREAMS:
        for row in active_rows(session, stream):
            record(stream, row.member_id, row.member_id).evidence.append(_ref(stream, row))

    return list(sources.values())

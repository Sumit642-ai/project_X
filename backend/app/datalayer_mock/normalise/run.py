"""Rebuild norm_* tables and the unmapped_codes report from the active staging loads."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Row, delete, select
from sqlalchemy.orm import Session

from app.datalayer_mock.ingest.models import PASS, Load
from app.datalayer_mock.ingest.staging import STAGING_TABLES
from app.datalayer_mock.normalise.concepts import (
    DiagnosisConcept,
    DrugConcept,
    normalise_claim_row,
    normalise_document_row,
    normalise_lab_row,
    normalise_pharmacy_row,
)
from app.datalayer_mock.normalise.models import NormDiagnosis, NormLab, NormMedication, UnmappedCode


@dataclass(frozen=True)
class NormalisationReport:
    diagnoses: int
    medications: int
    labs: int
    unmapped: list[UnmappedCode]


def _active_rows(session: Session, stream: str) -> Iterator[Row[Any]]:
    table = STAGING_TABLES[stream]
    active = select(Load.id).where(
        Load.stream == stream, Load.status == PASS, Load.is_active.is_(True)
    )
    yield from session.execute(
        select(table).where(table.c.load_id.in_(active)).order_by(table.c.id)
    )


def run_normalisation(session: Session) -> NormalisationReport:
    for model in (NormDiagnosis, NormMedication, NormLab, UnmappedCode):
        session.execute(delete(model))

    unmapped: dict[tuple[str, str | None, str | None, str], UnmappedCode] = {}

    def note(system: str, code: str | None, display: str | None, stream: str, load_id: int) -> None:
        key = (system, code, None if code else display, stream)
        if key in unmapped:
            unmapped[key].occurrences += 1
        else:
            unmapped[key] = UnmappedCode(
                code_system=system,
                code=code,
                display=display,
                source_stream=stream,
                occurrences=1,
                first_load_id=load_id,
            )

    def lineage(stream: str, row: Row[Any], member_id: str | None) -> dict[str, Any]:
        return {
            "source_stream": stream,
            "load_id": row.load_id,
            "source_row": row.source_row,
            "member_id": member_id,
        }

    def add_diagnosis(
        stream: str, row: Row[Any], member_id: str | None, concept: DiagnosisConcept
    ) -> None:
        session.add(
            NormDiagnosis(
                **lineage(stream, row, member_id),
                raw_code=concept.raw_code,
                raw_display=concept.raw_display,
                mapped=concept.mapped,
                display=concept.display,
                condition_group=concept.condition_group,
            )
        )
        if not concept.mapped:
            note("ICD-10", concept.raw_code, concept.raw_display, stream, row.load_id)

    def add_medication(
        stream: str, row: Row[Any], member_id: str | None, concept: DrugConcept
    ) -> None:
        session.add(
            NormMedication(
                **lineage(stream, row, member_id),
                raw_code=concept.raw_code,
                raw_display=concept.raw_display,
                mapped=concept.mapped,
                match_method=concept.match_method,
                ingredient=concept.ingredient,
                strength=concept.strength,
                drug_class=concept.drug_class,
            )
        )
        if not concept.mapped:
            note(
                "NDC" if concept.raw_code else "DRUG-NAME",
                concept.raw_code,
                concept.raw_display,
                stream,
                row.load_id,
            )

    counts = {"diagnoses": 0, "medications": 0, "labs": 0}
    for row in _active_rows(session, "claims_837"):
        for diagnosis in normalise_claim_row(row):
            add_diagnosis("claims_837", row, row.member_id, diagnosis)
            counts["diagnoses"] += 1
    for row in _active_rows(session, "pharmacy_ncpdp"):
        add_medication("pharmacy_ncpdp", row, row.member_id, normalise_pharmacy_row(row))
        counts["medications"] += 1
    for row in _active_rows(session, "ccda"):
        problems, medications = normalise_document_row(row)
        for diagnosis in problems:
            add_diagnosis("ccda", row, row.patient_id, diagnosis)
            counts["diagnoses"] += 1
        for medication in medications:
            add_medication("ccda", row, row.patient_id, medication)
            counts["medications"] += 1
    for row in _active_rows(session, "lab_results"):
        lab = normalise_lab_row(row)
        session.add(
            NormLab(
                **lineage("lab_results", row, row.member_id),
                raw_code=lab.raw_code,
                raw_display=lab.raw_display,
                mapped=lab.mapped,
                concept=lab.concept,
                value=lab.value,
                unit=lab.unit,
            )
        )
        counts["labs"] += 1
        if not lab.mapped:
            note("LOINC", lab.raw_code, lab.raw_display, "lab_results", row.load_id)

    session.add_all(unmapped.values())
    session.flush()
    return NormalisationReport(**counts, unmapped=list(unmapped.values()))

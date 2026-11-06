"""Map raw codes to concepts. An unmapped code is never dropped: the raw code and display are
kept and the result is flagged mapped=False."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.datalayer_mock.normalise import terminology


@dataclass(frozen=True)
class DiagnosisConcept:
    raw_code: str | None
    raw_display: str | None
    mapped: bool
    display: str | None = None
    condition_group: str | None = None


@dataclass(frozen=True)
class DrugConcept:
    raw_code: str | None  # NDC when the source has one
    raw_display: str | None
    mapped: bool
    match_method: str | None = None  # ndc | name
    ingredient: str | None = None
    strength: str | None = None
    drug_class: str | None = None


@dataclass(frozen=True)
class LabConcept:
    raw_code: str | None
    raw_display: str | None
    mapped: bool
    concept: str | None = None
    value: Decimal | None = None
    unit: str | None = None


def normalise_icd10(code: str | None, display: str | None = None) -> DiagnosisConcept:
    entry = terminology.icd10().get(code.strip().upper()) if code else None
    if entry is None:
        return DiagnosisConcept(code, display, mapped=False)
    return DiagnosisConcept(code, display, True, entry.display, entry.condition_group)


def normalise_ndc(ndc: str | None, display: str | None = None) -> DrugConcept:
    entry = terminology.ndc().get(ndc.strip()) if ndc else None
    if entry is None:
        return DrugConcept(ndc, display, mapped=False)
    return DrugConcept(
        ndc, display, True, "ndc", entry.ingredient, entry.strength, entry.drug_class
    )


def normalise_medication_name(name: str | None, dose: str | None = None) -> DrugConcept:
    """For documents that carry a drug name and dose but no NDC (e.g. C-CDA med lists)."""
    raw_display = " ".join(p for p in (name, dose) if p) or None
    entry = terminology.drug_names().get(terminology.name_key(name)) if name else None
    if entry is None:
        return DrugConcept(None, raw_display, mapped=False)
    # Strength comes from the document, not from whichever NDC matched the name.
    return DrugConcept(None, raw_display, True, "name", entry.ingredient, dose, entry.drug_class)


def normalise_loinc(
    code: str | None,
    display: str | None = None,
    value: Decimal | None = None,
    unit: str | None = None,
) -> LabConcept:
    entry = terminology.loinc().get(code.strip()) if code else None
    if entry is None:
        return LabConcept(code, display, False, value=value, unit=unit)
    return LabConcept(code, display, True, entry.concept, value, unit)


# --- staging rows -> concepts ---------------------------------------------------------------


def normalise_claim_row(row: Any) -> list[DiagnosisConcept]:
    return [normalise_icd10(code) for code in (row.icd10_codes or [])]


def normalise_pharmacy_row(row: Any) -> DrugConcept:
    return normalise_ndc(row.ndc, f"{row.drug_name} {row.strength}".strip())


def normalise_lab_row(row: Any) -> LabConcept:
    return normalise_loinc(row.loinc, row.test_name, row.result_value, row.unit)


def normalise_document_row(row: Any) -> tuple[list[DiagnosisConcept], list[DrugConcept]]:
    problems = [normalise_icd10(p.get("code"), p.get("text")) for p in (row.problems or [])]
    medications = [
        normalise_medication_name(m.get("name"), m.get("dose")) for m in (row.medications or [])
    ]
    return problems, medications

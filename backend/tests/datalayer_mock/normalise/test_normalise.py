import csv
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.datalayer_mock.ingest import ingest_file
from app.datalayer_mock.ingest.models import PASS
from app.datalayer_mock.normalise import (
    normalise_icd10,
    normalise_loinc,
    normalise_medication_name,
    normalise_ndc,
    normalise_pharmacy_row,
    run_normalisation,
)
from app.datalayer_mock.normalise.models import NormDiagnosis, NormLab, NormMedication, UnmappedCode

UNKNOWN_NDC = "99999-9999-99"


def _pharmacy_rows(raw: Path) -> list[dict[str, str]]:
    (path,) = (raw / "pharmacy").glob("pharmacy_ncpdp_*.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_every_ndc_in_raymonds_data_maps_to_the_right_drug_class(generated_raw: Path) -> None:
    raymond = [r for r in _pharmacy_rows(generated_raw) if r["member_id"] == "SYN-001"]
    classes = {r["drug_name"]: normalise_ndc(r["ndc"], r["drug_name"]) for r in raymond}

    assert {name: (c.mapped, c.drug_class) for name, c in classes.items()} == {
        "Furosemide": (True, "loop diuretic"),
        "Metoprolol succinate": (True, "beta blocker"),
        "Sacubitril/valsartan": (True, "ARNI"),
    }
    assert classes["Furosemide"].strength == "40 mg"


def test_raymonds_hospital_med_list_maps_by_name_with_the_document_dose() -> None:
    furosemide = normalise_medication_name("Furosemide", "80 mg")
    arni = normalise_medication_name("Sacubitril/valsartan", "24/26 mg")

    assert (furosemide.drug_class, furosemide.strength, furosemide.match_method) == (
        "loop diuretic",
        "80 mg",
        "name",
    )
    assert (arni.ingredient, arni.drug_class) == ("sacubitril / valsartan", "ARNI")


def test_every_code_in_the_generated_feeds_maps(ingested: Session) -> None:
    run_normalisation(ingested)

    unmapped_meds = ingested.scalars(select(NormMedication).where(~NormMedication.mapped)).all()
    unmapped_labs = ingested.scalars(select(NormLab).where(~NormLab.mapped)).all()
    coded_unmapped = ingested.scalars(
        select(NormDiagnosis).where(~NormDiagnosis.mapped, NormDiagnosis.raw_code.is_not(None))
    ).all()
    assert unmapped_meds == [] and unmapped_labs == [] and coded_unmapped == []


def test_condition_groups_cover_the_annex_conditions() -> None:
    groups = {
        code: normalise_icd10(code).condition_group
        for code in (
            "I50.22",
            "J44.9",
            "J45.51",
            "E11.65",
            "N18.31",
            "N18.4",
            "F31.81",
            "F11.20",
            "F03.B0",
        )
    }

    assert groups == {
        "I50.22": "HF",
        "J44.9": "COPD",
        "J45.51": "asthma",
        "E11.65": "diabetes",
        "N18.31": "CKD",
        "N18.4": "CKD",
        "F31.81": "bipolar",
        "F11.20": "OUD",
        "F03.B0": "dementia",
    }


def test_loinc_concepts_for_the_annex_labs() -> None:
    assert [normalise_loinc(c).concept for c in ("33762-6", "4548-4", "33914-3")] == [
        "nt_probnp",
        "hba1c",
        "egfr",
    ]


def test_unmapped_codes_keep_raw_code_and_display() -> None:
    drug = normalise_ndc(UNKNOWN_NDC, "Mysteryzine 10 mg")
    diagnosis = normalise_icd10("Z99.999", "Something rare")
    lab = normalise_loinc("0000-0", "Unknown test", Decimal("1.5"), "mg/dL")

    assert (drug.mapped, drug.raw_code, drug.raw_display, drug.drug_class) == (
        False,
        UNKNOWN_NDC,
        "Mysteryzine 10 mg",
        None,
    )
    assert (diagnosis.mapped, diagnosis.raw_code, diagnosis.raw_display) == (
        False,
        "Z99.999",
        "Something rare",
    )
    assert (lab.mapped, lab.raw_code, lab.value, lab.unit) == (
        False,
        "0000-0",
        Decimal("1.5"),
        "mg/dL",
    )


def test_pharmacy_row_display_is_drug_name_and_strength() -> None:
    row = SimpleNamespace(ndc=UNKNOWN_NDC, drug_name="Mysteryzine", strength="10 mg")
    assert normalise_pharmacy_row(row).raw_display == "Mysteryzine 10 mg"


def test_injected_unknown_ndc_is_reported_and_still_visible(
    ingested: Session, clock: FixedClock, landing: Path, generated_raw: Path, tmp_path: Path
) -> None:
    rows = _pharmacy_rows(generated_raw)
    injected = {
        **rows[0],
        "rx_claim_id": "SYN-RX-999999",
        "member_id": "SYN-001",
        "ndc": UNKNOWN_NDC,
        "drug_name": "Mysteryzine",
        "strength": "10 mg",
    }
    path = tmp_path / "pharmacy" / "pharmacy_ncpdp_20261109.csv"
    path.parent.mkdir()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows([*rows, injected])
    assert ingest_file(ingested, path, clock=clock, landing_root=landing).status == PASS

    report = run_normalisation(ingested)

    (reported,) = [u for u in report.unmapped if u.code_system == "NDC"]
    assert (reported.code, reported.display, reported.occurrences) == (
        UNKNOWN_NDC,
        "Mysteryzine 10 mg",
        1,
    )
    stored = ingested.scalars(select(UnmappedCode).where(UnmappedCode.code == UNKNOWN_NDC)).one()
    assert stored.source_stream == "pharmacy_ncpdp"
    visible = ingested.scalars(
        select(NormMedication).where(NormMedication.raw_code == UNKNOWN_NDC)
    ).one()
    assert (visible.member_id, visible.mapped, visible.raw_display, visible.drug_class) == (
        "SYN-001",
        False,
        "Mysteryzine 10 mg",
        None,
    )
    # Mapped rows from the same load are untouched.
    assert ingested.scalars(
        select(NormMedication).where(
            NormMedication.member_id == "SYN-001", NormMedication.drug_class == "ARNI"
        )
    ).one()


def test_document_problem_without_a_code_is_kept_as_unmapped(ingested: Session) -> None:
    run_normalisation(ingested)

    (kayla,) = ingested.scalars(
        select(NormDiagnosis).where(
            NormDiagnosis.member_id == "SYN-004", NormDiagnosis.source_stream == "ccda"
        )
    ).all()
    assert (kayla.mapped, kayla.raw_code, kayla.raw_display) == (
        False,
        None,
        "Bipolar I disorder, stabilised",
    )
    assert (
        ingested.scalars(
            select(UnmappedCode).where(UnmappedCode.display == "Bipolar I disorder, stabilised")
        )
        .one()
        .code_system
        == "ICD-10"
    )


def test_normalisation_is_rebuilt_not_duplicated(ingested: Session) -> None:
    first = run_normalisation(ingested)
    second = run_normalisation(ingested)

    assert (first.diagnoses, first.medications, first.labs) == (
        second.diagnoses,
        second.medications,
        second.labs,
    )
    assert len(ingested.scalars(select(NormMedication)).all()) == second.medications

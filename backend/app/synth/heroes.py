"""The five hero members, transcribed from annex.md (Sheets 1-10).

Values the annex does not give (dates of birth, cities, ZIPs, record IDs, exact times inside a
stated month) are filled minimally; docs/data-feeds.md lists every such choice.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from app.synth.catalog import CLAIMS_LOADED_THROUGH, DRUG_BY_KEY, LOAD_DATES, PLAN, STATE, ndc
from app.synth.ccda_builder import CcdaDocument, Medication
from app.synth.dataset import Dataset, at
from app.synth.hl7_builder import AdtEvent

D = date


def _eligibility(ds: Dataset) -> None:
    common: dict[str, Any] = {"plan": PLAN, "state": STATE}
    ds.add(
        "eligibility_834",
        **common,
        member_id="SYN-001",
        last_name="Tull",
        first_name="Raymond",
        dob=D(1950, 4, 12),
        sex="M",
        lob="MA-PPO",
        language="en",
        pcp="Dr A. Lindqvist",
        phone="555-0177",
        phone_type="landline",
        phone_as_of=D(2023, 2, 1),
        address_line1="12 Larch St",
        city="Columbus",
        zip="43204",
        address_as_of=D(2023, 2, 1),
        effective_date=D(2019, 1, 1),
        rep_name="Joan Tull",
        rep_relationship="wife",
        rep_form_expires=D(2027, 5, 31),
    )
    ds.add(
        "eligibility_834",
        **common,
        member_id="SYN-002",
        last_name="Pham",
        first_name="Anh",
        dob=D(1958, 1, 30),
        sex="F",
        lob="MA-PPO",
        language="vi",
        pcp="Dr T. Nguyen",
        phone="555-0121",
        phone_as_of=D(2025, 6, 1),
        address_line1="88 Pine Ave",
        city="Columbus",
        zip="43229",
        address_as_of=D(2025, 6, 1),
        effective_date=D(2023, 1, 1),
    )
    # PCP blank: none attributed (no visit in 14 months).
    ds.add(
        "eligibility_834",
        **common,
        member_id="SYN-003",
        last_name="Pruitt",
        first_name="Darnell",
        dob=D(1972, 2, 3),
        sex="M",
        lob="DUAL",
        language="en",
        phone="555-0110",
        address_line1="401 Elm Ct Apt 3",
        city="Dayton",
        zip="45405",
        address_as_of=D(2024, 1, 1),
        effective_date=D(2021, 7, 1),
    )
    ds.add(
        "eligibility_834",
        **common,
        member_id="SYN-004",
        last_name="Morrison",
        first_name="Kayla",
        dob=D(1992, 6, 18),
        sex="F",
        lob="MEDICAID",
        language="en",
        pcp="Riverside FQHC",
        phone="555-0133",
        address_line1="9 Birch Rd",
        city="Columbus",
        zip="43223",
        address_as_of=D(2025, 12, 1),
        effective_date=D(2024, 4, 1),
    )
    # I-14: earlier enrolment under the maiden name, never merged.
    ds.add(
        "eligibility_834",
        **common,
        member_id="SYN-004-M",
        last_name="Delaney",
        first_name="Kayla",
        dob=D(1992, 6, 18),
        sex="F",
        lob="MEDICAID",
        language="en",
        phone="555-0134",
        address_line1="70 Oak St",
        city="Columbus",
        zip="43207",
        effective_date=D(2022, 2, 1),
        term_date=D(2023, 6, 30),
    )
    ds.add(
        "eligibility_834",
        **common,
        member_id="SYN-005",
        last_name="Joseph",
        first_name="Rose-Marie",
        dob=D(1942, 8, 25),
        sex="F",
        lob="DSNP",
        language="ht",
        pcp="Dr M. Celestin",
        phone="555-0155",
        phone_as_of=D(2026, 3, 1),
        address_line1="3 Cedar Ln",
        city="Columbus",
        zip="43211",
        address_as_of=D(2026, 3, 1),
        effective_date=D(2024, 1, 1),
        rep_name="Mirlande Joseph",
        rep_relationship="daughter",
        rep_form_expires=D(2026, 9, 30),
        medicaid_redetermination_due=D(2026, 12, 31),
    )


def _claims(ds: Dataset) -> None:
    def claim(
        member: str,
        form: str,
        kind: str,
        service: date,
        codes: list[str],
        status: str,
        received: date,
        paid: date | None,
        end: date | None = None,
    ) -> None:
        ds.add(
            "claims_837",
            claim_id=ds.next_id("CLM"),
            member_id=member,
            claim_form=form,
            claim_type=kind,
            service_date=service,
            service_end_date=end,
            icd10_codes=codes,
            status=status,
            received_date=received,
            paid_date=paid,
            claims_loaded_through=CLAIMS_LOADED_THROUGH,
        )

    claim(
        "SYN-001",
        "837P",
        "office",
        D(2026, 8, 14),
        ["I50.22", "N18.31"],
        "paid",
        D(2026, 8, 20),
        D(2026, 9, 3),
    )
    claim(
        "SYN-002",
        "837P",
        "office",
        D(2026, 3, 10),
        ["E11.65"],
        "paid",
        D(2026, 3, 17),
        D(2026, 4, 2),
    )
    claim(
        "SYN-003", "837I", "ed", D(2026, 8, 19), ["J45.51"], "paid", D(2026, 8, 28), D(2026, 9, 15)
    )
    # Received after the cut-off, still pending.
    claim(
        "SYN-003",
        "837I",
        "ed",
        D(2026, 10, 3),
        ["J45.41", "G89.29"],
        "pending",
        D(2026, 10, 14),
        None,
    )
    claim(
        "SYN-004",
        "837P",
        "bh_outpatient",
        D(2026, 7, 2),
        ["F31.81"],
        "paid",
        D(2026, 7, 10),
        D(2026, 7, 28),
    )
    claim("SYN-005", "837I", "ed", D(2026, 5, 12), ["W19"], "paid", D(2026, 5, 20), D(2026, 6, 10))
    claim("SYN-005", "837I", "ed", D(2026, 8, 28), ["W19"], "paid", D(2026, 9, 5), D(2026, 9, 22))
    claim(
        "SYN-005",
        "837I",
        "home_health",
        D(2026, 9, 1),
        ["N18.4", "F03.B0"],
        "partially_paid",
        D(2026, 9, 15),
        D(2026, 9, 24),
        end=D(2026, 10, 30),
    )

    ds.mark_absent("SYN-001", "claims", "Inpatient claim for 2026-11-03 admission", "I-05")
    ds.mark_absent(
        "SYN-002", "claims", "PCP visit 2026-09-16 (inferred from new prescription)", "I-07"
    )
    ds.mark_absent("SYN-003", "claims", "ED visit 2026-10-28 (ADT only)", "I-10")
    ds.mark_absent("SYN-003", "claims", "ED visit 2026-11-06 (ADT only)", "I-10")


def _fill(
    ds: Dataset,
    member: str,
    drug_key: str,
    strength: str,
    fill: date,
    days: int,
    qty: str,
    *,
    prescriber: str,
    pharmacy: str,
    profile_phone: str,
    profile_as_of: date,
    rejected: tuple[str, str] | None = None,
    pay: str | None = "0.00",
) -> None:
    drug = DRUG_BY_KEY[drug_key]
    ds.add(
        "pharmacy_ncpdp",
        rx_claim_id=ds.next_id("RX"),
        member_id=member,
        fill_date=fill,
        ndc=ndc(drug_key, strength),
        drug_name=drug.name,
        strength=strength,
        sig=drug.sig,
        quantity=Decimal(qty),
        days_supply=days,
        claim_status="rejected" if rejected else "paid",
        reject_code=rejected[0] if rejected else None,
        reject_reason=rejected[1] if rejected else None,
        prescriber=prescriber,
        pharmacy_name=pharmacy,
        pharmacy_phone_on_profile=profile_phone,
        profile_phone_as_of=profile_as_of,
        patient_pay=None if rejected else Decimal(pay) if pay else None,
    )


def _pharmacy(ds: Dataset) -> None:
    raymond: dict[str, Any] = {
        "pharmacy": "Larch Street Pharmacy",
        "profile_phone": "555-0142",
        "profile_as_of": D(2026, 10, 28),
    }
    # I-03: 40 mg covered through 2026-10-30, four days before the 2026-11-03 admission.
    _fill(
        ds,
        "SYN-001",
        "furosemide",
        "40 mg",
        D(2026, 9, 30),
        30,
        "30",
        prescriber="Dr A. Lindqvist",
        **raymond,
    )
    _fill(
        ds,
        "SYN-001",
        "metoprolol_succinate",
        "50 mg",
        D(2026, 10, 15),
        30,
        "30",
        prescriber="Dr A. Lindqvist",
        **raymond,
    )
    _fill(
        ds,
        "SYN-001",
        "sacubitril_valsartan",
        "24/26 mg",
        D(2026, 11, 7),
        30,
        "60",
        prescriber="Dr K. Osei (St Brigid Regional)",
        rejected=("75", "PA required"),
        **raymond,
    )
    ds.mark_absent("SYN-001", "pharmacy", "Furosemide 80 mg fill (new discharge dose)", "I-02")

    anh: dict[str, Any] = {
        "prescriber": "Dr T. Nguyen",
        "pharmacy": "Northside Drug",
        "profile_phone": "555-0121",
        "profile_as_of": D(2026, 9, 16),
    }
    _fill(ds, "SYN-002", "glipizide", "5 mg", D(2026, 5, 1), 90, "90", **anh)
    _fill(ds, "SYN-002", "metformin", "1000 mg", D(2026, 8, 2), 90, "180", **anh)
    _fill(
        ds,
        "SYN-002",
        "semaglutide",
        "0.25 mg",
        D(2026, 9, 16),
        28,
        "1",
        rejected=("70", "non-formulary"),
        **anh,
    )

    darnell: dict[str, Any] = {
        "prescriber": "Dr E. Marsh (Lakeview ED)",
        "pharmacy": "Riverbend Pharmacy",
        "profile_phone": "555-0188",
        "profile_as_of": D(2026, 10, 28),
    }
    _fill(ds, "SYN-003", "albuterol", "90 mcg", D(2026, 8, 20), 25, "1", **darnell)
    _fill(
        ds, "SYN-003", "budesonide_formoterol", "160/4.5 mcg", D(2026, 10, 28), 30, "1", **darnell
    )

    # Riverside FQHC primary care is NOT a Part 2 program: this fill stays visible (I-12).
    kayla: dict[str, Any] = {"pharmacy": "Maple Community Pharmacy", "profile_phone": "555-0133"}
    _fill(
        ds,
        "SYN-004",
        "buprenorphine_naloxone",
        "8/2 mg",
        D(2026, 10, 22),
        14,
        "14",
        prescriber="Riverside FQHC",
        profile_as_of=D(2026, 10, 22),
        **kayla,
    )
    _fill(
        ds,
        "SYN-004",
        "lamotrigine",
        "100 mg",
        D(2026, 11, 5),
        14,
        "14",
        prescriber="Mercy BH Pavilion",
        profile_as_of=D(2026, 11, 5),
        **kayla,
    )

    rose: dict[str, Any] = {
        "prescriber": "Dr M. Celestin",
        "pharmacy": "Larch Street Pharmacy",
        "profile_phone": "555-0155",
        "profile_as_of": D(2026, 10, 10),
    }
    _fill(ds, "SYN-005", "donepezil", "10 mg", D(2026, 10, 10), 30, "30", **rose)
    _fill(ds, "SYN-005", "amlodipine", "5 mg", D(2026, 10, 10), 30, "30", **rose)


def _adt(ds: Dataset) -> None:
    raymond: dict[str, Any] = {
        "patient_id": "SYN-001-H",
        "assigning_authority": "STBRIGID",
        "last_name": "Tull",
        "first_name": "Raymond",
        "dob": D(1950, 4, 12),
        "sex": "M",
        "phone": "555-0142",
        "address_line1": "12 Larch Street",
        "city": "Columbus",
        "zip": "43204",
        "facility_code": "STBRIGID",
        "facility_name": "St Brigid Regional",
        "patient_class": "I",
        "visit_number": ds.next_id("V"),
    }
    admit = at(D(2026, 11, 3), 14, 20)
    ds.adt.append(
        AdtEvent(
            control_id=ds.next_id("ADT"),
            trigger="A01",
            event_at=admit,
            received_at=at(D(2026, 11, 3), 15, 5),
            admit_at=admit,
            discharge_at=None,
            discharge_disposition=None,
            **raymond,
        )
    )
    ds.adt.append(
        AdtEvent(
            control_id=ds.next_id("ADT"),
            trigger="A03",
            event_at=at(D(2026, 11, 7), 13, 40),
            received_at=at(D(2026, 11, 7), 14, 12),
            admit_at=admit,
            discharge_at=at(D(2026, 11, 7), 13, 40),
            discharge_disposition="01",
            **raymond,
        )
    )

    darnell: dict[str, Any] = {
        "patient_id": "SYN-003",
        "assigning_authority": "EVERGREEN",
        "last_name": "Pruitt",
        "first_name": "Darnell",
        "dob": D(1972, 2, 3),
        "sex": "M",
        "phone": None,
        "address_line1": "401 Elm Ct Apt 3",
        "city": "Dayton",
        "zip": "45405",
        "facility_code": "LAKEVIEW",
        "facility_name": "Lakeview ED",
        "patient_class": "E",
    }
    first_visit = at(D(2026, 10, 28), 21, 5)
    ds.adt.append(
        AdtEvent(
            control_id=ds.next_id("ADT"),
            trigger="A04",
            event_at=first_visit,
            received_at=at(D(2026, 10, 29), 7, 10),
            admit_at=first_visit,
            discharge_at=None,
            discharge_disposition=None,
            visit_number=ds.next_id("V"),
            **darnell,
        )
    )
    second_visit = at(D(2026, 11, 6), 22, 15)
    second_visit_number = ds.next_id("V")
    ds.adt.append(
        AdtEvent(
            control_id=ds.next_id("ADT"),
            trigger="A04",
            event_at=second_visit,
            received_at=at(D(2026, 11, 7), 6, 30),
            admit_at=second_visit,
            discharge_at=None,
            discharge_disposition=None,
            visit_number=second_visit_number,
            **darnell,
        )
    )
    ds.adt.append(
        AdtEvent(
            control_id=ds.next_id("ADT"),
            trigger="A03",
            event_at=at(D(2026, 11, 7), 3, 50),
            received_at=at(D(2026, 11, 7), 6, 31),
            admit_at=second_visit,
            discharge_at=at(D(2026, 11, 7), 3, 50),
            discharge_disposition="01",
            visit_number=second_visit_number,
            **darnell,
        )
    )

    ds.adt.append(
        AdtEvent(
            control_id=ds.next_id("ADT"),
            trigger="A03",
            event_at=at(D(2026, 11, 5), 11, 0),
            received_at=at(D(2026, 11, 5), 12, 10),
            admit_at=None,
            discharge_at=at(D(2026, 11, 5), 11, 0),
            discharge_disposition=None,
            patient_id="SYN-004",
            assigning_authority="EVERGREEN",
            last_name="Morrison",
            first_name="Kayla",
            dob=D(1992, 6, 18),
            sex="F",
            phone=None,
            address_line1="9 Birch Rd",
            city="Columbus",
            zip="43223",
            facility_code="MERCYBH",
            facility_name="Mercy BH Pavilion",
            patient_class="I",
            visit_number=ds.next_id("V"),
        )
    )


def _documents(ds: Dataset) -> None:
    ds.documents.append(
        CcdaDocument(
            doc_id=ds.next_id("DOC", 4),
            doc_type="medication_list",
            patient_id="SYN-001-H",
            last_name="Tull",
            first_name="Raymond",
            dob=D(1950, 4, 12),
            sex="M",
            facility="St Brigid Regional",
            effective_at=at(D(2026, 11, 7), 13, 40),
            received=D(2026, 11, 7),
            medications=(
                Medication("Furosemide", "80 mg", "Furosemide 80 mg daily"),
                Medication(
                    "Sacubitril/valsartan",
                    "24/26 mg",
                    "Sacubitril/valsartan 24/26 mg twice daily (new)",
                ),
                Medication("Metoprolol succinate", "50 mg", "Metoprolol succinate 50 mg daily"),
            ),
        )
    )
    ds.documents.append(
        CcdaDocument(
            doc_id=ds.next_id("DOC", 4),
            doc_type="ed_note",
            patient_id="SYN-003",
            last_name="Pruitt",
            first_name="Darnell",
            dob=D(1972, 2, 3),
            sex="M",
            facility="Lakeview ED",
            effective_at=at(D(2026, 11, 7), 3, 50),
            received=D(2026, 11, 7),
            encounter_start=at(D(2026, 11, 6), 22, 15),
            encounter_end=at(D(2026, 11, 7), 3, 50),
            disposition_code="01",
            disposition="Home or self care",
            problems=((None, "Asthma exacerbation"),),
            notes=("Out of rescue inhaler.",),
        )
    )
    ds.documents.append(
        CcdaDocument(
            doc_id=ds.next_id("DOC", 4),
            doc_type="discharge_summary",
            patient_id="SYN-004",
            last_name="Morrison",
            first_name="Kayla",
            dob=D(1992, 6, 18),
            sex="F",
            facility="Mercy BH Pavilion",
            effective_at=at(D(2026, 11, 5), 11, 0),
            received=D(2026, 11, 5),
            encounter_end=at(D(2026, 11, 5), 11, 0),
            disposition="Shelter",
            discharge_address="Riverside shelter",
            discharge_phone="555-0160",
            problems=((None, "Bipolar I disorder, stabilised"),),
            medications=(Medication("Lamotrigine", "100 mg", "Lamotrigine 100 mg daily"),),
            follow_up=("Behavioral health follow-up within 7 days",),
            notes=(
                "Shelter case desk 555-0160.",
                "Release to coordinate care with Riverside shelter signed 2026-11-05.",
            ),
        )
    )
    # I-04: queried, never received. No document file exists for this request.
    ds.add(
        "hie_requests",
        request_id=ds.next_id("REQ"),
        member_id="SYN-001",
        document_type="discharge_summary",
        facility="St Brigid Regional",
        requested_at=at(D(2026, 11, 7), 15, 2),
        status="not_received",
    )
    ds.mark_absent(
        "SYN-001",
        "documents",
        "St Brigid discharge summary (requested 2026-11-07 15:02, never received)",
        "I-04",
    )


def _clinical_and_coverage(ds: Dataset) -> None:
    def lab(
        member: str, loinc: str, name: str, value: str, unit: str, day: date, source: str
    ) -> None:
        ds.add(
            "lab_results",
            result_id=ds.next_id("LAB"),
            member_id=member,
            loinc=loinc,
            test_name=name,
            result_value=Decimal(value),
            unit=unit,
            collected_date=day,
            source=source,
        )

    lab(
        "SYN-001",
        "33762-6",
        "NT-proBNP",
        "4850",
        "pg/mL",
        D(2026, 11, 4),
        "St Brigid Regional (HIE)",
    )
    lab("SYN-002", "4548-4", "Hemoglobin A1c", "7.6", "%", D(2026, 3, 10), "Evergreen Lab Network")
    lab("SYN-002", "4548-4", "Hemoglobin A1c", "8.9", "%", D(2026, 10, 2), "Evergreen Lab Network")
    lab(
        "SYN-005", "33914-3", "eGFR", "22", "mL/min/1.73m2", D(2026, 9, 20), "Evergreen Lab Network"
    )

    ds.add(
        "auth_requests",
        auth_id=ds.next_id("AUTH"),
        member_id="SYN-005",
        request_type="prior_auth",
        item="Hospital bed (DME)",
        item_code="E0250",
        requested_date=D(2026, 10, 29),
        status="pending",
        decision_due=D(2026, 11, 5),
        expedited=False,
        missing_documents="Face-to-face encounter note",
        requested_by="Dr M. Celestin",
    )
    ds.mark_absent(
        "SYN-001",
        "um",
        "Part D coverage determination for sacubitril/valsartan "
        "(not yet requested; prescriber files)",
        "I-02",
    )

    def gap(
        member: str,
        measure: str,
        description: str,
        anchor: date,
        due: date,
        value: str | None = None,
    ) -> None:
        ds.add(
            "care_gaps",
            gap_id=ds.next_id("GAP"),
            member_id=member,
            measure=measure,
            description=description,
            anchor_date=anchor,
            due_date=due,
            status="open",
            value=Decimal(value) if value else None,
        )

    gap(
        "SYN-001",
        "TRC",
        "Transition contact after inpatient discharge",
        D(2026, 11, 7),
        D(2026, 11, 10),
    )
    gap(
        "SYN-002",
        "PDC",
        "Diabetes medication adherence (PDC), year to date",
        D(2026, 1, 1),
        D(2026, 12, 31),
        "0.76",
    )
    gap("SYN-003", "FMC", "7-day follow-up after ED visit", D(2026, 11, 6), D(2026, 11, 13))
    gap(
        "SYN-004",
        "FUH",
        "7-day follow-up after psychiatric discharge",
        D(2026, 11, 5),
        D(2026, 11, 12),
    )

    ds.add(
        "ltss_aide_hours",
        member_id="SYN-005",
        service="personal_care_aide",
        reassessment_date=D(2026, 10, 1),
        prior_hours_per_week=Decimal("20"),
        authorized_hours_per_week=Decimal("12"),
        effective_date=D(2026, 10, 15),
        notice_date=D(2026, 10, 1),
        appeal_window_days=60,
        as_of=LOAD_DATES["ltss"],
    )
    for day in (D(2026, 10, 9), D(2026, 10, 23)):
        ds.add(
            "nemt_trips",
            trip_id=ds.next_id("TRIP"),
            member_id="SYN-003",
            trip_date=day,
            pickup_address="1450 Wren Way, Dayton",
            destination="Lakeview Pulmonary Clinic",
            status="no_show",
            as_of=D(2026, 10, 31),
        )

    ds.add(
        "screens",
        screen_id=ds.next_id("SCR"),
        member_id="SYN-001",
        instrument="HRA",
        domain="general",
        screen_date=D(2026, 3, 4),
        result="Lives with wife; independent",
    )
    ds.add(
        "screens",
        screen_id=ds.next_id("SCR"),
        member_id="SYN-004",
        instrument="AHC-HRSN",
        domain="housing",
        screen_date=D(2025, 12, 1),
        result="Stable",
        risk_level="low",
    )
    ds.add(
        "screens",
        screen_id=ds.next_id("SCR"),
        member_id="SYN-005",
        instrument="ZBI-4",
        domain="caregiver_strain",
        screen_date=D(2026, 2, 10),
        result="High caregiver burden",
        score=14,
        score_max=16,
        risk_level="high",
    )

    for day, text in (
        (D(2026, 10, 6), "Individual counselling session; reviewed recovery goals and triggers."),
        (
            D(2026, 10, 13),
            "Individual counselling session; discussed housing stress and coping plan.",
        ),
        (D(2026, 10, 20), "Group session attended; continuing medication-assisted treatment plan."),
    ):
        ds.add(
            "new_dawn_notes",
            note_id=ds.next_id("P2N"),
            member_id="SYN-004",
            program_name="New Dawn Recovery",
            service_date=day,
            note_type="counselling",
            counselor="J. Alvarez, LCDC",
            note_text=text,
            redisclosure_prohibited=True,
        )


def _cm_platform(ds: Dataset) -> None:
    def consent(member: str, kind: str, granted: date, **values: object) -> None:
        ds.add(
            "consents",
            consent_id=ds.next_id("CON"),
            member_id=member,
            consent_type=kind,
            granted_date=granted,
            **values,
        )

    consent("SYN-002", "tcpa_sms", D(2025, 6, 1), phone="555-0121", source="enrolment form")
    consent("SYN-005", "tcpa_sms", D(2026, 3, 1), phone="555-0155", source="member services call")
    consent(
        "SYN-004",
        "part2",
        D(2025, 3, 14),
        program="New Dawn Recovery",
        scope="treatment, payment and health care operations",
        recipient=PLAN,
        source="signed consent form",
    )
    consent(
        "SYN-001",
        "personal_representative",
        D(2024, 5, 20),
        representative_name="Joan Tull",
        relationship="wife",
        expires_date=D(2027, 5, 31),
        source="representative form",
    )
    consent(
        "SYN-005",
        "personal_representative",
        D(2025, 9, 30),
        representative_name="Mirlande Joseph",
        relationship="daughter",
        expires_date=D(2026, 9, 30),
        source="representative form",
    )
    consent(
        "SYN-004",
        "third_party_release",
        D(2026, 11, 5),
        recipient="Riverside shelter case desk",
        scope="care coordination",
        source="Mercy BH Pavilion discharge summary",
    )

    def contact(
        member: str,
        phone: str,
        owner: str,
        confidence: str,
        *,
        authorized: bool = True,
        **values: object,
    ) -> None:
        ds.add(
            "contact_points",
            contact_id=ds.next_id("CP"),
            member_id=member,
            phone=phone,
            owner_type=owner,
            confidence=Decimal(confidence),
            authorized=authorized,
            **values,
        )

    contact(
        "SYN-001",
        "555-0142",
        "member",
        "0.82",
        owner_name="Raymond Tull",
        source="pharmacy",
        last_verified=D(2026, 10, 28),
        last_outcome="answered_pharmacy_ivr",
        best_time="10:00-12:00",
    )
    contact(
        "SYN-001",
        "555-0143",
        "representative",
        "0.70",
        owner_name="Joan Tull",
        relationship="wife (authorised representative, manages pills)",
        source="CM note",
        last_verified=D(2026, 6, 1),
        last_outcome="answered",
        best_time="evenings",
    )
    contact(
        "SYN-001",
        "555-0177",
        "member",
        "0.35",
        owner_name="Raymond Tull (landline)",
        source="eligibility",
        last_verified=D(2023, 2, 1),
        last_outcome="no_answer",
    )
    contact(
        "SYN-002",
        "555-0121",
        "member",
        "0.60",
        owner_name="Anh Pham",
        source="eligibility",
        last_verified=D(2025, 6, 1),
        last_outcome="voicemail",
    )
    contact(
        "SYN-003",
        "555-0188",
        "member",
        "0.72",
        owner_name="Darnell Pruitt (likely)",
        source="pharmacy",
        last_verified=D(2026, 10, 28),
        last_outcome="not_tried",
        best_time="18:00-19:00",
    )
    contact(
        "SYN-003",
        "555-0110",
        "member",
        "0.05",
        owner_name="Darnell Pruitt",
        source="eligibility",
        last_outcome="disconnected",
    )
    contact(
        "SYN-004",
        "555-0160",
        "facility",
        "0.75",
        owner_name="Riverside shelter case desk",
        source="discharge summary",
        last_verified=D(2026, 11, 5),
        best_time="09:00-17:00",
    )
    contact(
        "SYN-004",
        "555-0133",
        "member",
        "0.10",
        owner_name="Kayla Morrison",
        source="eligibility",
        last_outcome="disconnected",
    )
    contact(
        "SYN-004",
        "555-0161",
        "family",
        "0.40",
        owner_name="Sister",
        relationship="sister",
        source="old CM note",
        last_verified=D(2025, 5, 1),
        authorized=False,
    )
    contact(
        "SYN-005",
        "555-0155",
        "representative",
        "0.80",
        owner_name="Mirlande Joseph",
        relationship="daughter",
        source="eligibility",
        last_verified=D(2026, 3, 1),
        last_outcome="voicemail",
        best_time="after 19:00",
    )

    def outreach(
        member: str,
        phone: str | None,
        when: tuple[date, int, int],
        outcome: str,
        language: str | None,
        cm: str,
        channel: str = "call",
    ) -> None:
        ds.add(
            "outreach",
            outreach_id=ds.next_id("OUT"),
            member_id=member,
            phone=phone,
            channel=channel,
            attempted_at=at(*when),
            outcome=outcome,
            language_used=language,
            cm_name=cm,
        )

    outreach("SYN-001", "555-0143", (D(2026, 6, 1), 18, 30), "answered", "en", "Maria")
    outreach("SYN-001", "555-0177", (D(2026, 10, 14), 10, 30), "no_answer", "en", "Maria")
    outreach("SYN-001", "555-0177", (D(2026, 10, 21), 14, 0), "no_answer", "en", "Maria")
    for day, hh, mm in (
        (D(2026, 10, 5), 11, 0),
        (D(2026, 10, 12), 15, 20),
        (D(2026, 10, 20), 10, 10),
        (D(2026, 10, 29), 16, 45),
    ):
        outreach("SYN-002", "555-0121", (day, hh, mm), "voicemail", "en", "Outreach team")
    outreach("SYN-003", "555-0110", (D(2026, 10, 20), 13, 15), "disconnected", "en", "Devon")
    outreach("SYN-004", "555-0133", (D(2026, 10, 16), 10, 0), "disconnected", "en", "Alma")
    for day, hh, mm in (
        (D(2026, 10, 21), 11, 15),
        (D(2026, 10, 28), 13, 40),
        (D(2026, 11, 4), 10, 20),
    ):
        outreach("SYN-005", "555-0155", (day, hh, mm), "voicemail", "en", "Maria")

    ds.add("preferences", member_id="SYN-001", preferred_language="en", assigned_cm="Maria")
    ds.add("preferences", member_id="SYN-002", preferred_language="vi", cm_language_required="vi")
    ds.add("preferences", member_id="SYN-003", preferred_language="en", assigned_cm="Devon")
    ds.add("preferences", member_id="SYN-004", preferred_language="en", assigned_cm="Alma")
    ds.add(
        "preferences",
        member_id="SYN-005",
        preferred_language="ht",
        proxy_language="en",
        assigned_cm="Maria",
    )


# annex Sheet 1, column R: the plan's predictive risk score.
HERO_RISK = {
    "SYN-001": "0.88",
    "SYN-002": "0.41",
    "SYN-003": "0.71",
    "SYN-004": "0.74",
    "SYN-005": "0.69",
}
RISK_MODEL = "Evergreen readmission risk v3"


def _risk(ds: Dataset) -> None:
    for member_id, score in HERO_RISK.items():
        ds.add(
            "risk_scores",
            member_id=member_id,
            model=RISK_MODEL,
            score=Decimal(score),
            scored_at=D(2026, 11, 1),
        )


HERO_PLANTS = {
    "I-01": "SYN-001",
    "I-02": "SYN-001",
    "I-03": "SYN-001",
    "I-04": "SYN-001",
    "I-05": "SYN-001",
    "I-06": "SYN-002",
    "I-07": "SYN-002",
    "I-08": "SYN-002",
    "I-09": "SYN-003",
    "I-10": "SYN-003",
    "I-11": "SYN-003",
    "I-12": "SYN-004",
    "I-13": "SYN-004",
    "I-14": "SYN-004",
    "I-15": "SYN-005",
    "I-16": "SYN-005",
    "I-17": "SYN-005",
}


def add_heroes(ds: Dataset) -> None:
    _eligibility(ds)
    _claims(ds)
    _pharmacy(ds)
    _adt(ds)
    _documents(ds)
    _clinical_and_coverage(ds)
    _cm_platform(ds)
    _risk(ds)
    for imperfection_id, member_id in HERO_PLANTS.items():
        ds.plant(imperfection_id, member_id, hero=True)

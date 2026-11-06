"""Builds simplified C-CDA documents (discharge summary, ED note, medication list)."""

from dataclasses import dataclass, field
from datetime import date, datetime
from xml.sax.saxutils import escape, quoteattr

LOINC = "2.16.840.1.113883.6.1"
ICD10 = "2.16.840.1.113883.6.90"

DOC_TYPES = {
    "discharge_summary": ("18842-5", "Discharge Summary"),
    "ed_note": ("34111-5", "Emergency Department Note"),
    "medication_list": ("10160-0", "History of Medication Use"),
}


@dataclass(frozen=True)
class Medication:
    name: str
    dose: str
    sig: str


@dataclass(frozen=True)
class CcdaDocument:
    doc_id: str
    doc_type: str
    patient_id: str
    last_name: str
    first_name: str
    dob: date
    sex: str
    facility: str
    effective_at: datetime
    received: date
    encounter_start: datetime | None = None
    encounter_end: datetime | None = None
    disposition_code: str | None = None
    disposition: str | None = None
    discharge_address: str | None = None
    discharge_phone: str | None = None
    problems: tuple[tuple[str | None, str], ...] = ()
    medications: tuple[Medication, ...] = ()
    follow_up: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def file_name(self) -> str:
        return f"documents/CCDA_{self.received:%Y%m%d}_{self.doc_id}.xml"


def _ts(value: datetime) -> str:
    return value.strftime("%Y%m%d%H%M%S%z")


def _section(code: str, title: str, entries: list[str]) -> list[str]:
    lines = [
        "      <component>",
        "        <section>",
        f'          <code code="{code}" codeSystem="{LOINC}"/>',
        f"          <title>{escape(title)}</title>",
    ]
    lines += [f"          {entry}" for entry in entries]
    lines += ["        </section>", "      </component>"]
    return lines


def build_ccda(doc: CcdaDocument) -> str:
    type_code, type_name = DOC_TYPES[doc.doc_type]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<ClinicalDocument xmlns="urn:hl7-org:v3">',
        '  <typeId root="2.16.840.1.113883.1.3" extension="POCD_HD000040"/>',
        f'  <id root="2.16.840.1.113883.19.5" extension={quoteattr(doc.doc_id)}/>',
        f'  <code code="{type_code}" codeSystem="{LOINC}" displayName="{type_name}"/>',
        f"  <title>{type_name}</title>",
        f'  <effectiveTime value="{_ts(doc.effective_at)}"/>',
        "  <recordTarget>",
        "    <patientRole>",
        f"      <id extension={quoteattr(doc.patient_id)}/>",
        "      <patient>",
        f"        <name><given>{escape(doc.first_name)}</given>"
        f"<family>{escape(doc.last_name)}</family></name>",
        f'        <administrativeGenderCode code="{doc.sex}"/>',
        f'        <birthTime value="{doc.dob:%Y%m%d}"/>',
        "      </patient>",
        "    </patientRole>",
        "  </recordTarget>",
        "  <author>",
        "    <assignedAuthor>",
        f"      <representedOrganization><name>{escape(doc.facility)}</name>"
        "</representedOrganization>",
        "    </assignedAuthor>",
        "  </author>",
    ]
    if doc.encounter_start or doc.encounter_end or doc.disposition:
        lines += ["  <componentOf>", "    <encompassingEncounter>", "      <effectiveTime>"]
        if doc.encounter_start is not None:
            lines.append(f'        <low value="{_ts(doc.encounter_start)}"/>')
        if doc.encounter_end is not None:
            lines.append(f'        <high value="{_ts(doc.encounter_end)}"/>')
        lines.append("      </effectiveTime>")
        if doc.disposition is not None:
            code = f' code="{doc.disposition_code}"' if doc.disposition_code else ""
            lines.append(
                f"      <dischargeDispositionCode{code} displayName={quoteattr(doc.disposition)}/>"
            )
        lines += ["    </encompassingEncounter>", "  </componentOf>"]

    lines += ["  <component>", "    <structuredBody>"]
    if doc.problems:
        entries = []
        for problem_code, text in doc.problems:
            code_xml = (
                f'<code code="{problem_code}" codeSystem="{ICD10}"/>'
                if problem_code
                else '<code nullFlavor="UNK"/>'
            )
            entries.append(
                f"<entry><observation>{code_xml}<text>{escape(text)}</text></observation></entry>"
            )
        lines += _section("11450-4", "Problems", entries)
    if doc.medications:
        med_code = "10160-0" if doc.doc_type == "medication_list" else "10183-2"
        entries = [
            "<entry><substanceAdministration>"
            f"<consumable><manufacturedProduct><manufacturedMaterial><name>{escape(m.name)}</name>"
            "</manufacturedMaterial></manufacturedProduct></consumable>"
            f"<doseQuantity value={quoteattr(m.dose)}/><text>{escape(m.sig)}</text>"
            "</substanceAdministration></entry>"
            for m in doc.medications
        ]
        lines += _section(med_code, "Medications", entries)
    if doc.discharge_address or doc.discharge_phone or doc.notes:
        entries = []
        if doc.discharge_address or doc.discharge_phone:
            role = "<participantRole>"
            if doc.discharge_address:
                role += f"<addr>{escape(doc.discharge_address)}</addr>"
            if doc.discharge_phone:
                role += f'<telecom value="tel:{doc.discharge_phone}"/>'
            role += "</participantRole>"
            entries.append(
                f'<entry><act><participant typeCode="LOC">{role}</participant></act></entry>'
            )
        entries += [f"<entry><act><text>{escape(n)}</text></act></entry>" for n in doc.notes]
        lines += _section("8653-8", "Discharge Instructions", entries)
    if doc.follow_up:
        entries = [f"<entry><act><text>{escape(f)}</text></act></entry>" for f in doc.follow_up]
        lines += _section("18776-5", "Plan of Treatment", entries)
    lines += ["    </structuredBody>", "  </component>", "</ClinicalDocument>"]
    return "\n".join(lines) + "\n"

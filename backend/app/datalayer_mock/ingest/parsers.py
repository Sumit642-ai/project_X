"""Turn raw file bytes into dicts keyed by contract field name.

Parsers never decide what is valid; they only extract. Contracts validate.
"""

import csv
import io
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import hl7

from app.core.clock import PLAN_TZ


class FatalParseError(Exception):
    """The file as a whole cannot be read (not CSV/JSON/HL7/XML, or not the expected shape)."""


@dataclass
class ParsedFile:
    columns: tuple[str, ...] | None  # None for single-record formats (HL7, C-CDA)
    records: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)  # (source_row, message)

    @property
    def total(self) -> int:
        return len(self.records) + len(self.errors)


def parse_csv(content: bytes) -> ParsedFile:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FatalParseError(f"not UTF-8: {exc}") from exc
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise FatalParseError("empty file") from exc
    columns = tuple(h.strip() for h in header)
    parsed = ParsedFile(columns=columns)
    for row_no, values in enumerate(reader, start=2):  # row 1 is the header
        if not values:
            continue
        if len(values) != len(columns):
            parsed.errors.append((row_no, f"{len(values)} fields, expected {len(columns)}"))
            continue
        parsed.records.append((row_no, dict(zip(columns, values, strict=True))))
    return parsed


def parse_json(content: bytes) -> ParsedFile:
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FatalParseError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise FatalParseError("expected a JSON array of records")
    keys: dict[str, None] = {}
    parsed = ParsedFile(columns=())
    for index, record in enumerate(data, start=1):
        if not isinstance(record, dict):
            parsed.errors.append((index, "record is not an object"))
            continue
        keys.update(dict.fromkeys(record))
        parsed.records.append((index, record))
    parsed.columns = tuple(keys)
    return parsed


# --- HL7 v2 -------------------------------------------------------------------------------


def parse_hl7_ts(value: str) -> datetime | None:
    """HL7 TS to aware datetime. Values without an offset are taken as plan-local time."""
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y%m%d%H%M%S%z", "%Y%m%d%H%M%z", "%Y%m%d%H%M%S", "%Y%m%d%H%M"):
        try:
            parsed = datetime.strptime(value, fmt)  # noqa: DTZ007 - tagged with PLAN_TZ below
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=PLAN_TZ)
    raise ValueError(f"unrecognised HL7 timestamp {value!r}")


def _hl7_date(value: str) -> date | None:
    value = value.strip()
    return date(int(value[:4]), int(value[4:6]), int(value[6:8])) if value else None


def parse_adt(raw: str) -> dict[str, Any]:
    text = raw.replace("\r\n", "\r").replace("\n", "\r").strip("\r")
    try:
        message = hl7.parse(text)
    except Exception as exc:  # python-hl7 raises several exception types
        raise FatalParseError(f"not an HL7 v2 message: {exc}") from exc

    def get(path: str) -> str:
        try:
            return str(message[path]).strip()
        except (KeyError, IndexError):
            return ""

    if get("MSH.F9.R1.C1") != "ADT":
        raise FatalParseError(f"not an ADT message (MSH-9 {get('MSH.F9')!r})")
    try:
        return {
            "message_control_id": get("MSH.F10"),
            "trigger_event": get("MSH.F9.R1.C2") or get("EVN.F1"),
            "version": get("MSH.F12"),
            "sending_facility": get("MSH.F4"),
            "message_at": parse_hl7_ts(get("MSH.F7")),
            "event_at": parse_hl7_ts(get("EVN.F6")) or parse_hl7_ts(get("EVN.F2")),
            "patient_id": get("PID.F3.R1.C1"),
            "assigning_authority": get("PID.F3.R1.C4"),
            "last_name": get("PID.F5.R1.C1"),
            "first_name": get("PID.F5.R1.C2"),
            "dob": _hl7_date(get("PID.F7")),
            "sex": get("PID.F8"),
            "phone": get("PID.F13.R1.C1"),
            "address_line1": get("PID.F11.R1.C1"),
            "city": get("PID.F11.R1.C3"),
            "zip": get("PID.F11.R1.C5"),
            "patient_class": get("PV1.F2"),
            "visit_number": get("PV1.F19"),
            "admit_at": parse_hl7_ts(get("PV1.F44")),
            "discharge_at": parse_hl7_ts(get("PV1.F45")),
            "discharge_disposition": get("PV1.F36"),
            "diagnosis_code": get("DG1.F3.R1.C1"),
            "raw_message": raw,
        }
    except ValueError as exc:
        raise FatalParseError(str(exc)) from exc


# --- simplified C-CDA ---------------------------------------------------------------------

NS = {"v3": "urn:hl7-org:v3"}


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    return element.text.strip() or None


def parse_ccda(content: bytes) -> dict[str, Any]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise FatalParseError(f"invalid XML: {exc}") from exc
    if root.tag != "{urn:hl7-org:v3}ClinicalDocument":
        raise FatalParseError(f"not a ClinicalDocument (root {root.tag})")

    def attr(path: str, name: str) -> str | None:
        element = root.find(path, NS)
        return element.get(name) if element is not None else None

    def ts(path: str) -> datetime | None:
        value = attr(path, "value")
        return parse_hl7_ts(value) if value else None

    sections: dict[str, ET.Element] = {}
    for element in root.iterfind(".//v3:section", NS):
        section_code = element.find("v3:code", NS)
        if section_code is not None and section_code.get("code"):
            sections[section_code.get("code", "")] = element

    problems = []
    if (section := sections.get("11450-4")) is not None:
        for obs in section.iterfind(".//v3:observation", NS):
            code = obs.find("v3:code", NS)
            problems.append(
                {
                    "code": code.get("code") if code is not None else None,
                    "text": _text(obs.find("v3:text", NS)),
                }
            )
    medications = []
    for med_code in ("10183-2", "10160-0"):
        if (section := sections.get(med_code)) is not None:
            for sub in section.iterfind(".//v3:substanceAdministration", NS):
                dose = sub.find("v3:doseQuantity", NS)
                medications.append(
                    {
                        "name": _text(sub.find(".//v3:manufacturedMaterial/v3:name", NS)),
                        "dose": dose.get("value") if dose is not None else None,
                        "sig": _text(sub.find("v3:text", NS)),
                    }
                )
    discharge_address = discharge_phone = None
    notes: list[str] = []
    if (section := sections.get("8653-8")) is not None:
        discharge_address = _text(section.find(".//v3:participantRole/v3:addr", NS))
        telecom = section.find(".//v3:participantRole/v3:telecom", NS)
        if telecom is not None:
            discharge_phone = telecom.get("value", "").removeprefix("tel:") or None
        notes = [
            t for t in (_text(e) for e in section.iterfind("v3:entry/v3:act/v3:text", NS)) if t
        ]
    follow_up: list[str] = []
    if (section := sections.get("18776-5")) is not None:
        follow_up = [t for t in (_text(e) for e in section.iterfind(".//v3:text", NS)) if t]

    try:
        return {
            "document_id": attr("v3:id", "extension"),
            "document_type_code": attr("v3:code", "code"),
            "title": _text(root.find("v3:title", NS)),
            "patient_id": attr("v3:recordTarget/v3:patientRole/v3:id", "extension"),
            "last_name": _text(root.find(".//v3:patient/v3:name/v3:family", NS)),
            "first_name": _text(root.find(".//v3:patient/v3:name/v3:given", NS)),
            "dob": _hl7_date(attr(".//v3:patient/v3:birthTime", "value") or ""),
            "sex": attr(".//v3:patient/v3:administrativeGenderCode", "code"),
            "author_organization": _text(
                root.find("v3:author/v3:assignedAuthor/v3:representedOrganization/v3:name", NS)
            ),
            "effective_at": ts("v3:effectiveTime"),
            "encounter_start": ts(".//v3:encompassingEncounter/v3:effectiveTime/v3:low"),
            "encounter_end": ts(".//v3:encompassingEncounter/v3:effectiveTime/v3:high"),
            "discharge_disposition_code": attr(
                ".//v3:encompassingEncounter/v3:dischargeDispositionCode", "code"
            ),
            "discharge_disposition": attr(
                ".//v3:encompassingEncounter/v3:dischargeDispositionCode", "displayName"
            ),
            "discharge_address": discharge_address,
            "discharge_phone": discharge_phone,
            "problems": problems,
            "medications": medications,
            "follow_up": follow_up,
            "notes": notes,
        }
    except ValueError as exc:
        raise FatalParseError(str(exc)) from exc

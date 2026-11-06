"""Builds HL7 v2.5.1 ADT messages. The diagnosis field (DG1-3) is always left blank."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Trigger = Literal["A01", "A03", "A04"]
MESSAGE_STRUCTURE: dict[Trigger, str] = {"A01": "ADT_A01", "A03": "ADT_A03", "A04": "ADT_A01"}


@dataclass(frozen=True)
class AdtEvent:
    control_id: str
    trigger: Trigger
    facility_code: str
    facility_name: str
    event_at: datetime
    received_at: datetime
    patient_id: str
    assigning_authority: str
    last_name: str
    first_name: str
    dob: date
    sex: str
    phone: str | None
    address_line1: str
    city: str
    zip: str
    patient_class: Literal["I", "E"]
    visit_number: str
    admit_at: datetime | None
    discharge_at: datetime | None
    discharge_disposition: str | None

    @property
    def file_name(self) -> str:
        return f"adt/ADT_{self.received_at:%Y%m%dT%H%M%S}_{self.control_id}.hl7"


def hl7_ts(value: datetime) -> str:
    return value.strftime("%Y%m%d%H%M%S%z")


def _segment(name: str, fields: dict[int, str]) -> str:
    width = max(fields)
    return "|".join([name] + [fields.get(i, "") for i in range(1, width + 1)])


def build_adt(event: AdtEvent) -> str:
    sent = hl7_ts(event.received_at)
    msh = (
        f"MSH|^~\\&|{event.facility_code}_ADT|{event.facility_code}|EVERGREEN_CM|EVERGREEN|{sent}"
        f"||ADT^{event.trigger}^{MESSAGE_STRUCTURE[event.trigger]}|{event.control_id}|P|2.5.1"
    )
    evn = _segment("EVN", {1: event.trigger, 2: sent, 6: hl7_ts(event.event_at)})
    pid = _segment(
        "PID",
        {
            1: "1",
            3: f"{event.patient_id}^^^{event.assigning_authority}^MR",
            5: f"{event.last_name}^{event.first_name}",
            7: event.dob.strftime("%Y%m%d"),
            8: event.sex,
            11: f"{event.address_line1}^^{event.city}^OH^{event.zip}",
            13: f"{event.phone}^PRN^PH" if event.phone else "",
        },
    )
    pv1_fields = {
        1: "1",
        2: event.patient_class,
        3: f"^^^{event.facility_code}",
        19: event.visit_number,
    }
    if event.admit_at is not None:
        pv1_fields[44] = hl7_ts(event.admit_at)
    if event.discharge_at is not None:
        pv1_fields[45] = hl7_ts(event.discharge_at)
    if event.discharge_disposition:
        pv1_fields[36] = event.discharge_disposition
    pv1 = _segment("PV1", pv1_fields)
    # DG1-3 (diagnosis code) and DG1-4 (description) deliberately blank: ADT rule minimum.
    dg1 = _segment("DG1", {1: "1", 6: "A"})
    return "\r".join([msh, evn, pid, pv1, dg1]) + "\r"

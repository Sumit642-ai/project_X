from datetime import date
from typing import Literal

from app.datalayer_mock.ingest.contracts.base import (
    AwareDatetime,
    Contract,
    Phone,
    StreamContract,
    SynId,
)


class AdtMessageRecord(Contract):
    """Fields extracted from an HL7 v2 ADT message (A01 admit, A03 discharge, A04 register)."""

    message_control_id: str
    trigger_event: Literal["A01", "A03", "A04"]
    version: str
    sending_facility: str
    message_at: AwareDatetime
    event_at: AwareDatetime | None
    patient_id: SynId
    assigning_authority: str | None
    last_name: str
    first_name: str | None
    dob: date | None
    sex: str | None
    phone: Phone | None
    address_line1: str | None
    city: str | None
    zip: str | None
    patient_class: Literal["I", "E", "O"] | None
    visit_number: str | None
    admit_at: AwareDatetime | None
    discharge_at: AwareDatetime | None
    discharge_disposition: str | None
    # Usually blank in ADT; never inferred.
    diagnosis_code: str | None
    raw_message: str


CONTRACTS = (StreamContract("adt", "adt", "hl7", AdtMessageRecord, "stg_adt", kind="incremental"),)

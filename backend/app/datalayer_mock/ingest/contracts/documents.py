from datetime import date
from typing import Literal

from app.datalayer_mock.ingest.contracts.base import (
    AwareDatetime,
    Contract,
    Phone,
    StreamContract,
    SynId,
)


class HieRequestRow(Contract):
    """HIE document queries and whether the document arrived."""

    request_id: SynId
    member_id: SynId
    document_type: Literal["discharge_summary", "ed_note", "medication_list"]
    facility: str
    requested_at: AwareDatetime
    status: Literal["received", "not_received"]
    received_at: AwareDatetime | None


class CcdaDocumentRecord(Contract):
    """Fields extracted from a simplified C-CDA document."""

    document_id: SynId
    document_type_code: Literal["18842-5", "34111-5", "10160-0"]
    title: str | None
    patient_id: SynId
    last_name: str
    first_name: str
    dob: date | None
    sex: str | None
    author_organization: str | None
    effective_at: AwareDatetime
    encounter_start: AwareDatetime | None
    encounter_end: AwareDatetime | None
    discharge_disposition_code: str | None
    discharge_disposition: str | None
    discharge_address: str | None
    discharge_phone: Phone | None
    problems: list[dict[str, str | None]]
    medications: list[dict[str, str | None]]
    follow_up: list[str]
    notes: list[str]


CONTRACTS = (
    StreamContract("documents", "hie_requests", "csv", HieRequestRow, "stg_hie_requests"),
    StreamContract(
        "documents", "ccda", "ccda", CcdaDocumentRecord, "stg_documents", kind="incremental"
    ),
)

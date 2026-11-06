from datetime import date
from typing import Literal

from app.datalayer_mock.ingest.contracts.base import Contract, PipeList, StreamContract, SynId


class ClaimRow(Contract):
    """837-style medical claim header."""

    claim_id: SynId
    member_id: SynId
    claim_form: Literal["837P", "837I"]
    claim_type: Literal["office", "ed", "inpatient", "bh_outpatient", "home_health"]
    service_date: date
    service_end_date: date | None
    icd10_codes: PipeList
    status: Literal["paid", "pending", "denied", "partially_paid"]
    received_date: date
    paid_date: date | None
    claims_loaded_through: date


CONTRACTS = (
    StreamContract(
        "claims", "claims_837", "csv", ClaimRow, "stg_claims", as_of_field="claims_loaded_through"
    ),
)

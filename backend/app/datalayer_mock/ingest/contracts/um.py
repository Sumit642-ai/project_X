from datetime import date
from typing import Literal

from app.datalayer_mock.ingest.contracts.base import Contract, StreamContract, SynId


class AuthRequestRow(Contract):
    """Prior authorisation and Part D coverage-determination requests."""

    auth_id: SynId
    member_id: SynId
    request_type: Literal["prior_auth", "part_d_coverage_determination"]
    item: str
    item_code: str | None
    requested_date: date
    status: Literal["pending", "approved", "denied", "withdrawn"]
    decision_due: date | None
    decision_date: date | None
    expedited: bool
    missing_documents: str | None
    requested_by: str | None


CONTRACTS = (StreamContract("um", "auth_requests", "csv", AuthRequestRow, "stg_um_auth_requests"),)

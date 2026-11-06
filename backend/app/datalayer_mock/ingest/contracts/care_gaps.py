from datetime import date
from decimal import Decimal
from typing import Literal

from app.datalayer_mock.ingest.contracts.base import Contract, StreamContract, SynId


class CareGapRow(Contract):
    gap_id: SynId
    member_id: SynId
    measure: Literal["TRC", "FMC", "FUH", "PDC"]
    description: str
    anchor_date: date | None
    due_date: date
    status: Literal["open", "met"]
    value: Decimal | None


CONTRACTS = (StreamContract("care_gaps", "care_gaps", "csv", CareGapRow, "stg_care_gaps"),)

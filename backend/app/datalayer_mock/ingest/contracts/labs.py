from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import StringConstraints

from app.datalayer_mock.ingest.contracts.base import Contract, StreamContract, SynId


class LabResultRow(Contract):
    result_id: SynId
    member_id: SynId
    loinc: Annotated[str, StringConstraints(pattern=r"^\d{1,7}-\d$")]
    test_name: str
    result_value: Decimal
    unit: str
    collected_date: date
    source: str | None


CONTRACTS = (StreamContract("labs", "lab_results", "csv", LabResultRow, "stg_labs"),)

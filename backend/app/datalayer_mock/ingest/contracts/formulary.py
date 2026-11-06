from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from app.datalayer_mock.ingest.contracts.base import Contract, Ndc, StreamContract


class FormularyRow(Contract):
    ndc: Ndc
    drug_name: str
    strength: str
    tier: Annotated[int, Field(ge=1, le=6)] | None
    copay_30day: Decimal | None
    formulary_status: Literal["formulary", "non_formulary"]
    pa_required: bool
    step_therapy: bool
    quantity_limit: str | None
    preferred_alternative: str | None


CONTRACTS = (StreamContract("formulary", "formulary", "csv", FormularyRow, "stg_formulary"),)

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import Field

from app.datalayer_mock.ingest.contracts.base import Contract, StreamContract, SynId


class RiskScoreRow(Contract):
    """The plan's predictive risk score per member (0-1)."""

    member_id: SynId
    model: str
    score: Annotated[Decimal, Field(ge=0, le=1)]
    scored_at: date


CONTRACTS = (StreamContract("risk", "risk_scores", "csv", RiskScoreRow, "stg_risk_scores"),)

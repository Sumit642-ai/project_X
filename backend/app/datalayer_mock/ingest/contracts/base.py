from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StringConstraints,
    field_validator,
)


class Contract(BaseModel):
    """Base for every feed row contract.

    Blank strings become None, so missing data stays missing (shown as UNKNOWN later)
    instead of turning into "" or 0. Unknown fields are rejected.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_missing(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


def _split_pipe(value: Any) -> Any:
    if isinstance(value, str):
        return [part.strip() for part in value.split("|") if part.strip()]
    return value


def _require_tz(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must include a UTC offset")
    return value


# Synthetic-data guards from CLAUDE.md: IDs start with SYN-, phones are 555-01xx.
SynId = Annotated[str, StringConstraints(pattern=r"^SYN-[A-Z0-9-]+$")]
Phone = Annotated[str, StringConstraints(pattern=r"^555-01\d\d$")]
PipeList = Annotated[list[str], BeforeValidator(_split_pipe)]
AwareDatetime = Annotated[datetime, AfterValidator(_require_tz)]
Ndc = Annotated[str, StringConstraints(pattern=r"^\d{5}-\d{4}-\d{2}$")]


@dataclass(frozen=True)
class StreamContract:
    feed: str
    stream: str
    fmt: Literal["csv", "json", "hl7", "ccda"]
    model: type[Contract]
    table: str
    # snapshot: each load replaces the previous one; incremental: every good load stays active.
    kind: Literal["snapshot", "incremental"] = "snapshot"
    # Field holding the data as-of date; when None the load date in the file name is used.
    as_of_field: str | None = None

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(self.model.model_fields)

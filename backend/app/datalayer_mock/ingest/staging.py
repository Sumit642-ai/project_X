"""Typed staging tables, generated from the feed contracts so the two cannot drift apart.

Every staging row keeps its lineage (load_id, source_row) so later Facts can cite
source_record_id and loaded_at.
"""

import types
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
)
from sqlalchemy.types import TypeEngine

from app.datalayer_mock.ingest.contracts import CONTRACTS, StreamContract
from app.db.base import Base
from app.db.types import UTCDateTime


def _unwrap(annotation: Any) -> tuple[Any, bool]:
    """Strip Annotated/Optional wrappers; return (base type, nullable)."""
    nullable = False
    while True:
        origin = get_origin(annotation)
        if origin is Annotated:
            annotation = get_args(annotation)[0]
        elif origin in (Union, types.UnionType):
            args = [a for a in get_args(annotation) if a is not type(None)]
            nullable = nullable or len(args) < len(get_args(annotation))
            if len(args) != 1:
                raise TypeError(f"unsupported union in contract: {annotation!r}")
            annotation = args[0]
        else:
            return annotation, nullable


def column_type(annotation: Any) -> tuple[TypeEngine[Any], bool]:
    base, nullable = _unwrap(annotation)
    origin = get_origin(base)
    sa_type: TypeEngine[Any]
    if origin is Literal:
        sa_type = String(40)
    elif origin in (list, dict) or base in (list, dict):
        sa_type = JSON()
    elif base is bool:
        sa_type = Boolean()
    elif base is int:
        sa_type = Integer()
    elif base is Decimal:
        sa_type = Numeric(14, 4)
    elif base is datetime:
        sa_type = UTCDateTime()
    elif base is date:
        sa_type = Date()
    elif base is str:
        sa_type = Text()
    else:
        raise TypeError(f"no column type for {annotation!r}")
    return sa_type, nullable


def build_staging_table(contract: StreamContract) -> Table:
    columns = [
        Column("id", Integer, primary_key=True),
        Column("load_id", ForeignKey("loads.id"), nullable=False, index=True),
        Column("source_row", Integer, nullable=False),
    ]
    for name, field in contract.model.model_fields.items():
        sa_type, nullable = column_type(field.annotation)
        columns.append(Column(name, sa_type, nullable=nullable))
    return Table(contract.table, Base.metadata, *columns)


STAGING_TABLES: dict[str, Table] = {
    stream: build_staging_table(contract) for stream, contract in CONTRACTS.items()
}

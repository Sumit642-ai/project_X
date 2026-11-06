from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class _Lineage:
    """Where a normalised value came from: the staging row that held it."""

    source_stream: Mapped[str] = mapped_column(String(60))
    load_id: Mapped[int] = mapped_column(ForeignKey("loads.id"), index=True)
    source_row: Mapped[int] = mapped_column(Integer)
    member_id: Mapped[str | None] = mapped_column(String(40), index=True)
    raw_code: Mapped[str | None] = mapped_column(String(40))
    raw_display: Mapped[str | None] = mapped_column(Text)
    mapped: Mapped[bool]


class NormDiagnosis(_Lineage, Base):
    __tablename__ = "norm_diagnoses"

    id: Mapped[int] = mapped_column(primary_key=True)
    display: Mapped[str | None] = mapped_column(Text)
    condition_group: Mapped[str | None] = mapped_column(String(40))


class NormMedication(_Lineage, Base):
    __tablename__ = "norm_medications"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_method: Mapped[str | None] = mapped_column(String(10))
    ingredient: Mapped[str | None] = mapped_column(String(80))
    strength: Mapped[str | None] = mapped_column(String(40))
    drug_class: Mapped[str | None] = mapped_column(String(60))


class NormLab(_Lineage, Base):
    __tablename__ = "norm_labs"

    id: Mapped[int] = mapped_column(primary_key=True)
    concept: Mapped[str | None] = mapped_column(String(40))
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    unit: Mapped[str | None] = mapped_column(String(40))


class UnmappedCode(Base):
    """Report of codes the terminology tables could not map, rebuilt on every run."""

    __tablename__ = "unmapped_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_system: Mapped[str] = mapped_column(String(20))  # ICD-10 | NDC | DRUG-NAME | LOINC
    code: Mapped[str | None] = mapped_column(String(40))
    display: Mapped[str | None] = mapped_column(Text)
    source_stream: Mapped[str] = mapped_column(String(60))
    occurrences: Mapped[int] = mapped_column(Integer)
    first_load_id: Mapped[int] = mapped_column(Integer)

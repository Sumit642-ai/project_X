"""Landing -> contract validation -> PASS (staging) or QUARANTINE.

QUARANTINE when: the file has no contract or cannot be read; the columns differ from the
contract (schema change); more than 2% of rows fail the contract; or, for snapshot streams,
the row count is more than 30% below the last good load. Nothing from a quarantined load
reaches staging and the previous good load stays active.
"""

import hashlib
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, Clock, get_clock
from app.core.config import get_settings
from app.datalayer_mock.ingest.contracts import CONTRACTS, FEED_ORDER, Contract, StreamContract
from app.datalayer_mock.ingest.models import PASS, QUARANTINE, RECEIVED, Load, LoadError
from app.datalayer_mock.ingest.parsers import (
    FatalParseError,
    ParsedFile,
    parse_adt,
    parse_ccda,
    parse_csv,
    parse_json,
)
from app.datalayer_mock.ingest.staging import STAGING_TABLES
from app.db.session import get_session_factory

MAX_UNPARSEABLE_SHARE = 0.02
MAX_ROW_COUNT_DROP = 0.30

_SNAPSHOT_NAME = re.compile(r"^(?P<stream>[a-z0-9_]+)_(?P<date>\d{8})\.(csv|json)$")
_ADT_NAME = re.compile(r"^ADT_(?P<date>\d{8})T\d{6}_[A-Za-z0-9-]+\.hl7$")
_CCDA_NAME = re.compile(r"^CCDA_(?P<date>\d{8})_[A-Za-z0-9-]+\.xml$")


def identify(file_name: str) -> tuple[str | None, date | None]:
    """Stream name and load date carried in a raw file name."""
    for pattern, fixed_stream in ((_SNAPSHOT_NAME, None), (_ADT_NAME, "adt"), (_CCDA_NAME, "ccda")):
        if match := pattern.match(file_name):
            stream = fixed_stream or match.group("stream")
            raw_date = match.group("date")
            return stream, date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:]))
    return None, None


@dataclass
class _Validation:
    reason: str | None
    records: list[tuple[int, Contract]]
    errors: list[tuple[int | None, str]]
    total: int


def _parse(contract: StreamContract, content: bytes) -> ParsedFile:
    if contract.fmt == "csv":
        return parse_csv(content)
    if contract.fmt == "json":
        return parse_json(content)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FatalParseError(f"not UTF-8: {exc}") from exc
    record = parse_adt(text) if contract.fmt == "hl7" else parse_ccda(content)
    return ParsedFile(columns=None, records=[(1, record)])


def _short(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'row'}: {err['msg']}" for err in exc.errors()
    )


def _validate(contract: StreamContract | None, feed: str, content: bytes) -> _Validation:
    if contract is None:
        return _Validation("no contract for this file name", [], [], 0)
    if contract.feed != feed:
        return _Validation(f"stream {contract.stream} belongs to feed {contract.feed}", [], [], 0)
    try:
        parsed = _parse(contract, content)
    except FatalParseError as exc:
        return _Validation(f"unparseable file: {exc}", [], [(None, str(exc))], 1)

    if parsed.columns is not None:
        expected = contract.columns
        added = [c for c in parsed.columns if c not in expected]
        missing = [c for c in expected if c not in parsed.columns]
        duplicated = sorted({c for c in parsed.columns if parsed.columns.count(c) > 1})
        if added or missing or duplicated:
            parts = [
                f"{label} {cols}"
                for label, cols in (
                    ("added", added),
                    ("missing", missing),
                    ("duplicated", duplicated),
                )
                if cols
            ]
            return _Validation(f"schema change: {'; '.join(parts)}", [], [], parsed.total)

    records: list[tuple[int, Contract]] = []
    errors: list[tuple[int | None, str]] = list(parsed.errors)
    for row_no, raw in parsed.records:
        try:
            records.append((row_no, contract.model.model_validate(raw)))
        except ValidationError as exc:
            errors.append((row_no, _short(exc)))
    total = parsed.total
    reason = None
    if total and len(errors) / total > MAX_UNPARSEABLE_SHARE:
        reason = (
            f"{len(errors)} of {total} rows unparseable ({len(errors) / total:.1%}), "
            f"limit {MAX_UNPARSEABLE_SHARE:.0%}"
        )
    return _Validation(reason, records, errors, total)


def _active_load(session: Session, stream: str) -> Load | None:
    return session.scalar(
        select(Load)
        .where(Load.stream == stream, Load.status == PASS, Load.is_active.is_(True))
        .order_by(Load.id.desc())
    )


def _row_count_reason(session: Session, contract: StreamContract, total: int) -> str | None:
    last_good = _active_load(session, contract.stream)
    if last_good is None or not last_good.row_count:
        return None
    if total < last_good.row_count * (1 - MAX_ROW_COUNT_DROP):
        drop = 1 - total / last_good.row_count
        return (
            f"row count {total} is {drop:.0%} below last good load {last_good.id} "
            f"({last_good.row_count} rows), limit {MAX_ROW_COUNT_DROP:.0%}"
        )
    return None


def _land(landing_root: Path, feed: str, load_id: int, file_name: str, content: bytes) -> str:
    relative = Path(feed) / f"{load_id:06d}" / file_name
    target = landing_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as handle:  # never overwrite: the landing area is immutable
            handle.write(content)
    except FileExistsError:
        if target.read_bytes() != content:
            raise
    target.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    return relative.as_posix()


def _data_as_of(
    contract: StreamContract, records: list[tuple[int, Contract]], file_date: date | None
) -> date | None:
    if contract.as_of_field:
        values = [getattr(r, contract.as_of_field) for _, r in records]
        return max((v for v in values if v is not None), default=None)
    if contract.fmt == "hl7" and records:
        message_at = getattr(records[0][1], "message_at", None)
        return message_at.astimezone(PLAN_TZ).date() if message_at else None
    return file_date


def _ingest(
    session: Session,
    content: bytes,
    *,
    feed: str,
    stream: str,
    contract: StreamContract | None,
    file_label: str,
    file_name: str,
    file_date: date | None,
    clock: Clock,
    landing_root: Path,
) -> Load:
    checksum = hashlib.sha256(content).hexdigest()
    existing = session.scalar(
        select(Load).where(
            Load.stream == stream, Load.checksum == checksum, Load.status != RECEIVED
        )
    )
    if existing is not None:
        return existing  # same bytes already processed: idempotent re-run

    load = Load(
        feed=feed,
        stream=stream,
        file=file_label,
        checksum=checksum,
        received_at=clock.now(),
        status=RECEIVED,
        rejected_rows=0,
        is_active=False,
    )
    session.add(load)
    session.flush()
    load.landing_path = _land(landing_root, feed, load.id, file_name, content)

    result = _validate(contract, feed, content)
    load.row_count = result.total
    load.rejected_rows = len(result.errors)
    reason = result.reason
    if reason is None and contract is not None and contract.kind == "snapshot":
        reason = _row_count_reason(session, contract, result.total)
    session.add_all(
        LoadError(load_id=load.id, source_row=row, error=msg) for row, msg in result.errors
    )

    if reason is not None or contract is None:
        load.status = QUARANTINE
        load.error = reason
    else:
        rows: list[dict[str, Any]] = [
            {"load_id": load.id, "source_row": row_no, **record.model_dump()}
            for row_no, record in result.records
        ]
        if rows:
            session.execute(insert(STAGING_TABLES[contract.stream]), rows)
        if contract.kind == "snapshot":
            session.execute(
                update(Load)
                .where(Load.stream == contract.stream, Load.is_active.is_(True))
                .values(is_active=False)
            )
        load.status = PASS
        load.is_active = True
        load.data_as_of = _data_as_of(contract, result.records, file_date)
    load.loaded_at = clock.now()
    session.flush()
    return load


def ingest_file(session: Session, path: Path, *, clock: Clock, landing_root: Path) -> Load:
    """Land and validate one raw file. Flushes but does not commit."""
    feed = path.parent.name
    stream, file_date = identify(path.name)
    return _ingest(
        session,
        path.read_bytes(),
        feed=feed,
        stream=stream or path.stem,
        contract=CONTRACTS.get(stream) if stream else None,
        file_label=f"{feed}/{path.name}",
        file_name=path.name,
        file_date=file_date,
        clock=clock,
        landing_root=landing_root,
    )


def raw_files_in_order(raw_root: Path) -> list[Path]:
    """Every raw file, feeds in FEED_ORDER (unknown feeds last), files by load date then name."""
    feed_dirs = sorted(
        (p for p in raw_root.iterdir() if p.is_dir()),
        key=lambda p: (
            FEED_ORDER.index(p.name) if p.name in FEED_ORDER else len(FEED_ORDER),
            p.name,
        ),
    )

    def file_key(path: Path) -> tuple[date, str]:
        return identify(path.name)[1] or date.min, path.name

    return [
        f for d in feed_dirs for f in sorted((p for p in d.iterdir() if p.is_file()), key=file_key)
    ]


def ingest_all(session: Session, raw_root: Path, *, clock: Clock, landing_root: Path) -> list[Load]:
    """Ingest everything under raw_root in load order, committing after each file."""
    loads = []
    for path in raw_files_in_order(raw_root):
        loads.append(ingest_file(session, path, clock=clock, landing_root=landing_root))
        session.commit()
    return loads


def _control_id(raw: str) -> str:
    first = raw.replace("\n", "\r").split("\r", 1)[0].split("|")
    control = first[9] if len(first) > 9 else ""
    return re.sub(r"[^A-Za-z0-9-]", "", control) or "unknown"


def ingest_adt_message(
    raw: str,
    *,
    session: Session | None = None,
    clock: Clock | None = None,
    landing_root: Path | None = None,
) -> Load:
    """Real-time path: land and stage one HL7 ADT message. Commits when it owns the session."""
    owns_session = session is None
    active = session if session is not None else get_session_factory()()
    clock = clock or get_clock()
    try:
        control = _control_id(raw)
        load = _ingest(
            active,
            raw.encode("utf-8"),
            feed="adt",
            stream="adt",
            contract=CONTRACTS["adt"],
            file_label=f"realtime:{control}",
            file_name=f"{control}.hl7",
            file_date=None,
            clock=clock,
            landing_root=landing_root or get_settings().landing_dir,
        )
        if owns_session:
            active.commit()
        return load
    finally:
        if owns_session:
            active.close()


def summarise(loads: Iterable[Load]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for load in loads:
        counts[load.status] = counts.get(load.status, 0) + 1
    return counts

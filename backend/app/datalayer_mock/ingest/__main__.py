"""`make ingest`: load everything in data/raw in feed order."""

import argparse
import sys
from pathlib import Path

from app.core.clock import get_clock
from app.core.config import get_settings
from app.datalayer_mock.ingest.freshness import feed_status
from app.datalayer_mock.ingest.models import QUARANTINE
from app.datalayer_mock.ingest.pipeline import ingest_all, summarise
from app.db.session import get_session_factory


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="python -m app.datalayer_mock.ingest")
    parser.add_argument("--raw", type=Path, default=settings.raw_dir)
    parser.add_argument("--landing", type=Path, default=settings.landing_dir)
    args = parser.parse_args(argv)

    if not args.raw.is_dir():
        print(f"No raw directory at {args.raw}; run make synth first.", file=sys.stderr)
        return 1
    clock = get_clock()
    with get_session_factory()() as session:
        loads = ingest_all(session, args.raw, clock=clock, landing_root=args.landing)
        for load in loads:
            note = f"  {load.error}" if load.error else ""
            print(f"{load.status:<10} {load.row_count or 0:>6}  {load.file}{note}")
        print(f"\n{len(loads)} files: {summarise(loads)}")
        print("\nfeed            last good load (UTC)         age h   data as of")
        for status in feed_status(session, clock):
            last = status.last_good_load_at.isoformat() if status.last_good_load_at else "UNKNOWN"
            age = f"{status.age_hours:.1f}" if status.age_hours is not None else "UNKNOWN"
            as_of = status.data_as_of.isoformat() if status.data_as_of else "UNKNOWN"
            print(f"{status.feed:<15} {last:<28} {age:>7}   {as_of}")
    return 1 if any(load.status == QUARANTINE for load in loads) else 0


if __name__ == "__main__":
    raise SystemExit(main())

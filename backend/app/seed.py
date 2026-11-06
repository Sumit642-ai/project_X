"""`make seed`: build the demo database from data/raw (generating it first if missing).

ingest -> identity matching -> Facts -> users and assignments -> signals and scores.
"""

import sys

from app.core.clock import get_clock
from app.core.config import get_settings
from app.datalayer_mock.identity import run_matching
from app.datalayer_mock.ingest import ingest_all
from app.db.session import get_session_factory
from app.facts import refresh_facts
from app.scoring.service import score_members
from app.synth.generate import generate
from app.workbench.seed import seed_workbench


def main() -> int:
    settings = get_settings()
    clock = get_clock()
    if not (settings.raw_dir / "MANIFEST.json").exists():
        print(f"No raw data in {settings.raw_dir}; generating it.")
        generate(settings.raw_dir)
    with get_session_factory()() as session:
        loads = ingest_all(
            session, settings.raw_dir, clock=clock, landing_root=settings.landing_dir
        )
        matching = run_matching(session, clock)
        facts = refresh_facts(session, clock)
        seed_workbench(session, clock)
        scores = score_members(session, clock)
        session.commit()
    print(
        f"Loaded {len(loads)} files; links {matching.created}; {facts.created} new facts; "
        f"{len(scores)} members scored."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

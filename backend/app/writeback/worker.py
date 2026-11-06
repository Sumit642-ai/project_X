"""`python -m app.writeback.worker`: retry pending CM write-backs every 30 seconds."""

import time

from app.core.clock import get_clock
from app.db.session import get_session_factory
from app.writeback.client import get_cm_client
from app.writeback.service import sync_due

INTERVAL_SECONDS = 30


def run_once() -> None:
    with get_session_factory()() as session:
        summary = sync_due(session, get_clock(), get_cm_client())
        session.commit()
    if summary.synced or summary.retrying or summary.alerted or summary.conflicts:
        print(
            f"synced {summary.synced} retrying {summary.retrying} "
            f"conflicts {summary.conflicts} alerted {summary.alerted}",
            flush=True,
        )


def main() -> None:
    while True:
        run_once()
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

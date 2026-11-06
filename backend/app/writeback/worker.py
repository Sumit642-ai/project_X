"""`python -m app.writeback.worker`: retry pending CM write-backs every 30 seconds."""

import logging
import time

from app.core.clock import get_clock
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.writeback.client import get_cm_client
from app.writeback.service import SyncSummary, sync_due

INTERVAL_SECONDS = 30
log = logging.getLogger("casecompass.writeback")


def run_once() -> SyncSummary:
    with get_session_factory()() as session:
        summary = sync_due(session, get_clock(), get_cm_client())
        session.commit()
    if summary.synced or summary.retrying or summary.alerted or summary.conflicts:
        log.info(
            "write-back retry run",
            extra={
                "synced": len(summary.synced),
                "retrying": len(summary.retrying),
                "conflicts": len(summary.conflicts),
                "alerted": len(summary.alerted),
            },
        )
    return summary


def main() -> None:
    configure_logging()
    while True:
        run_once()
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app import observability
from app.api.deps import ClockDep, DbSession, require_role
from app.workbench.models import User

router = APIRouter(tags=["observability"])
Supervisor = Annotated[User, Depends(require_role("supervisor"))]


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(session: DbSession, clock: ClockDep) -> str:
    """Prometheus text format for the scraper. Counts and ages only: no member data."""
    return observability.prometheus(observability.collect(session, clock))


@router.get("/admin/metrics")
def admin_metrics(session: DbSession, clock: ClockDep, user: Supervisor) -> dict[str, Any]:
    """The same metrics as JSON, for the supervisor's metrics page."""
    return observability.collect(session, clock)

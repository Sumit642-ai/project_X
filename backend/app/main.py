import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.ai_draft import router as ai_draft_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.conflicts import router as conflicts_router
from app.api.demo import router as demo_router
from app.api.documents import router as documents_router
from app.api.encounters import router as encounters_router
from app.api.health import router as health_router
from app.api.members import router as members_router
from app.api.metrics import router as metrics_router
from app.api.queue import router as queue_router
from app.core.config import get_settings
from app.core.logging import configure_logging, register_names
from app.datalayer_mock.identity.models import Member
from app.facts.models import ContactPoint
from app.db.session import get_db
from app.workbench.access import AccessDeniedError
from app.workbench.actions import ActionError


request_log = logging.getLogger("casecompass.request")
log = logging.getLogger("casecompass")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load member names so log masking can remove them from any log line."""
    provider = app.dependency_overrides.get(get_db, get_db)
    try:
        sessions = provider()
        session = next(sessions)
        try:
            people = [
                n
                for row in session.execute(select(Member.first_name, Member.last_name))
                for n in row
            ]
            # Representatives and family (people, not organisations such as a shelter desk).
            people += [
                part
                for (full,) in session.execute(
                    select(ContactPoint.owner_name).where(
                        ContactPoint.owner.in_(("self", "representative"))
                    )
                )
                for part in (full or "").split()
            ]
            register_names(people)
        finally:
            sessions.close()
    except Exception as exc:  # no database yet (e.g. before migrations): phones still masked
        log.warning("name masking unavailable: %s", type(exc).__name__)
    yield


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="CaseCompass API",
        version="0.1.0",
        description="Case-management workbench. Synthetic data only.",
        lifespan=lifespan,
    )
    # Only the frontend's origin may call the API from a browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def log_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """One structured line per request: route template, never the raw path or query."""
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        params = request.scope.get("path_params") or {}
        request_log.info(
            "request",
            extra={
                "method": request.method,
                "route": getattr(route, "path", "unmatched"),
                "member_id": params.get("member_id"),
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    for router in (
        health_router,
        auth_router,
        queue_router,
        encounters_router,
        audit_router,
        members_router,
        conflicts_router,
        documents_router,
        ai_draft_router,
        demo_router,
        metrics_router,
    ):
        app.include_router(router)

    @app.exception_handler(AccessDeniedError)
    async def access_denied(request: Request, exc: AccessDeniedError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(ActionError)
    async def action_error(request: Request, exc: ActionError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": {"reason": exc.reason}})

    return app


app = create_app()

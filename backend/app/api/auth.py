from fastapi import APIRouter, HTTPException, Request, status

from app.api import schemas
from app.api.deps import ClockDep, CurrentUser, DbSession, issue_token
from app.api.ratelimit import SlidingWindowLimiter, client_key
from app.core.config import get_settings
from app.workbench.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(
    body: schemas.LoginRequest, request: Request, session: DbSession, clock: ClockDep
) -> schemas.TokenOut:
    """Fake login for seeded demo users only. Disabled outside local/test/demo.
    Rate limited per client address (LOGIN_RATE_LIMIT per LOGIN_RATE_WINDOW_SECONDS)."""
    settings = get_settings()
    if settings.app_env not in ("local", "test", "demo"):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    limiter: SlidingWindowLimiter | None = getattr(request.app.state, "login_limiter", None)
    if limiter is None:
        limiter = SlidingWindowLimiter(
            settings.login_rate_limit, settings.login_rate_window_seconds
        )
        request.app.state.login_limiter = limiter
    limiter.check(client_key(request))
    user = session.get(User, body.username)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown demo user")
    return schemas.TokenOut(
        access_token=issue_token(user, clock), user=schemas.UserOut.model_validate(user)
    )


@router.get("/me")
def me(user: CurrentUser) -> schemas.UserOut:
    return schemas.UserOut.model_validate(user)

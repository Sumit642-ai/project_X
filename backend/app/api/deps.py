"""Demo-grade auth: seeded users, HS256 JWT, expiry checked against the injected Clock."""

from collections.abc import Callable
from datetime import timedelta
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.clock import Clock, get_clock
from app.core.config import get_settings
from app.db.session import get_db
from app.workbench.models import User

ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]
ClockDep = Annotated[Clock, Depends(get_clock)]


def issue_token(user: User, clock: Clock) -> str:
    settings = get_settings()
    now = clock.now()
    claims: dict[str, Any] = {
        "sub": user.username,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_ttl_minutes)).timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def current_user(
    session: DbSession,
    clock: ClockDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "sign in first", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        # Time claims are checked against the Clock service, not the wall clock.
        claims = jwt.decode(
            credentials.credentials,
            get_settings().jwt_secret,
            algorithms=[ALGORITHM],
            options={"verify_exp": False, "verify_iat": False, "require": ["sub", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc
    now = int(clock.now().timestamp())
    if int(claims["exp"]) < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    if int(claims["iat"]) > now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token issued in the future")
    user = session.get(User, claims.get("sub"))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(*roles: str) -> Callable[[User], User]:
    def check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"role {user.role} may not use this endpoint"
            )
        return user

    return check

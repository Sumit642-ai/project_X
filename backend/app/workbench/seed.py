"""Seeded demo users and initial assignments (from the CM platform's assigned_cm)."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.facts.models import Fact
from app.workbench.models import Assignment, User


@dataclass(frozen=True)
class SeedUser:
    username: str
    name: str
    role: str
    credential: str | None
    program: str | None
    licensed_states: tuple[str, ...]
    languages: tuple[str, ...]
    capacity_target: int | None
    pod: str | None = None


SEED_USERS = (
    SeedUser("maria", "Maria", "cm", "RN", "complex_cm", ("OH",), ("en",), 45, "OH-1"),
    SeedUser("devon", "Devon", "cm", "RN", "transitions", ("OH",), ("en",), 60, "OH-1"),
    SeedUser("alma", "Alma", "cm", "LCSW", "behavioral_health", ("OH",), ("en", "es"), 35, "OH-1"),
    SeedUser("priya", "Priya", "cm", "RN", "complex_cm", ("TX",), ("en", "vi"), 45, "TX-1"),
    SeedUser("janet", "Janet", "supervisor", "RN", None, ("OH",), ("en",), None, "OH-1"),
    SeedUser("sam", "Sam", "call_agent", None, None, (), ("en",), None),
)

# How each seeded user is offered on the demo sign-in page (demo mode only).
SIGN_IN_LABELS = {
    "maria": "Maria · RN, complex case management",
    "devon": "Devon · RN, transitions",
    "alma": "Alma · LCSW, behavioral health",
    "priya": "Priya · RN (Texas licence)",
    "janet": "Janet · supervisor",
    "sam": "Sam · call agent",
}


def seed_workbench(session: Session, clock: Clock) -> None:
    """Create users, then give every member without an active assignment the CM the CM
    platform names, when that CM is a seeded user. Others stay unassigned."""
    users = {u.username: u for u in session.scalars(select(User))}
    for seed in SEED_USERS:
        user = users.get(seed.username) or User(username=seed.username)
        user.name, user.role, user.credential, user.program = (
            seed.name,
            seed.role,
            seed.credential,
            seed.program,
        )
        user.licensed_states, user.languages = list(seed.licensed_states), list(seed.languages)
        user.capacity_target, user.pod = seed.capacity_target, seed.pod
        session.add(user)
        users[seed.username] = user
    session.flush()

    active = set(session.scalars(select(Assignment.member_id).where(Assignment.status == "active")))
    preferences = session.scalars(
        select(Fact)
        .where(Fact.type == "preference", Fact.superseded_by.is_(None))
        .order_by(Fact.id)
    )
    for fact in preferences:
        name = (fact.value.get("assigned_cm") or "").lower()
        if fact.member_id in active or name not in users or users[name].role != "cm":
            continue
        session.add(
            Assignment(
                member_id=fact.member_id,
                cm_username=name,
                status="active",
                assigned_by="system:cm_platform",
                assigned_at=clock.now(),
                reason="assigned in CM platform",
            )
        )
        active.add(fact.member_id)
    session.flush()

"""Who may see or act on which member."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.workbench.models import Assignment, User


class AccessDeniedError(PermissionError):
    pass


def active_assignment(session: Session, member_id: str) -> Assignment | None:
    return session.scalars(
        select(Assignment).where(Assignment.member_id == member_id, Assignment.status == "active")
    ).first()


def assigned_members(session: Session, username: str) -> set[str]:
    return set(
        session.scalars(
            select(Assignment.member_id).where(
                Assignment.cm_username == username, Assignment.status == "active"
            )
        )
    )


def unassigned_members(session: Session, member_ids: set[str]) -> set[str]:
    taken = set(session.scalars(select(Assignment.member_id).where(Assignment.status == "active")))
    return member_ids - taken


def check_member_access(
    session: Session, user: User, member_id: str, *, supervisor_ok: bool = True
) -> None:
    """CMs act only on their own members; supervisors on anyone (unless excluded)."""
    if user.role == "supervisor" and supervisor_ok:
        return
    if user.role == "cm":
        assignment = active_assignment(session, member_id)
        if assignment is not None and assignment.cm_username == user.username:
            return
        raise AccessDeniedError(f"{member_id} is not assigned to {user.username}")
    raise AccessDeniedError(f"role {user.role} cannot act on member records")

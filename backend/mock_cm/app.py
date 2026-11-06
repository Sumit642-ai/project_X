"""Mock CM platform (the system of record CaseCompass writes back to). Demo only.

Its own SQLite database stores notes, assessment answers and tasks per member. Every member
record has a version; writes are conditional (If-Match) and idempotent (Idempotency-Key).
It can be told to misbehave: MOCK_CM_MODE=down|slow|conflict, or POST /admin/mode.

Run: uvicorn mock_cm.app:create_app --factory --port 8200
"""

import os
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import JSON, ForeignKey, Integer, String, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

MODES = ("up", "down", "slow", "conflict")


class Base(DeclarativeBase):
    pass


class MemberRecord(Base):
    __tablename__ = "member_records"

    member_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("member_records.member_id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    version: Mapped[int] = mapped_column(Integer)
    note: Mapped[dict[str, Any]] = mapped_column(JSON)
    assessment: Mapped[dict[str, Any]] = mapped_column(JSON)
    tasks: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    received_at: Mapped[str] = mapped_column(String(40))


class WriteBody(BaseModel):
    note: dict[str, Any]
    assessment: dict[str, Any]
    tasks: list[dict[str, Any]]


class ModeBody(BaseModel):
    mode: str
    slow_seconds: float = 3.0


def create_app(database_url: str | None = None, mode: str | None = None) -> FastAPI:
    url = database_url or os.environ.get("MOCK_CM_DATABASE_URL", "sqlite:///./mock_cm.db")
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    state: dict[str, Any] = {
        "mode": mode or os.environ.get("MOCK_CM_MODE", "up"),
        "slow_seconds": 3.0,
    }
    app = FastAPI(title="Mock CM platform", description="Demo system of record. Synthetic only.")

    def behave() -> None:
        if state["mode"] == "down":
            raise HTTPException(503, "mock CM platform is down")
        if state["mode"] == "slow":
            time.sleep(state["slow_seconds"])

    def record(session: Session, member_id: str) -> MemberRecord:
        found = session.get(MemberRecord, member_id)
        if found is None:
            found = MemberRecord(member_id=member_id, version=1)
            session.add(found)
            session.flush()
        return found

    def view(session: Session, member: MemberRecord) -> dict[str, Any]:
        entries = list(
            session.scalars(
                select(Entry).where(Entry.member_id == member.member_id).order_by(Entry.id)
            )
        )
        assessment: dict[str, Any] = {}
        for entry in entries:
            assessment.update(entry.assessment)
        return {
            "member_id": member.member_id,
            "version": member.version,
            "notes": [e.note for e in entries],
            "assessment": assessment,
            "tasks": [t for e in entries for t in e.tasks],
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok" if state["mode"] != "down" else "down", "mode": state["mode"]}

    @app.get("/members/{member_id}/record")
    def get_record(member_id: str) -> dict[str, Any]:
        behave()
        with sessions() as session:
            member = record(session, member_id)
            session.commit()
            return view(session, member)

    @app.put("/members/{member_id}/entries/{idempotency_key}")
    def write(
        member_id: str,
        idempotency_key: str,
        body: WriteBody,
        response: Response,
        if_match: str | None = Header(default=None),
    ) -> Any:
        behave()
        with sessions() as session:
            member = record(session, member_id)
            existing = session.scalars(
                select(Entry).where(Entry.idempotency_key == idempotency_key)
            ).first()
            if existing is not None:  # replay of a write we already applied
                response.status_code = 200
                session.commit()
                return {"status": "duplicate", "version": member.version, "entry_id": existing.id}
            if state["mode"] == "conflict":
                member.version += 1  # someone else edited the record meanwhile
            if if_match is None or int(if_match) != member.version:
                session.commit()
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": "record changed since it was opened",
                        "current": view(session, member),
                    },
                )
            member.version += 1
            entry = Entry(
                member_id=member_id,
                idempotency_key=idempotency_key,
                version=member.version,
                note=body.note,
                assessment=body.assessment,
                tasks=body.tasks,
                received_at=datetime.now(UTC).isoformat(),
            )
            session.add(entry)
            session.commit()
            response.status_code = 201
            return {"status": "created", "version": member.version, "entry_id": entry.id}

    @app.post("/admin/mode")
    def set_mode(body: ModeBody) -> dict[str, Any]:
        if body.mode not in MODES:
            raise HTTPException(422, f"mode must be one of {', '.join(MODES)}")
        state["mode"], state["slow_seconds"] = body.mode, body.slow_seconds
        return {"mode": state["mode"]}

    @app.post("/admin/reset")
    def reset() -> dict[str, Any]:
        """Demo reset: no entries, every record back to version 1, platform up."""
        with sessions() as session:
            session.execute(delete(Entry))
            session.execute(delete(MemberRecord))
            session.commit()
        state["mode"] = "up"
        return {"mode": "up", "entries": 0}

    @app.post("/admin/touch/{member_id}")
    def touch(member_id: str) -> dict[str, Any]:
        """Simulate another user editing the member's record (bumps the version)."""
        with sessions() as session:
            member = record(session, member_id)
            member.version += 1
            session.commit()
            return {"member_id": member_id, "version": member.version}

    @app.get("/admin/entries")
    def entries(member_id: str | None = None) -> list[dict[str, Any]]:
        with sessions() as session:
            query = select(Entry).order_by(Entry.id)
            if member_id:
                query = query.where(Entry.member_id == member_id)
            return [
                {
                    "id": e.id,
                    "member_id": e.member_id,
                    "key": e.idempotency_key,
                    "version": e.version,
                    "note": e.note,
                }
                for e in session.scalars(query)
            ]

    return app

"""ai draft: logs, drafts, guardrail metrics, user pods

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-06 21:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db.types

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOG_STATUSES = (
    "ok", "timeout", "connection", "rate_limited", "refusal", "truncated", "invalid_output",
    "not_configured", "api_error", "error",
)

AI_LOGS_PG = """
CREATE FUNCTION ai_logs_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'ai_logs are append-only';
END $$;
CREATE TRIGGER ai_logs_append_only BEFORE UPDATE OR DELETE ON ai_logs
    FOR EACH ROW EXECUTE FUNCTION ai_logs_append_only();
REVOKE UPDATE, DELETE, TRUNCATE ON ai_logs FROM PUBLIC;
"""
AI_LOGS_SQLITE = (
    "CREATE TRIGGER ai_logs_no_update BEFORE UPDATE ON ai_logs "
    "BEGIN SELECT RAISE(ABORT, 'ai_logs are append-only'); END",
    "CREATE TRIGGER ai_logs_no_delete BEFORE DELETE ON ai_logs "
    "BEGIN SELECT RAISE(ABORT, 'ai_logs are append-only'); END",
)


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("pod", sa.String(length=20), nullable=True))

    op.create_table(
        "ai_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("encounter_id", sa.Integer(), nullable=False),
        sa.Column("created_at", app.db.types.UTCDateTime(), nullable=False),
        sa.Column("actor", sa.String(length=40), nullable=False),
        sa.Column("feature", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=60), nullable=False),
        sa.Column("prompt_version", sa.String(length=30), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=80), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in LOG_STATUSES)})", name="ck_ai_logs_status"
        ),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_logs_encounter_id", "ai_logs", ["encounter_id"])

    op.create_table(
        "ai_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("encounter_id", sa.Integer(), nullable=False),
        sa.Column("ai_log_id", sa.Integer(), nullable=False),
        sa.Column("created_at", app.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=40), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("unsupported_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("flagged_medications", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["ai_log_id"], ["ai_logs.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.username"]),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_drafts_encounter_id", "ai_drafts", ["encounter_id"])

    op.create_table(
        "ai_guardrail_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("encounter_id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("pod", sa.String(length=20), nullable=True),
        sa.Column("unsupported_count", sa.Integer(), nullable=False),
        sa.Column("edit_distance", sa.Float(), nullable=False),
        sa.Column("major_edit", sa.Boolean(), nullable=False),
        sa.Column("seconds_to_save", sa.Integer(), nullable=False),
        sa.Column("saved_at", app.db.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["ai_drafts.id"]),
        sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("encounter_id"),
    )
    op.create_index("ix_ai_guardrail_metrics_pod", "ai_guardrail_metrics", ["pod"])

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(AI_LOGS_PG)
    elif dialect == "sqlite":
        for statement in AI_LOGS_SQLITE:
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS ai_logs_append_only ON ai_logs")
        op.execute("DROP FUNCTION IF EXISTS ai_logs_append_only()")
    op.drop_index("ix_ai_guardrail_metrics_pod", table_name="ai_guardrail_metrics")
    op.drop_table("ai_guardrail_metrics")
    op.drop_index("ix_ai_drafts_encounter_id", table_name="ai_drafts")
    op.drop_table("ai_drafts")
    op.drop_index("ix_ai_logs_encounter_id", table_name="ai_logs")
    op.drop_table("ai_logs")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("pod")

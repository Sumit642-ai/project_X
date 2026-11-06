"""task resolution by data

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db.types

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("resolved_at", app.db.types.UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("resolution", sa.Text(), nullable=True))
        batch.add_column(sa.Column("resolution_fact_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("resolution_fact_ids")
        batch.drop_column("resolution")
        batch.drop_column("resolved_at")

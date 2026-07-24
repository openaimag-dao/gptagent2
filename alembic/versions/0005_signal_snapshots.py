"""signal snapshots table

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signal_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bull_score", sa.Integer(), nullable=False),
        sa.Column("bear_score", sa.Integer(), nullable=False),
        sa.Column("net_score", sa.Integer(), nullable=False),
        sa.Column("confidence_pct", sa.Integer(), nullable=False),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_signal_snapshots_computed_at", "signal_snapshots", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_signal_snapshots_computed_at", table_name="signal_snapshots")
    op.drop_table("signal_snapshots")

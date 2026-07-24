"""correlations table

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-24

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "correlations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol_a", sa.String(length=20), nullable=False),
        sa.Column("symbol_b", sa.String(length=20), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("correlation", sa.Numeric(6, 4), nullable=False),
        sa.Column("data_points", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_correlations_symbol_a", "correlations", ["symbol_a"])
    op.create_index("ix_correlations_symbol_b", "correlations", ["symbol_b"])
    op.create_index("ix_correlations_calculated_at", "correlations", ["calculated_at"])


def downgrade() -> None:
    op.drop_index("ix_correlations_calculated_at", table_name="correlations")
    op.drop_index("ix_correlations_symbol_b", table_name="correlations")
    op.drop_index("ix_correlations_symbol_a", table_name="correlations")
    op.drop_table("correlations")

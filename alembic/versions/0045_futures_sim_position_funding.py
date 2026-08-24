"""Futures Simulator: funding_paid column on futures_sim_positions

Revision ID: 0045
Revises: 0044
Create Date: 2026-08-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "futures_sim_positions",
        sa.Column("funding_paid", sa.Numeric(24, 8), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("futures_sim_positions", "funding_paid")

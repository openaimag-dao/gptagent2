"""Volatility-conditioning columns on probability_snapshots

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "probability_snapshots",
        sa.Column("volatility_conditioned", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "probability_snapshots",
        sa.Column("reference_volatility", sa.Numeric(10, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("probability_snapshots", "reference_volatility")
    op.drop_column("probability_snapshots", "volatility_conditioned")

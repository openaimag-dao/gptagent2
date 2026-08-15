"""V9 Increment 1: regime_confidence_pct on market_regime_snapshots +
forward-return quantiles/regime-conditioning columns on probability_snapshots

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "market_regime_snapshots",
        sa.Column("confidence_pct", sa.Integer(), nullable=True),
    )
    op.add_column(
        "probability_snapshots",
        sa.Column("p10_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "probability_snapshots",
        sa.Column("p25_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "probability_snapshots",
        sa.Column("p50_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "probability_snapshots",
        sa.Column("p75_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "probability_snapshots",
        sa.Column("p90_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "probability_snapshots",
        sa.Column("regime_conditioned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "probability_snapshots",
        sa.Column("reference_regime", sa.String(30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("probability_snapshots", "reference_regime")
    op.drop_column("probability_snapshots", "regime_conditioned")
    op.drop_column("probability_snapshots", "p90_pct")
    op.drop_column("probability_snapshots", "p75_pct")
    op.drop_column("probability_snapshots", "p50_pct")
    op.drop_column("probability_snapshots", "p25_pct")
    op.drop_column("probability_snapshots", "p10_pct")
    op.drop_column("market_regime_snapshots", "confidence_pct")

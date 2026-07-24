"""market regime snapshots table

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-24

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REGIME_VALUES = (
    "risk_on",
    "risk_off",
    "neutral",
    "liquidity_expansion",
    "liquidity_contraction",
    "flight_to_safety",
)


def upgrade() -> None:
    op.create_table(
        "market_regime_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("regime", sa.Enum(*_REGIME_VALUES, name="market_regime_type"), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_market_regime_snapshots_computed_at", "market_regime_snapshots", ["computed_at"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_regime_snapshots_computed_at", table_name="market_regime_snapshots"
    )
    op.drop_table("market_regime_snapshots")
    sa.Enum(name="market_regime_type").drop(op.get_bind(), checkfirst=True)

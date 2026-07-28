"""v4.0 Phase 1: market_snapshots table for the Market Replay Engine

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("regime", sa.String(length=30), nullable=True),
        sa.Column("health_score", sa.Integer(), nullable=True),
        sa.Column("trend_strength_score", sa.Integer(), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("consensus", sa.JSON(), nullable=True),
        sa.Column("agents", sa.JSON(), nullable=True),
        sa.Column("portfolio_advice", sa.JSON(), nullable=True),
        sa.Column("macro", sa.JSON(), nullable=False),
        sa.Column("crypto", sa.JSON(), nullable=False),
        sa.Column("whale", sa.JSON(), nullable=True),
        sa.Column("etf", sa.JSON(), nullable=True),
        sa.Column("news", sa.JSON(), nullable=False),
        sa.Column("predictions", sa.JSON(), nullable=True),
        sa.Column("alerts", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_market_snapshots_computed_at", "market_snapshots", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_market_snapshots_computed_at", table_name="market_snapshots")
    op.drop_table("market_snapshots")

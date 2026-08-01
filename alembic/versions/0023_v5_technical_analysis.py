"""v5.3: technical_analysis_snapshots table for TradingView MCP Integration

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "technical_analysis_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("bullish_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("bearish_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("trend_strength", sa.Numeric(6, 2), nullable=True),
        sa.Column("momentum", sa.Numeric(10, 4), nullable=True),
        sa.Column("volatility", sa.Numeric(6, 2), nullable=True),
        sa.Column("breakout_probability", sa.Numeric(6, 2), nullable=True),
        sa.Column("breakdown_probability", sa.Numeric(6, 2), nullable=True),
        sa.Column("confidence", sa.Numeric(6, 2), nullable=True),
        sa.Column("active_signals", sa.JSON(), nullable=False),
        sa.Column("timeframes_covered", sa.JSON(), nullable=False),
        sa.Column("support", sa.Numeric(24, 8), nullable=True),
        sa.Column("resistance", sa.Numeric(24, 8), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_technical_analysis_snapshots_symbol", "technical_analysis_snapshots", ["symbol"]
    )
    op.create_index(
        "ix_technical_analysis_snapshots_computed_at",
        "technical_analysis_snapshots",
        ["computed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_technical_analysis_snapshots_computed_at", table_name="technical_analysis_snapshots"
    )
    op.drop_index(
        "ix_technical_analysis_snapshots_symbol", table_name="technical_analysis_snapshots"
    )
    op.drop_table("technical_analysis_snapshots")

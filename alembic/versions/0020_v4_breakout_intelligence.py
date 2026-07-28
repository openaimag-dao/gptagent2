"""v4.0 Phase 2: breakout_events table for Breakout Intelligence

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "breakout_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", sa.String(length=5), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("level", sa.Numeric(24, 8), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("probability_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("confidence_pct", sa.Integer(), nullable=False),
        sa.Column("risk_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("expected_continuation", sa.String(length=40), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("volume_confirmed", sa.Boolean(), nullable=True),
        sa.Column("atr_confirmed", sa.Boolean(), nullable=True),
        sa.Column("vwap_confirmed", sa.Boolean(), nullable=True),
        sa.Column("regime_confirmed", sa.Boolean(), nullable=True),
        sa.Column("oi_funding_confirmed", sa.Boolean(), nullable=True),
        sa.Column("multi_timeframe_confirmed", sa.Boolean(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_breakout_events_symbol", "breakout_events", ["symbol"])
    op.create_index("ix_breakout_events_timeframe", "breakout_events", ["timeframe"])
    op.create_index("ix_breakout_events_computed_at", "breakout_events", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_breakout_events_computed_at", table_name="breakout_events")
    op.drop_index("ix_breakout_events_timeframe", table_name="breakout_events")
    op.drop_index("ix_breakout_events_symbol", table_name="breakout_events")
    op.drop_table("breakout_events")

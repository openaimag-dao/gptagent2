"""probability snapshots + pattern signals

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DIRECTION_VALUES = ("bullish", "bearish", "neutral")


def upgrade() -> None:
    bind = op.get_bind()
    timeframe_enum = PG_ENUM(
        "1d", "4h", "1h", name="history_timeframe", create_type=False
    )
    PG_ENUM(*_DIRECTION_VALUES, name="pattern_direction").create(bind, checkfirst=True)
    direction_enum = PG_ENUM(*_DIRECTION_VALUES, name="pattern_direction", create_type=False)

    op.create_table(
        "probability_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", timeframe_enum, nullable=False),
        sa.Column("horizon_periods", sa.Integer(), nullable=False),
        sa.Column("reference_rsi", sa.Numeric(6, 2), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("prob_up_pct", sa.Integer(), nullable=False),
        sa.Column("prob_down_pct", sa.Integer(), nullable=False),
        sa.Column("prob_flat_pct", sa.Integer(), nullable=False),
        sa.Column("avg_forward_return_pct", sa.Numeric(10, 4), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_probability_snapshots_symbol", "probability_snapshots", ["symbol"]
    )
    op.create_index(
        "ix_probability_snapshots_timeframe", "probability_snapshots", ["timeframe"]
    )
    op.create_index(
        "ix_probability_snapshots_computed_at", "probability_snapshots", ["computed_at"]
    )

    op.create_table(
        "pattern_signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column(
            "timeframe",
            PG_ENUM("1d", "4h", "1h", name="history_timeframe", create_type=False),
            nullable=False,
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pattern_name", sa.String(length=50), nullable=False),
        sa.Column("direction", direction_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pattern_signals_symbol", "pattern_signals", ["symbol"])
    op.create_index("ix_pattern_signals_timeframe", "pattern_signals", ["timeframe"])
    op.create_index("ix_pattern_signals_timestamp", "pattern_signals", ["timestamp"])
    op.create_unique_constraint(
        "uq_pattern_signal",
        "pattern_signals",
        ["symbol", "timeframe", "timestamp", "pattern_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_pattern_signal", "pattern_signals", type_="unique")
    op.drop_index("ix_pattern_signals_timestamp", table_name="pattern_signals")
    op.drop_index("ix_pattern_signals_timeframe", table_name="pattern_signals")
    op.drop_index("ix_pattern_signals_symbol", table_name="pattern_signals")
    op.drop_table("pattern_signals")

    op.drop_index("ix_probability_snapshots_computed_at", table_name="probability_snapshots")
    op.drop_index("ix_probability_snapshots_timeframe", table_name="probability_snapshots")
    op.drop_index("ix_probability_snapshots_symbol", table_name="probability_snapshots")
    op.drop_table("probability_snapshots")

    PG_ENUM(name="pattern_direction").drop(op.get_bind(), checkfirst=True)

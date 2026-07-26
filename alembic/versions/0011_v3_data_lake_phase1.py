"""V3 phase 1: forex history + economic calendar

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-26

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMEFRAME_VALUES = ("1d", "4h", "1h")
_CALENDAR_CATEGORY_VALUES = ("cpi", "ppi", "nfp", "gdp", "fomc", "ecb", "boj", "pboc")


def _history_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column(
            "timeframe",
            PG_ENUM(*_TIMEFRAME_VALUES, name="history_timeframe", create_type=False),
            nullable=False,
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(24, 8), nullable=False),
        sa.Column("high", sa.Numeric(24, 8), nullable=False),
        sa.Column("low", sa.Numeric(24, 8), nullable=False),
        sa.Column("close", sa.Numeric(24, 8), nullable=False),
        sa.Column("volume", sa.Numeric(30, 2), nullable=True),
        sa.Column("return_pct", sa.Numeric(14, 8), nullable=True),
        sa.Column("volatility", sa.Numeric(14, 8), nullable=True),
        sa.Column("atr", sa.Numeric(24, 8), nullable=True),
        sa.Column("rsi", sa.Numeric(6, 2), nullable=True),
        sa.Column("macd", sa.Numeric(24, 8), nullable=True),
        sa.Column("macd_signal", sa.Numeric(24, 8), nullable=True),
        sa.Column("macd_histogram", sa.Numeric(24, 8), nullable=True),
        sa.Column("sma_20", sa.Numeric(24, 8), nullable=True),
        sa.Column("sma_50", sa.Numeric(24, 8), nullable=True),
        sa.Column("sma_200", sa.Numeric(24, 8), nullable=True),
        sa.Column("volume_change_pct", sa.Numeric(14, 8), nullable=True),
        sa.Column(
            "indicators_computed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table("forex_history", *_history_columns())
    op.create_index("ix_forex_history_symbol", "forex_history", ["symbol"])
    op.create_index("ix_forex_history_timeframe", "forex_history", ["timeframe"])
    op.create_index("ix_forex_history_timestamp", "forex_history", ["timestamp"])
    op.create_index(
        "ix_forex_history_indicators_computed", "forex_history", ["indicators_computed"]
    )
    op.create_unique_constraint(
        "uq_forex_history_bar", "forex_history", ["symbol", "timeframe", "timestamp"]
    )

    op.create_table(
        "economic_calendar_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "category",
            sa.Enum(*_CALENDAR_CATEGORY_VALUES, name="economic_calendar_category"),
            nullable=False,
        ),
        sa.Column("country", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("importance", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_economic_calendar_events_event_date", "economic_calendar_events", ["event_date"]
    )
    op.create_index(
        "ix_economic_calendar_events_category", "economic_calendar_events", ["category"]
    )
    op.create_unique_constraint(
        "uq_economic_calendar_event",
        "economic_calendar_events",
        ["category", "country", "event_date"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_economic_calendar_event", "economic_calendar_events", type_="unique"
    )
    op.drop_index(
        "ix_economic_calendar_events_category", table_name="economic_calendar_events"
    )
    op.drop_index(
        "ix_economic_calendar_events_event_date", table_name="economic_calendar_events"
    )
    op.drop_table("economic_calendar_events")
    sa.Enum(name="economic_calendar_category").drop(op.get_bind(), checkfirst=True)

    op.drop_constraint("uq_forex_history_bar", "forex_history", type_="unique")
    op.drop_index("ix_forex_history_indicators_computed", table_name="forex_history")
    op.drop_index("ix_forex_history_timestamp", table_name="forex_history")
    op.drop_index("ix_forex_history_timeframe", table_name="forex_history")
    op.drop_index("ix_forex_history_symbol", table_name="forex_history")
    op.drop_table("forex_history")

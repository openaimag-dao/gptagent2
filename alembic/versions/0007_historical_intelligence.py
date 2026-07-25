"""historical intelligence engine: market/crypto/stock/macro history + events

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMEFRAME_VALUES = ("1d", "4h", "1h")
_EVENT_CATEGORY_VALUES = ("halving", "crash", "macro_policy", "regulatory", "black_swan")
_HISTORY_TABLES = ("market_history", "crypto_history", "stock_history", "macro_history")


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
    bind = op.get_bind()
    PG_ENUM(*_TIMEFRAME_VALUES, name="history_timeframe").create(bind, checkfirst=True)

    for table_name in _HISTORY_TABLES:
        op.create_table(table_name, *_history_columns())
        op.create_index(f"ix_{table_name}_symbol", table_name, ["symbol"])
        op.create_index(f"ix_{table_name}_timeframe", table_name, ["timeframe"])
        op.create_index(f"ix_{table_name}_timestamp", table_name, ["timestamp"])
        op.create_index(
            f"ix_{table_name}_indicators_computed", table_name, ["indicators_computed"]
        )
        op.create_unique_constraint(
            f"uq_{table_name}_bar", table_name, ["symbol", "timeframe", "timestamp"]
        )

    op.create_table(
        "historical_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "category",
            sa.Enum(*_EVENT_CATEGORY_VALUES, name="historical_event_category"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("symbols_affected", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_historical_events_event_date", "historical_events", ["event_date"])
    op.create_index("ix_historical_events_category", "historical_events", ["category"])


def downgrade() -> None:
    op.drop_index("ix_historical_events_category", table_name="historical_events")
    op.drop_index("ix_historical_events_event_date", table_name="historical_events")
    op.drop_table("historical_events")
    sa.Enum(name="historical_event_category").drop(op.get_bind(), checkfirst=True)

    for table_name in reversed(_HISTORY_TABLES):
        op.drop_constraint(f"uq_{table_name}_bar", table_name, type_="unique")
        op.drop_index(f"ix_{table_name}_indicators_computed", table_name=table_name)
        op.drop_index(f"ix_{table_name}_timestamp", table_name=table_name)
        op.drop_index(f"ix_{table_name}_timeframe", table_name=table_name)
        op.drop_index(f"ix_{table_name}_symbol", table_name=table_name)
        op.drop_table(table_name)

    PG_ENUM(name="history_timeframe").drop(op.get_bind(), checkfirst=True)

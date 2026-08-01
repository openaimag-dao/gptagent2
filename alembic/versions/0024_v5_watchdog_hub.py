"""v5.4: watchdog_snapshots + watchdog_events tables for Next Generation Market Watchdog

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-01

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watchdog_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scan_duration_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("regime", sa.String(length=30), nullable=True),
        sa.Column("market_health", sa.String(length=20), nullable=False),
        sa.Column("global_score", sa.Integer(), nullable=True),
        sa.Column("trend_strength_score", sa.Integer(), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("liquidity_score", sa.Integer(), nullable=True),
        sa.Column("volatility", sa.Numeric(6, 2), nullable=True),
        sa.Column("consensus", sa.JSON(), nullable=True),
        sa.Column("committee_decision", sa.String(length=10), nullable=True),
        sa.Column("committee_confidence_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("committee_recommendation", sa.String(length=60), nullable=True),
        sa.Column("expected_scenario", sa.String(length=40), nullable=True),
        sa.Column("expected_scenario_pct", sa.Integer(), nullable=True),
        sa.Column("highest_risk", sa.Text(), nullable=True),
        sa.Column("biggest_opportunity", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_watchdog_snapshots_computed_at", "watchdog_snapshots", ["computed_at"]
    )

    op.create_table(
        "watchdog_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("telegram_sent", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_watchdog_events_event_type", "watchdog_events", ["event_type"])
    op.create_index("ix_watchdog_events_telegram_sent", "watchdog_events", ["telegram_sent"])
    op.create_index("ix_watchdog_events_created_at", "watchdog_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_watchdog_events_created_at", table_name="watchdog_events")
    op.drop_index("ix_watchdog_events_telegram_sent", table_name="watchdog_events")
    op.drop_index("ix_watchdog_events_event_type", table_name="watchdog_events")
    op.drop_table("watchdog_events")

    op.drop_index("ix_watchdog_snapshots_computed_at", table_name="watchdog_snapshots")
    op.drop_table("watchdog_snapshots")

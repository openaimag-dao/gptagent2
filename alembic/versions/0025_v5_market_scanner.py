"""v5.5: scanner_snapshots + scanner_alerts tables for the Autonomous Market Scanner

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-01

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scanner_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("change_pct_1h", sa.Numeric(10, 4), nullable=True),
        sa.Column("change_pct_24h", sa.Numeric(10, 4), nullable=True),
        sa.Column("volume_24h", sa.Numeric(24, 2), nullable=True),
        sa.Column("market_cap", sa.Numeric(24, 2), nullable=True),
        sa.Column("market_cap_rank", sa.Integer(), nullable=True),
        sa.Column("sector", sa.String(length=30), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scanner_snapshots_symbol", "scanner_snapshots", ["symbol"])
    op.create_index("ix_scanner_snapshots_recorded_at", "scanner_snapshots", ["recorded_at"])

    op.create_table(
        "scanner_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("alert_key", sa.String(length=60), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("tier", sa.String(length=10), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("telegram_message_ids", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("first_triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_scanner_alerts_alert_key", "scanner_alerts", ["alert_key"])
    op.create_index("ix_scanner_alerts_active", "scanner_alerts", ["active"])


def downgrade() -> None:
    op.drop_index("ix_scanner_alerts_active", table_name="scanner_alerts")
    op.drop_index("ix_scanner_alerts_alert_key", table_name="scanner_alerts")
    op.drop_table("scanner_alerts")

    op.drop_index("ix_scanner_snapshots_recorded_at", table_name="scanner_snapshots")
    op.drop_index("ix_scanner_snapshots_symbol", table_name="scanner_snapshots")
    op.drop_table("scanner_snapshots")

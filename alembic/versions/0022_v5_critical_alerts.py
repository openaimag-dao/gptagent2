"""v5.1: critical_alerts table for the Autonomous Critical Alert System

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "critical_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("alert_key", sa.String(length=60), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("tier", sa.String(length=10), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("telegram_message_ids", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("first_triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_critical_alerts_alert_key", "critical_alerts", ["alert_key"])
    op.create_index("ix_critical_alerts_active", "critical_alerts", ["active"])


def downgrade() -> None:
    op.drop_index("ix_critical_alerts_active", table_name="critical_alerts")
    op.drop_index("ix_critical_alerts_alert_key", table_name="critical_alerts")
    op.drop_table("critical_alerts")

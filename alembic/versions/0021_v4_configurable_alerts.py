"""v4.0 Phase 8: alert_rules table for Configurable Alerts

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("metric", sa.String(length=30), nullable=False),
        sa.Column("operator", sa.String(length=10), nullable=False),
        sa.Column("threshold", sa.Numeric(24, 8), nullable=False),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alert_rules_chat_id", "alert_rules", ["chat_id"])
    op.create_index("ix_alert_rules_symbol", "alert_rules", ["symbol"])
    op.create_index("ix_alert_rules_enabled", "alert_rules", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_alert_rules_enabled", table_name="alert_rules")
    op.drop_index("ix_alert_rules_symbol", table_name="alert_rules")
    op.drop_index("ix_alert_rules_chat_id", table_name="alert_rules")
    op.drop_table("alert_rules")

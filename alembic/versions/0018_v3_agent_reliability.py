"""v3.0: agent_prediction_logs table for the Agent Reliability Engine

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_prediction_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent", sa.String(length=30), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reference_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_periods", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_prediction_logs_agent", "agent_prediction_logs", ["agent"])
    op.create_index(
        "ix_agent_prediction_logs_reference_timestamp",
        "agent_prediction_logs",
        ["reference_timestamp"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_prediction_logs_reference_timestamp", table_name="agent_prediction_logs"
    )
    op.drop_index("ix_agent_prediction_logs_agent", table_name="agent_prediction_logs")
    op.drop_table("agent_prediction_logs")

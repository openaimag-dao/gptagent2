"""reports table

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-24

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("report_type", sa.String(length=30), nullable=False),
        sa.Column("regime", sa.String(length=30), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("bull_score", sa.Integer(), nullable=False),
        sa.Column("bear_score", sa.Integer(), nullable=False),
        sa.Column("confidence_pct", sa.Integer(), nullable=False),
        sa.Column("market_summary", sa.JSON(), nullable=False),
        sa.Column("correlations_summary", sa.JSON(), nullable=False),
        sa.Column("analysis", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reports_report_type", "reports", ["report_type"])
    op.create_index("ix_reports_generated_at", "reports", ["generated_at"])


def downgrade() -> None:
    op.drop_index("ix_reports_generated_at", table_name="reports")
    op.drop_index("ix_reports_report_type", table_name="reports")
    op.drop_table("reports")

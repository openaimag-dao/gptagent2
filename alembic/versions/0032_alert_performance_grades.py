"""V9 Increment 9: alert_performance_grades table

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_performance_grades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("alert_log_id", sa.Integer(), nullable=False),
        sa.Column("alert_type", sa.String(40), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("reference_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("evaluated_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("realized_move_pct", sa.Numeric(10, 4), nullable=False),
        sa.Column("significant_move", sa.Boolean(), nullable=False),
        sa.Column("implied_direction", sa.String(10), nullable=True),
        sa.Column("direction_continued", sa.Boolean(), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_alert_performance_grades_alert_log_id",
        "alert_performance_grades",
        ["alert_log_id"],
        unique=True,
    )
    op.create_index(
        "ix_alert_performance_grades_alert_type",
        "alert_performance_grades",
        ["alert_type"],
    )
    op.create_index("ix_alert_performance_grades_symbol", "alert_performance_grades", ["symbol"])
    op.create_index(
        "ix_alert_performance_grades_triggered_at",
        "alert_performance_grades",
        ["triggered_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_alert_performance_grades_triggered_at", "alert_performance_grades")
    op.drop_index("ix_alert_performance_grades_symbol", "alert_performance_grades")
    op.drop_index("ix_alert_performance_grades_alert_type", "alert_performance_grades")
    op.drop_index("ix_alert_performance_grades_alert_log_id", "alert_performance_grades")
    op.drop_table("alert_performance_grades")

"""POST-V9 Phase 10/11: excursion/baseline-edge columns on
alert_performance_grades

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "alert_performance_grades",
        sa.Column("max_favorable_excursion_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "alert_performance_grades",
        sa.Column("max_adverse_excursion_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "alert_performance_grades",
        sa.Column("peak_move_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "alert_performance_grades",
        sa.Column("time_to_peak_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "alert_performance_grades",
        sa.Column("baseline_return_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "alert_performance_grades",
        sa.Column("edge_vs_baseline_pct", sa.Numeric(10, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("alert_performance_grades", "edge_vs_baseline_pct")
    op.drop_column("alert_performance_grades", "baseline_return_pct")
    op.drop_column("alert_performance_grades", "time_to_peak_days")
    op.drop_column("alert_performance_grades", "peak_move_pct")
    op.drop_column("alert_performance_grades", "max_adverse_excursion_pct")
    op.drop_column("alert_performance_grades", "max_favorable_excursion_pct")

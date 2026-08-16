"""POST-V9 Phase 14: naive-baseline comparison columns on
price_forecast_snapshots

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("momentum_baseline_correct", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("historical_mean_baseline_error_pct", sa.Numeric(10, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_forecast_snapshots", "historical_mean_baseline_error_pct")
    op.drop_column("price_forecast_snapshots", "momentum_baseline_correct")

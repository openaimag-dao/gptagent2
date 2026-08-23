"""Forecasting 3.0: regime-mean-baseline column on price_forecast_snapshots

Revision ID: 0041
Revises: 0040
Create Date: 2026-08-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("regime_mean_baseline_error_pct", sa.Numeric(10, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_forecast_snapshots", "regime_mean_baseline_error_pct")

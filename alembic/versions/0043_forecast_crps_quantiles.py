"""Forecasting 3.0 (Phase 5/12/13): forward-return quantile + CRPS columns
on price_forecast_snapshots

Revision ID: 0043
Revises: 0042
Create Date: 2026-08-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column_name in ("p10_pct", "p25_pct", "p50_pct", "p75_pct", "p90_pct", "crps_pct"):
        op.add_column(
            "price_forecast_snapshots",
            sa.Column(column_name, sa.Numeric(10, 4), nullable=True),
        )


def downgrade() -> None:
    for column_name in ("crps_pct", "p90_pct", "p75_pct", "p50_pct", "p25_pct", "p10_pct"):
        op.drop_column("price_forecast_snapshots", column_name)

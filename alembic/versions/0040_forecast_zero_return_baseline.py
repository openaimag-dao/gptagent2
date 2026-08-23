"""Forecasting 3.0: zero-return-baseline column on price_forecast_snapshots

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("zero_return_baseline_error_pct", sa.Numeric(10, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_forecast_snapshots", "zero_return_baseline_error_pct")

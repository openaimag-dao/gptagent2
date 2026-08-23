"""Forecasting 3.0 (Phase 22): calibrated_confidence_pct/data_quality_score
columns on price_forecast_snapshots

Revision ID: 0042
Revises: 0041
Create Date: 2026-08-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("calibrated_confidence_pct", sa.Integer(), nullable=True),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("data_quality_score", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_forecast_snapshots", "data_quality_score")
    op.drop_column("price_forecast_snapshots", "calibrated_confidence_pct")

"""V9 Increment 3: forecast_version/regime_at_forecast/forecast_status/
invalidation_reason/invalidated_at on price_forecast_snapshots

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-13

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("forecast_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("regime_at_forecast", sa.String(30), nullable=True),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("forecast_status", sa.String(20), nullable=False, server_default="ACTIVE"),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("invalidation_reason", sa.String(255), nullable=True),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_forecast_snapshots", "invalidated_at")
    op.drop_column("price_forecast_snapshots", "invalidation_reason")
    op.drop_column("price_forecast_snapshots", "forecast_status")
    op.drop_column("price_forecast_snapshots", "regime_at_forecast")
    op.drop_column("price_forecast_snapshots", "forecast_version")

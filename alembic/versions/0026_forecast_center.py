"""AI Forecast Center: price_forecast_snapshots table

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_forecast_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("horizon", sa.String(length=10), nullable=False),
        sa.Column("current_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("target_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("expected_change_pct", sa.Numeric(10, 4), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("probability_pct", sa.Integer(), nullable=False),
        sa.Column("checkpoints", sa.JSON(), nullable=False),
        sa.Column("distribution", sa.JSON(), nullable=False),
        sa.Column("key_levels", sa.JSON(), nullable=False),
        sa.Column("realized_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("error_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_price_forecast_snapshots_symbol", "price_forecast_snapshots", ["symbol"]
    )
    op.create_index(
        "ix_price_forecast_snapshots_horizon", "price_forecast_snapshots", ["horizon"]
    )
    op.create_index(
        "ix_price_forecast_snapshots_computed_at", "price_forecast_snapshots", ["computed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_price_forecast_snapshots_computed_at", table_name="price_forecast_snapshots")
    op.drop_index("ix_price_forecast_snapshots_horizon", table_name="price_forecast_snapshots")
    op.drop_index("ix_price_forecast_snapshots_symbol", table_name="price_forecast_snapshots")
    op.drop_table("price_forecast_snapshots")

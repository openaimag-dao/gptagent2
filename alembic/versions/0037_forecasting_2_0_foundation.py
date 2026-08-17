"""Forecasting 2.0 foundation: official-daily flag + excursion/error-type
columns on price_forecast_snapshots, new agent_forecasts table

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-17

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("is_official_daily", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("official_forecast_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("max_favorable_excursion_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("max_adverse_excursion_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("error_type", sa.String(length=30), nullable=True),
    )
    op.create_index(
        "ix_price_forecast_snapshots_is_official_daily",
        "price_forecast_snapshots",
        ["is_official_daily"],
    )
    op.create_index(
        "uq_official_daily_forecast",
        "price_forecast_snapshots",
        ["symbol", "horizon", "official_forecast_date"],
        unique=True,
        postgresql_where=sa.text("is_official_daily IS TRUE"),
    )

    op.create_table(
        "agent_forecasts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "forecast_id",
            sa.Integer(),
            sa.ForeignKey("price_forecast_snapshots.id"),
            nullable=False,
        ),
        sa.Column("agent_name", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=True),
        sa.Column("confidence_pct", sa.Integer(), nullable=True),
        sa.Column("key_factors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_forecasts_forecast_id", "agent_forecasts", ["forecast_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_forecasts_forecast_id", table_name="agent_forecasts")
    op.drop_table("agent_forecasts")
    op.drop_index("uq_official_daily_forecast", table_name="price_forecast_snapshots")
    op.drop_index(
        "ix_price_forecast_snapshots_is_official_daily", table_name="price_forecast_snapshots"
    )
    op.drop_column("price_forecast_snapshots", "error_type")
    op.drop_column("price_forecast_snapshots", "max_adverse_excursion_pct")
    op.drop_column("price_forecast_snapshots", "max_favorable_excursion_pct")
    op.drop_column("price_forecast_snapshots", "official_forecast_date")
    op.drop_column("price_forecast_snapshots", "is_official_daily")

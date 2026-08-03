"""AI Forecast Center follow-up: reference_timestamp + confidence_tier on
price_forecast_snapshots, for the prediction-history grading job

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("confidence_tier", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("reference_timestamp", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_price_forecast_snapshots_reference_timestamp",
        "price_forecast_snapshots",
        ["reference_timestamp"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_price_forecast_snapshots_reference_timestamp", table_name="price_forecast_snapshots"
    )
    op.drop_column("price_forecast_snapshots", "reference_timestamp")
    op.drop_column("price_forecast_snapshots", "confidence_tier")

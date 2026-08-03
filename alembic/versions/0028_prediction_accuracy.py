"""Prediction Accuracy: direction_correct + confidence_correct on
price_forecast_snapshots, filled in by the grading job

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("direction_correct", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("confidence_correct", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_forecast_snapshots", "confidence_correct")
    op.drop_column("price_forecast_snapshots", "direction_correct")

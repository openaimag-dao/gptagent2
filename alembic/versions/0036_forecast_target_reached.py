"""Forecast Intelligence Upgrade: target_reached column on
price_forecast_snapshots

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("target_reached", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_forecast_snapshots", "target_reached")

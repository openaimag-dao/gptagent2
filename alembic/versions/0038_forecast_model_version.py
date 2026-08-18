"""Final audit (Phase 22): model_version column on price_forecast_snapshots

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-18

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_forecast_snapshots",
        sa.Column("model_version", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_forecast_snapshots", "model_version")

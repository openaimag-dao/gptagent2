"""POST-V9 Phase 5: regime_at_prediction column on agent_prediction_logs

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_prediction_logs",
        sa.Column("regime_at_prediction", sa.String(length=30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_prediction_logs", "regime_at_prediction")

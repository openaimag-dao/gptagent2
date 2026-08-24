"""Futures Simulator: optional per-account Max Risk Settings overrides

Revision ID: 0046
Revises: 0045
Create Date: 2026-08-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All nullable: NULL means "use the global futures_sim_risk_* setting",
    # not "zero" -- this is the task's own "optional" Max Risk Settings, a
    # per-account override layer over the server-side defaults, never a
    # required field.
    op.add_column(
        "futures_sim_accounts",
        sa.Column("risk_high_margin_ratio_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "futures_sim_accounts",
        sa.Column("risk_near_liquidation_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "futures_sim_accounts",
        sa.Column("risk_margin_warning_available_pct", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "futures_sim_accounts",
        sa.Column("risk_daily_loss_warning_pct", sa.Numeric(10, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("futures_sim_accounts", "risk_daily_loss_warning_pct")
    op.drop_column("futures_sim_accounts", "risk_margin_warning_available_pct")
    op.drop_column("futures_sim_accounts", "risk_near_liquidation_pct")
    op.drop_column("futures_sim_accounts", "risk_high_margin_ratio_pct")

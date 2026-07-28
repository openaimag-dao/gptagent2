"""v3.0: extend market_regime_type with strong_bull/bull_weakening/altseason;
add trend_strength_score/risk_score/confidence_score to global_market_scores

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_REGIME_VALUES = ("strong_bull", "bull_weakening", "altseason")


def upgrade() -> None:
    # Postgres allows adding enum values inside a transaction (PG 12+) as
    # long as the new value isn't used in that same transaction -- it isn't
    # here, so this is safe as a normal migration (same pattern as 0013).
    for value in _NEW_REGIME_VALUES:
        op.execute(f"ALTER TYPE market_regime_type ADD VALUE IF NOT EXISTS '{value}'")

    op.add_column(
        "global_market_scores", sa.Column("trend_strength_score", sa.Integer(), nullable=True)
    )
    op.add_column("global_market_scores", sa.Column("risk_score", sa.Integer(), nullable=True))
    op.add_column(
        "global_market_scores", sa.Column("confidence_score", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("global_market_scores", "confidence_score")
    op.drop_column("global_market_scores", "risk_score")
    op.drop_column("global_market_scores", "trend_strength_score")
    # Postgres has no ALTER TYPE ... DROP VALUE -- same documented
    # limitation as 0013's downgrade.

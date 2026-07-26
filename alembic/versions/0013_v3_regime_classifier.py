"""V3 phase 5: extend market_regime_type with bull/bear/accumulation/
distribution/capitulation/recovery/sideways

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-26

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_VALUES = (
    "bull",
    "bear",
    "accumulation",
    "distribution",
    "capitulation",
    "recovery",
    "sideways",
)


def upgrade() -> None:
    # Postgres allows adding enum values inside a transaction (PG 12+) as
    # long as the new value isn't used in that same transaction -- it isn't
    # here, so this is safe as a normal migration.
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE market_regime_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. Safely removing these
    # would require recreating the enum type and re-casting every existing
    # row, which fails outright if any row already uses one of the new
    # values -- an acceptable, deliberate limitation: this downgrade leaves
    # the added enum values in place rather than risk data loss.
    pass

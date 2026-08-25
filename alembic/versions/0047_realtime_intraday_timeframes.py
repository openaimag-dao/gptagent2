"""Futures Simulator chart: 5m/15m realtime-aggregated history timeframes

Revision ID: 0047
Revises: 0046
Create Date: 2026-08-25

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TIMEFRAME_VALUES = ("5m", "15m")


def upgrade() -> None:
    # Postgres allows adding enum values inside a transaction (PG 12+) as
    # long as the new value isn't used in that same transaction -- it isn't
    # here (this migration writes no 5m/15m rows), so this is safe as a
    # normal migration. Same pattern as 0013 and 0017.
    #
    # history_timeframe is shared by market/crypto/stock/macro_history;
    # adding values is additive and affects no existing row. New values
    # sort after '1h' in the type's ordering, which is harmless -- every
    # query in this codebase orders by `timestamp`, never by `timeframe`.
    for value in _NEW_TIMEFRAME_VALUES:
        op.execute(f"ALTER TYPE history_timeframe ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE -- same documented
    # limitation as 0013/0017's downgrades: the added values stay in place
    # rather than risk data loss from recreating and re-casting the type.
    pass

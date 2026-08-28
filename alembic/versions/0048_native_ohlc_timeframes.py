"""Native CoinGecko OHLC history timeframes: 30m, 4d

Revision ID: 0048
Revises: 0047
Create Date: 2026-08-28

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TIMEFRAME_VALUES = ("30m", "4d")


def upgrade() -> None:
    # Same pattern as 0013/0017/0047: adding enum values is safe inside a
    # normal migration transaction on PG12+ as long as the transaction
    # doesn't also use the new value, which this one doesn't.
    for value in _NEW_TIMEFRAME_VALUES:
        op.execute(f"ALTER TYPE history_timeframe ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE -- same documented
    # limitation as 0013/0017/0047's downgrades.
    pass

"""Composite (symbol, recorded_at) index on scanner_snapshots -- the scan
cycle's own history lookup filters on both columns together across up to
~500 symbols and a 30-day lookback every cycle; the existing single-column
indexes on each require Postgres to bitmap-intersect them instead of using
one covering index scan.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_scanner_snapshots_symbol_recorded_at",
        "scanner_snapshots",
        ["symbol", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scanner_snapshots_symbol_recorded_at", table_name="scanner_snapshots")

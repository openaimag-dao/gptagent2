"""initial schema: snapshot_batches and asset_prices

Revision ID: 0001
Revises:
Create Date: 2026-07-24

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "snapshot_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_snapshot_batches_collected_at", "snapshot_batches", ["collected_at"])

    op.create_table(
        "asset_prices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("snapshot_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "asset_class",
            sa.Enum("crypto", "stock", "index", "macro", name="asset_class"),
            nullable=False,
        ),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("change_24h", sa.Numeric(24, 8), nullable=True),
        sa.Column("change_pct_24h", sa.Numeric(10, 4), nullable=True),
        sa.Column("market_cap", sa.Numeric(30, 2), nullable=True),
        sa.Column("volume_24h", sa.Numeric(30, 2), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_asset_prices_batch_id", "asset_prices", ["batch_id"])
    op.create_index("ix_asset_prices_symbol", "asset_prices", ["symbol"])
    op.create_index("ix_asset_prices_recorded_at", "asset_prices", ["recorded_at"])


def downgrade() -> None:
    op.drop_index("ix_asset_prices_recorded_at", table_name="asset_prices")
    op.drop_index("ix_asset_prices_symbol", table_name="asset_prices")
    op.drop_index("ix_asset_prices_batch_id", table_name="asset_prices")
    op.drop_table("asset_prices")
    sa.Enum(name="asset_class").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_snapshot_batches_collected_at", table_name="snapshot_batches")
    op.drop_table("snapshot_batches")

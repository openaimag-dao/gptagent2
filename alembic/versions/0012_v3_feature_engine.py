"""V3 phase 2: feature snapshots

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feature_snapshots_symbol", "feature_snapshots", ["symbol"])
    op.create_index("ix_feature_snapshots_computed_at", "feature_snapshots", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_feature_snapshots_computed_at", table_name="feature_snapshots")
    op.drop_index("ix_feature_snapshots_symbol", table_name="feature_snapshots")
    op.drop_table("feature_snapshots")

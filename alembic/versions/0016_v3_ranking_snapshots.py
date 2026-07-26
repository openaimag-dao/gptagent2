"""V3 phase 9: ranking snapshots

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ranking_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("target_symbol", sa.String(length=20), nullable=False),
        sa.Column("rankings", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ranking_snapshots_target_symbol", "ranking_snapshots", ["target_symbol"])
    op.create_index("ix_ranking_snapshots_computed_at", "ranking_snapshots", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_ranking_snapshots_computed_at", table_name="ranking_snapshots")
    op.drop_index("ix_ranking_snapshots_target_symbol", table_name="ranking_snapshots")
    op.drop_table("ranking_snapshots")

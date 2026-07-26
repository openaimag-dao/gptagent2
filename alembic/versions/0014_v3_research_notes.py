"""V3 phase 7: research notes

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("discoveries", sa.JSON(), nullable=False),
        sa.Column("discovery_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_notes_generated_at", "research_notes", ["generated_at"])


def downgrade() -> None:
    op.drop_index("ix_research_notes_generated_at", table_name="research_notes")
    op.drop_table("research_notes")

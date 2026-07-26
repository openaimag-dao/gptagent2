"""V3 phase 8: hypotheses

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-26

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VERDICT_VALUES = ("accepted", "rejected", "inconclusive")


def upgrade() -> None:
    op.create_table(
        "hypotheses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("statement", sa.String(length=300), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("event_a", sa.String(length=30), nullable=False),
        sa.Column("event_b", sa.String(length=30), nullable=False),
        sa.Column("verdict", sa.Enum(*_VERDICT_VALUES, name="hypothesis_verdict"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("result_a", sa.JSON(), nullable=True),
        sa.Column("result_b", sa.JSON(), nullable=True),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hypotheses_symbol", "hypotheses", ["symbol"])
    op.create_index("ix_hypotheses_verdict", "hypotheses", ["verdict"])
    op.create_index("ix_hypotheses_tested_at", "hypotheses", ["tested_at"])


def downgrade() -> None:
    op.drop_index("ix_hypotheses_tested_at", table_name="hypotheses")
    op.drop_index("ix_hypotheses_verdict", table_name="hypotheses")
    op.drop_index("ix_hypotheses_symbol", table_name="hypotheses")
    op.drop_table("hypotheses")
    sa.Enum(name="hypothesis_verdict").drop(op.get_bind(), checkfirst=True)

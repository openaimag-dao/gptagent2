"""news items table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-24

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "federal_reserve", "sec", "etf", "crypto", "stocks", "macro", name="news_category"
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "sentiment",
            sa.Enum("bullish", "bearish", "neutral", name="news_sentiment"),
            nullable=False,
        ),
        sa.Column("sentiment_score", sa.Numeric(6, 2), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_news_items_source", "news_items", ["source"])
    op.create_index("ix_news_items_category", "news_items", ["category"])
    op.create_index("ix_news_items_url", "news_items", ["url"], unique=True)
    op.create_index("ix_news_items_fetched_at", "news_items", ["fetched_at"])


def downgrade() -> None:
    op.drop_index("ix_news_items_fetched_at", table_name="news_items")
    op.drop_index("ix_news_items_url", table_name="news_items")
    op.drop_index("ix_news_items_category", table_name="news_items")
    op.drop_index("ix_news_items_source", table_name="news_items")
    op.drop_table("news_items")
    sa.Enum(name="news_sentiment").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="news_category").drop(op.get_bind(), checkfirst=True)

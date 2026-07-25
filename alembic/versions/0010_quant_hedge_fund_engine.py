"""sentiment, scenario, whale/etf snapshots, alerts, portfolios (V2)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-25

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- sentiment_snapshots --
    op.create_table(
        "sentiment_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fear_greed_value", sa.Integer(), nullable=True),
        sa.Column("fear_greed_classification", sa.String(length=30), nullable=True),
        sa.Column("news_sentiment_score", sa.Integer(), nullable=True),
        sa.Column("news_items_analyzed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "social_sentiment_available", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("social_sentiment_reason", sa.Text(), nullable=True),
        sa.Column("global_sentiment_score", sa.Integer(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sentiment_snapshots_computed_at", "sentiment_snapshots", ["computed_at"])

    # -- scenario_snapshots --
    op.create_table(
        "scenario_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scenarios", sa.JSON(), nullable=False),
        sa.Column("global_score", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scenario_snapshots_computed_at", "scenario_snapshots", ["computed_at"])

    # -- whale_snapshots --
    op.create_table(
        "whale_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("classification", sa.String(length=30), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_whale_snapshots_symbol", "whale_snapshots", ["symbol"])
    op.create_index("ix_whale_snapshots_computed_at", "whale_snapshots", ["computed_at"])

    # -- etf_flow_snapshots --
    op.create_table(
        "etf_flow_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("classification", sa.String(length=40), nullable=True),
        sa.Column("bullish_items", sa.Integer(), nullable=True),
        sa.Column("bearish_items", sa.Integer(), nullable=True),
        sa.Column("neutral_items", sa.Integer(), nullable=True),
        sa.Column("items_analyzed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_hours", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_etf_flow_snapshots_computed_at", "etf_flow_snapshots", ["computed_at"])

    # -- alert_logs --
    op.create_table(
        "alert_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("alert_type", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("conviction_tier", sa.String(length=20), nullable=False),
        sa.Column("confidence_pct", sa.Integer(), nullable=False),
        sa.Column("broadcast", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alert_logs_alert_type", "alert_logs", ["alert_type"])
    op.create_index("ix_alert_logs_broadcast", "alert_logs", ["broadcast"])
    op.create_index("ix_alert_logs_triggered_at", "alert_logs", ["triggered_at"])

    # -- portfolios / portfolio_positions --
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_portfolios_name", "portfolios", ["name"], unique=True)

    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("entry_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_portfolio_positions_portfolio_id", "portfolio_positions", ["portfolio_id"]
    )
    op.create_index("ix_portfolio_positions_symbol", "portfolio_positions", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_portfolio_positions_symbol", table_name="portfolio_positions")
    op.drop_index("ix_portfolio_positions_portfolio_id", table_name="portfolio_positions")
    op.drop_table("portfolio_positions")

    op.drop_index("ix_portfolios_name", table_name="portfolios")
    op.drop_table("portfolios")

    op.drop_index("ix_alert_logs_triggered_at", table_name="alert_logs")
    op.drop_index("ix_alert_logs_broadcast", table_name="alert_logs")
    op.drop_index("ix_alert_logs_alert_type", table_name="alert_logs")
    op.drop_table("alert_logs")

    op.drop_index("ix_etf_flow_snapshots_computed_at", table_name="etf_flow_snapshots")
    op.drop_table("etf_flow_snapshots")

    op.drop_index("ix_whale_snapshots_computed_at", table_name="whale_snapshots")
    op.drop_index("ix_whale_snapshots_symbol", table_name="whale_snapshots")
    op.drop_table("whale_snapshots")

    op.drop_index("ix_scenario_snapshots_computed_at", table_name="scenario_snapshots")
    op.drop_table("scenario_snapshots")

    op.drop_index("ix_sentiment_snapshots_computed_at", table_name="sentiment_snapshots")
    op.drop_table("sentiment_snapshots")

"""global market score, knowledge rules, similar market matches, brain enrichment

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RULE_CATEGORY_VALUES = ("theory", "rule", "macro_idea", "crypto_idea")


def _timeframe_enum() -> PG_ENUM:
    return PG_ENUM("1d", "4h", "1h", name="history_timeframe", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    # -- global_market_scores --
    op.create_table(
        "global_market_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("risk_on_score", sa.Integer(), nullable=False),
        sa.Column("risk_off_score", sa.Integer(), nullable=False),
        sa.Column("liquidity_score", sa.Integer(), nullable=False),
        sa.Column("fear_score", sa.Integer(), nullable=False),
        sa.Column("greed_score", sa.Integer(), nullable=False),
        sa.Column("macro_pressure_score", sa.Integer(), nullable=False),
        sa.Column("institutional_activity_score", sa.Integer(), nullable=False),
        sa.Column("crypto_strength_score", sa.Integer(), nullable=False),
        sa.Column("stock_strength_score", sa.Integer(), nullable=False),
        sa.Column("global_score", sa.Integer(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_global_market_scores_computed_at", "global_market_scores", ["computed_at"]
    )

    # -- knowledge_rules --
    PG_ENUM(*_RULE_CATEGORY_VALUES, name="rule_category").create(bind, checkfirst=True)
    op.create_table(
        "knowledge_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "category",
            PG_ENUM(*_RULE_CATEGORY_VALUES, name="rule_category", create_type=False),
            nullable=False,
        ),
        sa.Column("author", sa.String(length=100), nullable=False),
        sa.Column("target_symbol", sa.String(length=20), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("horizon_periods", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("occurrences", sa.Integer(), nullable=True),
        sa.Column("win_rate_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("avg_return_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("max_drawdown_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("profit_factor", sa.Numeric(10, 4), nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(10, 4), nullable=True),
        sa.Column("confidence_pct", sa.Integer(), nullable=True),
        sa.Column("last_backtested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_knowledge_rules_category", "knowledge_rules", ["category"])
    op.create_index("ix_knowledge_rules_target_symbol", "knowledge_rules", ["target_symbol"])
    op.create_index("ix_knowledge_rules_created_at", "knowledge_rules", ["created_at"])

    # -- similar_market_matches --
    op.create_table(
        "similar_market_matches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("timeframe", _timeframe_enum(), nullable=False),
        sa.Column("reference_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("match_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("similarity_score", sa.Numeric(6, 2), nullable=False),
        sa.Column("market_regime", sa.String(length=30), nullable=True),
        sa.Column("btc_result_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("nasdaq_result_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("forward_return_1d_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("forward_return_3d_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("forward_return_7d_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("forward_return_30d_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_similar_market_matches_symbol", "similar_market_matches", ["symbol"])
    op.create_index(
        "ix_similar_market_matches_timeframe", "similar_market_matches", ["timeframe"]
    )
    op.create_index(
        "ix_similar_market_matches_reference_timestamp",
        "similar_market_matches",
        ["reference_timestamp"],
    )
    op.create_index(
        "ix_similar_market_matches_match_timestamp",
        "similar_market_matches",
        ["match_timestamp"],
    )

    # -- brain enrichment: probability self-learning + report institutional summary --
    op.add_column(
        "probability_snapshots",
        sa.Column("reference_timestamp", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_probability_snapshots_reference_timestamp",
        "probability_snapshots",
        ["reference_timestamp"],
    )
    op.add_column(
        "reports",
        sa.Column(
            "institutional_summary", sa.JSON(), nullable=False, server_default="{}"
        ),
    )


def downgrade() -> None:
    op.drop_column("reports", "institutional_summary")
    op.drop_index(
        "ix_probability_snapshots_reference_timestamp", table_name="probability_snapshots"
    )
    op.drop_column("probability_snapshots", "reference_timestamp")

    op.drop_index(
        "ix_similar_market_matches_match_timestamp", table_name="similar_market_matches"
    )
    op.drop_index(
        "ix_similar_market_matches_reference_timestamp", table_name="similar_market_matches"
    )
    op.drop_index("ix_similar_market_matches_timeframe", table_name="similar_market_matches")
    op.drop_index("ix_similar_market_matches_symbol", table_name="similar_market_matches")
    op.drop_table("similar_market_matches")

    op.drop_index("ix_knowledge_rules_created_at", table_name="knowledge_rules")
    op.drop_index("ix_knowledge_rules_target_symbol", table_name="knowledge_rules")
    op.drop_index("ix_knowledge_rules_category", table_name="knowledge_rules")
    op.drop_table("knowledge_rules")
    PG_ENUM(name="rule_category").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_global_market_scores_computed_at", table_name="global_market_scores")
    op.drop_table("global_market_scores")

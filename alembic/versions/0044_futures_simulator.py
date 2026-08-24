"""Futures Simulator: demo/paper-trading account/position/order/trade/ledger
tables

Revision ID: 0044
Revises: 0043
Create Date: 2026-08-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "futures_sim_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("account_session_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="ACTIVE"),
        sa.Column("wallet_balance", sa.Numeric(24, 8), nullable=False),
        sa.Column("realized_pnl_total", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("fees_paid_total", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("funding_paid_total", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("peak_equity", sa.Numeric(24, 8), nullable=False),
        sa.Column("max_drawdown_pct", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_futures_sim_accounts_name", "futures_sim_accounts", ["name"])
    op.create_index(
        "ix_futures_sim_accounts_account_session_id",
        "futures_sim_accounts",
        ["account_session_id"],
        unique=True,
    )
    op.create_index("ix_futures_sim_accounts_status", "futures_sim_accounts", ["status"])
    op.create_index(
        "uq_futures_sim_account_active_name",
        "futures_sim_accounts",
        ["name"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "futures_sim_positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("futures_sim_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(5), nullable=False),
        sa.Column("margin_mode", sa.String(10), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("entry_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("mark_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("initial_margin", sa.Numeric(24, 8), nullable=False),
        sa.Column("maintenance_margin", sa.Numeric(24, 8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("liquidation_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("sl_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("tp_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="OPEN"),
        sa.Column("close_reason", sa.String(20), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_futures_sim_positions_account_id", "futures_sim_positions", ["account_id"])
    op.create_index("ix_futures_sim_positions_symbol", "futures_sim_positions", ["symbol"])
    op.create_index("ix_futures_sim_positions_status", "futures_sim_positions", ["status"])
    op.create_index("ix_futures_sim_positions_opened_at", "futures_sim_positions", ["opened_at"])

    op.create_table(
        "futures_sim_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("futures_sim_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position_id",
            sa.Integer(),
            sa.ForeignKey("futures_sim_positions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("client_order_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("position_side", sa.String(5), nullable=False),
        sa.Column("order_type", sa.String(20), nullable=False),
        sa.Column("margin_mode", sa.String(10), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=True),
        sa.Column("stop_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("reduce_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="NEW"),
        sa.Column("requested_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("estimated_fill_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("actual_fill_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("slippage_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("filled_quantity", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("fee_rate_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("fee_amount", sa.Numeric(24, 8), nullable=True),
        sa.Column("reject_reason", sa.String(255), nullable=True),
        sa.Column("strategy_tag", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("prediction_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_futures_sim_orders_account_id", "futures_sim_orders", ["account_id"])
    op.create_index("ix_futures_sim_orders_position_id", "futures_sim_orders", ["position_id"])
    op.create_index(
        "ix_futures_sim_orders_client_order_id",
        "futures_sim_orders",
        ["client_order_id"],
        unique=True,
    )
    op.create_index("ix_futures_sim_orders_symbol", "futures_sim_orders", ["symbol"])
    op.create_index("ix_futures_sim_orders_status", "futures_sim_orders", ["status"])
    op.create_index("ix_futures_sim_orders_created_at", "futures_sim_orders", ["created_at"])

    op.create_table(
        "futures_sim_trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("futures_sim_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position_id",
            sa.Integer(),
            sa.ForeignKey("futures_sim_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("futures_sim_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(5), nullable=False),
        sa.Column("leverage", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(24, 8), nullable=False),
        sa.Column("fees", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("funding", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("net_pnl", sa.Numeric(24, 8), nullable=False),
        sa.Column("roi_pct", sa.Numeric(10, 4), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("exit_reason", sa.String(20), nullable=False),
        sa.Column("strategy_tag", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("prediction_id", sa.Integer(), nullable=True),
        sa.Column("strategy_label", sa.String(30), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("self_assessment_tags", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_futures_sim_trades_account_id", "futures_sim_trades", ["account_id"])
    op.create_index("ix_futures_sim_trades_position_id", "futures_sim_trades", ["position_id"])
    op.create_index("ix_futures_sim_trades_symbol", "futures_sim_trades", ["symbol"])
    op.create_index("ix_futures_sim_trades_closed_at", "futures_sim_trades", ["closed_at"])

    op.create_table(
        "futures_sim_ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("futures_sim_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("balance_after", sa.Numeric(24, 8), nullable=False),
        sa.Column("reference_type", sa.String(20), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_futures_sim_ledger_entries_account_id", "futures_sim_ledger_entries", ["account_id"]
    )
    op.create_index(
        "ix_futures_sim_ledger_entries_event_type", "futures_sim_ledger_entries", ["event_type"]
    )
    op.create_index(
        "ix_futures_sim_ledger_entries_created_at", "futures_sim_ledger_entries", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("futures_sim_ledger_entries")
    op.drop_table("futures_sim_trades")
    op.drop_table("futures_sim_orders")
    op.drop_table("futures_sim_positions")
    op.drop_table("futures_sim_accounts")

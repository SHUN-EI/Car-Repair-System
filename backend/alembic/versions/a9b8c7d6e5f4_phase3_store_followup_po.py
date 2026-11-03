"""phase3 store scope, follow-up reminders, purchase orders

Revision ID: a9b8c7d6e5f4
Revises: f8a9b0c1d2e3
Create Date: 2026-11-03 14:20:00.000000

只追加列和表：用户所属门店、备件归属门店、门店结存、库存流水、采购单、回访提醒。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("store_id", sa.Integer(), nullable=True, comment="所属门店，空表示未绑定"))
    op.create_foreign_key("fk_users_store_id", "users", "stores", ["store_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_users_store_id", "users", ["store_id"])

    op.add_column("spare_parts", sa.Column("store_id", sa.Integer(), nullable=True, comment="归属门店，空表示未分店"))
    op.create_foreign_key("fk_spare_parts_store_id", "spare_parts", "stores", ["store_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_spare_parts_store_id", "spare_parts", ["store_id"])

    op.create_index("ix_work_orders_store_id", "work_orders", ["store_id"])
    op.create_index("ix_quotes_store_id", "quotes", ["store_id"])

    op.create_table(
        "store_part_stocks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False, comment="门店"),
        sa.Column("spare_part_id", sa.Integer(), nullable=False, comment="备件"),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0", comment="本店结存"),
        sa.ForeignKeyConstraint(["spare_part_id"], ["spare_parts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_id", "spare_part_id", name="uq_store_part_stock"),
    )
    op.create_index("ix_store_part_stocks_store_id", "store_part_stocks", ["store_id"])
    op.create_index("ix_store_part_stocks_spare_part_id", "store_part_stocks", ["spare_part_id"])
    op.create_index("ix_store_part_stocks_id", "store_part_stocks", ["id"])

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=True),
        sa.Column("spare_part_id", sa.Integer(), nullable=True),
        sa.Column("part_code", sa.String(length=50), nullable=False),
        sa.Column("qty_delta", sa.Integer(), nullable=False, comment="正数入库，负数出库"),
        sa.Column("movement_type", sa.String(length=30), nullable=False, comment="PO_RECEIVE/IMPORT/ISSUE"),
        sa.Column("ref_type", sa.String(length=30), nullable=True),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.Column("balance_after", sa.Integer(), nullable=True, comment="变动后的总库存"),
        sa.Column("store_balance_after", sa.Integer(), nullable=True, comment="变动后的本店结存"),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["spare_part_id"], ["spare_parts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stock_movements_store_id", "stock_movements", ["store_id"])
    op.create_index("ix_stock_movements_spare_part_id", "stock_movements", ["spare_part_id"])
    op.create_index("ix_stock_movements_id", "stock_movements", ["id"])

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("po_no", sa.String(length=40), nullable=False, comment="采购单号"),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("supplier", sa.String(length=200), nullable=True, comment="供应商"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ORDERED", comment="ORDERED/PARTIAL/RECEIVED/CANCELLED"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("po_no"),
    )
    op.create_index("ix_purchase_orders_po_no", "purchase_orders", ["po_no"])
    op.create_index("ix_purchase_orders_store_id", "purchase_orders", ["store_id"])
    op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"])
    op.create_index("ix_purchase_orders_id", "purchase_orders", ["id"])

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("spare_part_id", sa.Integer(), nullable=True),
        sa.Column("part_code", sa.String(length=50), nullable=False, comment="备件编码"),
        sa.Column("part_name", sa.String(length=200), nullable=False, comment="备件名称"),
        sa.Column("qty_ordered", sa.Integer(), nullable=False),
        sa.Column("qty_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Float(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["spare_part_id"], ["spare_parts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_order_lines_purchase_order_id", "purchase_order_lines", ["purchase_order_id"])
    op.create_index("ix_purchase_order_lines_id", "purchase_order_lines", ["id"])

    op.create_table(
        "follow_up_reminders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=True),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False, comment="REVISIT 回访 / RATING 评价"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="SCHEDULED", comment="SCHEDULED/SENT/CANCELLED/SKIPPED"),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False, comment="计划发送时间"),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("channel_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="短信/钉钉/站内的发送结果"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_follow_up_reminders_store_id", "follow_up_reminders", ["store_id"])
    op.create_index("ix_follow_up_reminders_work_order_id", "follow_up_reminders", ["work_order_id"])
    op.create_index("ix_follow_up_reminders_status", "follow_up_reminders", ["status"])
    op.create_index("ix_follow_up_reminders_scheduled_at", "follow_up_reminders", ["scheduled_at"])
    op.create_index("ix_follow_up_reminders_id", "follow_up_reminders", ["id"])


def downgrade() -> None:
    op.drop_index("ix_follow_up_reminders_id", table_name="follow_up_reminders")
    op.drop_index("ix_follow_up_reminders_scheduled_at", table_name="follow_up_reminders")
    op.drop_index("ix_follow_up_reminders_status", table_name="follow_up_reminders")
    op.drop_index("ix_follow_up_reminders_work_order_id", table_name="follow_up_reminders")
    op.drop_index("ix_follow_up_reminders_store_id", table_name="follow_up_reminders")
    op.drop_table("follow_up_reminders")

    op.drop_index("ix_purchase_order_lines_id", table_name="purchase_order_lines")
    op.drop_index("ix_purchase_order_lines_purchase_order_id", table_name="purchase_order_lines")
    op.drop_table("purchase_order_lines")

    op.drop_index("ix_purchase_orders_id", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_status", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_store_id", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_po_no", table_name="purchase_orders")
    op.drop_table("purchase_orders")

    op.drop_index("ix_stock_movements_id", table_name="stock_movements")
    op.drop_index("ix_stock_movements_spare_part_id", table_name="stock_movements")
    op.drop_index("ix_stock_movements_store_id", table_name="stock_movements")
    op.drop_table("stock_movements")

    op.drop_index("ix_store_part_stocks_id", table_name="store_part_stocks")
    op.drop_index("ix_store_part_stocks_spare_part_id", table_name="store_part_stocks")
    op.drop_index("ix_store_part_stocks_store_id", table_name="store_part_stocks")
    op.drop_table("store_part_stocks")

    op.drop_index("ix_quotes_store_id", table_name="quotes")
    op.drop_index("ix_work_orders_store_id", table_name="work_orders")

    op.drop_index("ix_spare_parts_store_id", table_name="spare_parts")
    op.drop_constraint("fk_spare_parts_store_id", "spare_parts", type_="foreignkey")
    op.drop_column("spare_parts", "store_id")

    op.drop_index("ix_users_store_id", table_name="users")
    op.drop_constraint("fk_users_store_id", "users", type_="foreignkey")
    op.drop_column("users", "store_id")

"""phase2 fitment, service packages, quotes, payment stub

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-11-03 12:10:00.000000

只追加列和表：备件适配、保养套餐/项目、报价单、支付意向占位。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "spare_parts",
        sa.Column("fitment", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="适配规则"),
    )

    op.create_table(
        "service_packages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False, comment="套餐编码"),
        sa.Column("name", sa.String(length=200), nullable=False, comment="套餐名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="说明"),
        sa.Column("brand", sa.String(length=50), nullable=True, comment="适用品牌，空为不限"),
        sa.Column("series", sa.String(length=80), nullable=True, comment="适用车系，空为不限"),
        sa.Column("mileage_from", sa.Integer(), nullable=True, comment="里程下限 km"),
        sa.Column("mileage_to", sa.Integer(), nullable=True, comment="里程上限 km"),
        sa.Column("symptom_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="症状关键词"),
        sa.Column("list_price", sa.Float(), nullable=False, server_default="0", comment="套餐价"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"), comment="是否在售"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_service_packages_code", "service_packages", ["code"])
    op.create_index("ix_service_packages_id", "service_packages", ["id"])

    op.create_table(
        "service_skus",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False, comment="项目编码"),
        sa.Column("name", sa.String(length=200), nullable=False, comment="项目名称"),
        sa.Column("labor_minutes", sa.Integer(), nullable=False, server_default="0", comment="工时分钟"),
        sa.Column("base_price", sa.Float(), nullable=False, server_default="0", comment="基础价"),
        sa.Column("package_id", sa.Integer(), nullable=True, comment="所属套餐"),
        sa.Column("category", sa.String(length=50), nullable=True, comment="类别"),
        sa.Column("symptom_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="症状关键词"),
        sa.Column("brand", sa.String(length=50), nullable=True, comment="适用品牌"),
        sa.Column("series", sa.String(length=80), nullable=True, comment="适用车系"),
        sa.Column("mileage_from", sa.Integer(), nullable=True),
        sa.Column("mileage_to", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"), comment="是否在售"),
        sa.ForeignKeyConstraint(["package_id"], ["service_packages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_service_skus_code", "service_skus", ["code"])
    op.create_index("ix_service_skus_package_id", "service_skus", ["package_id"])
    op.create_index("ix_service_skus_id", "service_skus", ["id"])

    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("quote_no", sa.String(length=50), nullable=False, comment="报价单号"),
        sa.Column("work_order_id", sa.Integer(), nullable=True),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("store_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="DRAFT"),
        sa.Column("customer_confirm", sa.Boolean(), nullable=False, server_default=sa.text("false"), comment="车主是否已确认"),
        sa.Column("total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("mileage", sa.Integer(), nullable=True),
        sa.Column("symptoms", sa.Text(), nullable=True),
        sa.Column("consult_text", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("staff_confirmed_by", sa.Integer(), nullable=True),
        sa.Column("customer_confirmed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["staff_confirmed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quote_no"),
    )
    op.create_index("ix_quotes_quote_no", "quotes", ["quote_no"])
    op.create_index("ix_quotes_work_order_id", "quotes", ["work_order_id"])
    op.create_index("ix_quotes_vehicle_id", "quotes", ["vehicle_id"])
    op.create_index("ix_quotes_customer_id", "quotes", ["customer_id"])
    op.create_index("ix_quotes_status", "quotes", ["status"])
    op.create_index("ix_quotes_id", "quotes", ["id"])

    op.create_table(
        "quote_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("quote_id", sa.Integer(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("line_type", sa.String(length=20), nullable=False, server_default="LABOR"),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("qty", sa.Float(), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=30), nullable=True),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quote_lines_quote_id", "quote_lines", ["quote_id"])
    op.create_index("ix_quote_lines_id", "quote_lines", ["id"])

    op.create_table(
        "payment_intents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("intent_no", sa.String(length=40), nullable=False, comment="意向单号"),
        sa.Column("quote_id", sa.Integer(), nullable=True),
        sa.Column("work_order_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="STUB"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="CREATED"),
        sa.Column("note", sa.String(length=200), nullable=False, server_default="占位订单，未接入清算"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("intent_no"),
    )
    op.create_index("ix_payment_intents_intent_no", "payment_intents", ["intent_no"])
    op.create_index("ix_payment_intents_quote_id", "payment_intents", ["quote_id"])
    op.create_index("ix_payment_intents_work_order_id", "payment_intents", ["work_order_id"])
    op.create_index("ix_payment_intents_status", "payment_intents", ["status"])
    op.create_index("ix_payment_intents_id", "payment_intents", ["id"])


def downgrade() -> None:
    op.drop_index("ix_payment_intents_id", table_name="payment_intents")
    op.drop_index("ix_payment_intents_status", table_name="payment_intents")
    op.drop_index("ix_payment_intents_work_order_id", table_name="payment_intents")
    op.drop_index("ix_payment_intents_quote_id", table_name="payment_intents")
    op.drop_index("ix_payment_intents_intent_no", table_name="payment_intents")
    op.drop_table("payment_intents")

    op.drop_index("ix_quote_lines_id", table_name="quote_lines")
    op.drop_index("ix_quote_lines_quote_id", table_name="quote_lines")
    op.drop_table("quote_lines")

    op.drop_index("ix_quotes_id", table_name="quotes")
    op.drop_index("ix_quotes_status", table_name="quotes")
    op.drop_index("ix_quotes_customer_id", table_name="quotes")
    op.drop_index("ix_quotes_vehicle_id", table_name="quotes")
    op.drop_index("ix_quotes_work_order_id", table_name="quotes")
    op.drop_index("ix_quotes_quote_no", table_name="quotes")
    op.drop_table("quotes")

    op.drop_index("ix_service_skus_id", table_name="service_skus")
    op.drop_index("ix_service_skus_package_id", table_name="service_skus")
    op.drop_index("ix_service_skus_code", table_name="service_skus")
    op.drop_table("service_skus")

    op.drop_index("ix_service_packages_id", table_name="service_packages")
    op.drop_index("ix_service_packages_code", table_name="service_packages")
    op.drop_table("service_packages")

    op.drop_column("spare_parts", "fitment")

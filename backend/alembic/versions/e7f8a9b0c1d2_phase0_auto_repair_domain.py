"""phase0 auto repair domain skeleton

Revision ID: e7f8a9b0c1d2
Revises: c3d4e5f6a7b9
Create Date: 2026-11-03 10:40:00.000000

汽修 Phase 0：客户 / 门店 / 工位 / 车辆 / 预约 / 配件目录，
以及工单上的可空关联列。工单枚举只追加值，不改已有值。

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "c3d4e5f6a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_STATUS_VALUES = (
    "INTAKE",
    "DIAGNOSING",
    "QUOTING",
    "QC",
    "CLOSED",
    "CANCELLED",
)


def _add_status_values() -> None:
    # ADD VALUE 不能在同一事务里被后续语句使用；这里只追加，不写入新值。
    # PostgreSQL 12+ 允许在事务中 ADD VALUE，但 autocommit 更稳妥。
    with op.get_context().autocommit_block():
        for value in _NEW_STATUS_VALUES:
            op.execute(sa.text(f"ALTER TYPE workorderstatus ADD VALUE IF NOT EXISTS '{value}'"))


def upgrade() -> None:
    _add_status_values()

    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False, comment="客户姓名"),
        sa.Column("phone", sa.String(length=20), nullable=True, comment="手机号"),
        sa.Column("email", sa.String(length=200), nullable=True, comment="邮箱"),
        sa.Column("id_no", sa.String(length=30), nullable=True, comment="证件号占位"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        sa.Column("user_id", sa.Integer(), nullable=True, comment="可选关联系统用户"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customers_phone", "customers", ["phone"])
    op.create_index("ix_customers_id", "customers", ["id"])

    op.create_table(
        "stores",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False, comment="门店编码"),
        sa.Column("name", sa.String(length=200), nullable=False, comment="门店名称"),
        sa.Column("address", sa.String(length=300), nullable=True, comment="地址"),
        sa.Column("phone", sa.String(length=20), nullable=True, comment="联系电话"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"), comment="是否营业"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_stores_code", "stores", ["code"])
    op.create_index("ix_stores_id", "stores", ["id"])

    op.create_table(
        "part_skus",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False, comment="SKU 编码"),
        sa.Column("name", sa.String(length=200), nullable=False, comment="配件名称"),
        sa.Column("brand", sa.String(length=100), nullable=True, comment="品牌"),
        sa.Column("unit", sa.String(length=20), nullable=True, comment="单位"),
        sa.Column("list_price", sa.Float(), nullable=True, comment="指导价占位"),
        sa.Column("cost_price", sa.Float(), nullable=True, comment="成本价占位"),
        sa.Column("specification", sa.String(length=200), nullable=True, comment="规格"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"), comment="是否在售"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_part_skus_code", "part_skus", ["code"])
    op.create_index("ix_part_skus_id", "part_skus", ["id"])

    op.create_table(
        "bays",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False, comment="所属门店"),
        sa.Column("code", sa.String(length=50), nullable=False, comment="工位编码"),
        sa.Column("name", sa.String(length=100), nullable=False, comment="工位名称"),
        sa.Column("bay_type", sa.String(length=30), nullable=True, comment="工位类型"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"), comment="是否可用"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_id", "code", name="uq_bays_store_code"),
    )
    op.create_index("ix_bays_store_id", "bays", ["store_id"])
    op.create_index("ix_bays_id", "bays", ["id"])

    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("plate", sa.String(length=20), nullable=False, comment="车牌号"),
        sa.Column("vin", sa.String(length=17), nullable=True, comment="车架号 VIN"),
        sa.Column("make", sa.String(length=50), nullable=True, comment="品牌"),
        sa.Column("model", sa.String(length=80), nullable=True, comment="车型"),
        sa.Column("year", sa.Integer(), nullable=True, comment="年款"),
        sa.Column("owner_id", sa.Integer(), nullable=True, comment="车主，关联客户"),
        sa.ForeignKeyConstraint(["owner_id"], ["customers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plate"),
        sa.UniqueConstraint("vin"),
    )
    op.create_index("ix_vehicles_plate", "vehicles", ["plate"])
    op.create_index("ix_vehicles_vin", "vehicles", ["vin"])
    op.create_index("ix_vehicles_owner_id", "vehicles", ["owner_id"])
    op.create_index("ix_vehicles_id", "vehicles", ["id"])

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False, comment="预约门店"),
        sa.Column("bay_id", sa.Integer(), nullable=True, comment="预约工位"),
        sa.Column("customer_id", sa.Integer(), nullable=True, comment="客户"),
        sa.Column("vehicle_id", sa.Integer(), nullable=True, comment="车辆"),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False, comment="预约到店时间"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING", comment="预约状态"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bay_id"], ["bays.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_appointments_store_id", "appointments", ["store_id"])
    op.create_index("ix_appointments_customer_id", "appointments", ["customer_id"])
    op.create_index("ix_appointments_vehicle_id", "appointments", ["vehicle_id"])
    op.create_index("ix_appointments_id", "appointments", ["id"])

    op.add_column("work_orders", sa.Column("vehicle_id", sa.Integer(), nullable=True, comment="关联车辆"))
    op.add_column("work_orders", sa.Column("customer_id", sa.Integer(), nullable=True, comment="关联客户"))
    op.add_column("work_orders", sa.Column("store_id", sa.Integer(), nullable=True, comment="服务门店"))
    op.add_column("work_orders", sa.Column("bay_id", sa.Integer(), nullable=True, comment="占用工位"))
    op.add_column("work_orders", sa.Column("appointment_id", sa.Integer(), nullable=True, comment="来源预约"))
    op.create_foreign_key("fk_work_orders_vehicle_id", "work_orders", "vehicles", ["vehicle_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_work_orders_customer_id", "work_orders", "customers", ["customer_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_work_orders_store_id", "work_orders", "stores", ["store_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_work_orders_bay_id", "work_orders", "bays", ["bay_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_work_orders_appointment_id", "work_orders", "appointments", ["appointment_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_work_orders_vehicle_id", "work_orders", ["vehicle_id"])
    op.create_index("ix_work_orders_customer_id", "work_orders", ["customer_id"])

    op.add_column("spare_parts", sa.Column("sku_id", sa.Integer(), nullable=True, comment="关联配件目录 SKU"))
    op.create_foreign_key("fk_spare_parts_sku_id", "spare_parts", "part_skus", ["sku_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_spare_parts_sku_id", "spare_parts", ["sku_id"])


def downgrade() -> None:
    op.drop_index("ix_spare_parts_sku_id", table_name="spare_parts")
    op.drop_constraint("fk_spare_parts_sku_id", "spare_parts", type_="foreignkey")
    op.drop_column("spare_parts", "sku_id")

    op.drop_index("ix_work_orders_customer_id", table_name="work_orders")
    op.drop_index("ix_work_orders_vehicle_id", table_name="work_orders")
    op.drop_constraint("fk_work_orders_appointment_id", "work_orders", type_="foreignkey")
    op.drop_constraint("fk_work_orders_bay_id", "work_orders", type_="foreignkey")
    op.drop_constraint("fk_work_orders_store_id", "work_orders", type_="foreignkey")
    op.drop_constraint("fk_work_orders_customer_id", "work_orders", type_="foreignkey")
    op.drop_constraint("fk_work_orders_vehicle_id", "work_orders", type_="foreignkey")
    op.drop_column("work_orders", "appointment_id")
    op.drop_column("work_orders", "bay_id")
    op.drop_column("work_orders", "store_id")
    op.drop_column("work_orders", "customer_id")
    op.drop_column("work_orders", "vehicle_id")

    op.drop_table("appointments")
    op.drop_table("vehicles")
    op.drop_table("bays")
    op.drop_table("part_skus")
    op.drop_table("stores")
    op.drop_table("customers")
    # Postgres 不能直接从枚举类型删值，新状态值保留。

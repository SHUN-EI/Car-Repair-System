"""add_workorder_status_values

Revision ID: b7c4d8e1f2a3
Revises: a43b0de36259
Create Date: 2026-07-27 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c4d8e1f2a3'
down_revision: Union[str, None] = 'a43b0de36259'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 这些值里有的在建表时已经在枚举里。重复 ADD VALUE 会让事务失败，
    # Python 的 try/except 不能把 PostgreSQL 事务恢复回来。
    new_values = ['ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'ARCHIVED', 'STANDARDIZED', 'CLASSIFIED']
    with op.get_context().autocommit_block():
        for val in new_values:
            op.execute(sa.text(f"ALTER TYPE workorderstatus ADD VALUE IF NOT EXISTS '{val}'"))


def downgrade() -> None:
    pass

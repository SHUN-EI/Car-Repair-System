"""空库迁移：users.employee_id 还不存在时，2a5022bf6eca 应补列而不是直接改注释。"""
import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def _load_revision():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "2a5022bf6eca_add_device_monitor_fields.py"
    spec = importlib.util.spec_from_file_location("rev_2a5022bf6eca", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_employee_id_is_added_when_missing():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50))"))
        conn.execute(text(
            "CREATE TABLE devices (id INTEGER PRIMARY KEY)"
        ))
        conn.execute(text("CREATE TABLE knowledge_items (id INTEGER PRIMARY KEY, fault_code TEXT)"))
        conn.execute(text("CREATE TABLE work_orders (id INTEGER PRIMARY KEY, fault_code TEXT, fault_category VARCHAR(100), fault_phenomenon_type VARCHAR(200), fault_phenomenon TEXT, attachments TEXT, root_cause_category VARCHAR(100), root_cause_type VARCHAR(200), root_cause TEXT, solution_ref_knowledge_id INTEGER, repair_result VARCHAR(20), follow_up_plan TEXT, work_hours FLOAT, created_by INTEGER)"))
    revision = _load_revision()
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        revision.op = Operations(ctx)
        # 只跑补列逻辑，不跑整段设备字段升级（那些列依赖 PostgreSQL JSONB）。
        revision._ensure_users_employee_id()

    columns = {col["name"] for col in inspect(engine).get_columns("users")}
    assert "employee_id" in columns

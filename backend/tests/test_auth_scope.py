"""鉴权与门店范围。用内存 SQLite，不连外网，也不调用真实 LLM。"""
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DEBUG", "true")


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kwargs):
    return "JSON"


from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
import app.models  # noqa: E402,F401
from app.models.spare_part import SparePart  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.work_order import WorkOrder, WorkOrderStatus  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    admin = User(
        username="admin_test",
        password_hash="x",
        real_name="管理员",
        role="ADMIN",
        is_active=True,
    )
    tech = User(
        username="tech_store1",
        password_hash="x",
        real_name="技师",
        role="TECHNICIAN",
        store_id=1,
        is_active=True,
    )
    db.add_all([admin, tech])
    db.flush()
    db.add(WorkOrder(
        work_order_no="WO-SCOPE-2",
        fault_description="他店故障",
        status=WorkOrderStatus.IN_PROGRESS,
        store_id=2,
    ))
    db.add(SparePart(
        part_code="SP-OTHER",
        part_name="他店刹车片",
        stock_quantity=3,
        safety_stock=1,
        store_id=2,
    ))
    db.commit()
    tokens = {
        "admin": create_access_token(admin.id, admin.username),
        "tech": create_access_token(tech.id, tech.username),
    }

    def _override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    from fastapi.testclient import TestClient
    with TestClient(app) as test_client:
        test_client.tokens = tokens
        yield test_client
    app.dependency_overrides.clear()
    db.close()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestUnauthenticatedWrites:
    def test_create_user_requires_login(self, client):
        response = client.post("/api/v1/users/", json={
            "username": "new_user",
            "password": "secret12",
            "real_name": "新人",
        })
        assert response.status_code == 401

    def test_create_knowledge_requires_login(self, client):
        response = client.post("/api/v1/knowledge/", json={
            "title": "未登录知识",
            "content": "不该写入",
        })
        assert response.status_code == 401

    def test_complete_work_order_requires_login(self, client):
        response = client.post("/api/v1/work-orders/1/complete")
        assert response.status_code == 401


class TestRoleAndStoreScope:
    def test_technician_cannot_create_user(self, client):
        response = client.post(
            "/api/v1/users/",
            json={"username": "another", "password": "secret12", "real_name": "另一个"},
            headers=_auth(client.tokens["tech"]),
        )
        assert response.status_code == 403

    def test_technician_cannot_create_store(self, client):
        response = client.post(
            "/api/v1/stores/",
            json={"code": "S-NEW", "name": "新店"},
            headers=_auth(client.tokens["tech"]),
        )
        assert response.status_code == 403

    def test_technician_cannot_trigger_stock_alerts(self, client):
        response = client.post(
            "/api/v1/spare-parts/check-alerts",
            headers=_auth(client.tokens["tech"]),
        )
        assert response.status_code == 403

    def test_technician_cannot_update_other_store_part(self, client):
        response = client.put(
            "/api/v1/spare-parts/1",
            json={"part_name": "被改名"},
            headers=_auth(client.tokens["tech"]),
        )
        assert response.status_code == 403

    def test_technician_cannot_complete_other_store_order(self, client):
        response = client.post(
            "/api/v1/work-orders/1/complete",
            headers=_auth(client.tokens["tech"]),
        )
        assert response.status_code == 403

    def test_device_sync_rejects_missing_key(self, client):
        response = client.post("/api/v1/devices/monitor/sync-status", json=[])
        assert response.status_code == 503

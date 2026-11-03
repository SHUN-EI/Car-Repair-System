"""Phase 0：汽修状态机、预约状态、模型可编译、迁移接在当前 head 之后。"""
import os
import sys

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain.appointment_status import (  # noqa: E402
    is_allowed_appointment_transition,
    appointment_targets,
)
from app.domain.work_order_status import (  # noqa: E402
    AUTO_REPAIR_PATH,
    VALID_TRANSITIONS,
    allowed_transitions,
    is_allowed_transition,
    status_machine_payload,
)
from app.models.appointment import Appointment  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.part_sku import PartSku  # noqa: E402
from app.models.spare_part import SparePart  # noqa: E402
from app.models.store import Bay, Store  # noqa: E402
from app.models.vehicle import Vehicle  # noqa: E402
from app.models.work_order import WorkOrder, WorkOrderStatus  # noqa: E402


# 改动前工业车道必须仍然合法。只断言「原边还在」，不禁止新增出边。
_INDUSTRIAL_EDGES = {
    "DRAFT": {"SUBMITTED", "ASSIGNED"},
    "SUBMITTED": {"ASSIGNED", "REJECTED"},
    "ASSIGNED": {"ACCEPTED", "REJECTED"},
    "ACCEPTED": {"ARRIVED", "REJECTED"},
    "ARRIVED": {"INSPECTING", "REJECTED"},
    "INSPECTING": {"IN_PROGRESS", "REJECTED"},
    "IN_PROGRESS": {"ARCHIVING", "REJECTED"},
    "ARCHIVING": {"ARCHIVED"},
}


class TestWorkOrderStatusMachine:
    def test_enum_matches_transition_table(self):
        values = {item.value for item in WorkOrderStatus}
        assert values == set(VALID_TRANSITIONS)

    def test_industrial_edges_kept(self):
        for src, required in _INDUSTRIAL_EDGES.items():
            assert required <= set(allowed_transitions(src))

    def test_auto_repair_path_is_guarded(self):
        for src, dst in zip(AUTO_REPAIR_PATH, AUTO_REPAIR_PATH[1:]):
            assert is_allowed_transition(src, dst), f"{src} → {dst}"
        assert "CANCELLED" in allowed_transitions("QUOTING")
        assert allowed_transitions("CLOSED") == []
        assert allowed_transitions("CANCELLED") == []
        assert "QC" not in allowed_transitions("DRAFT")
        assert "INTAKE" not in allowed_transitions("IN_PROGRESS")

    def test_completed_can_close_but_not_reopen(self):
        assert allowed_transitions("COMPLETED") == ["CLOSED"]
        assert not is_allowed_transition("CLOSED", "INTAKE")
        assert not is_allowed_transition("ARCHIVED", "CLOSED")

    def test_payload_exposes_status_and_transitions(self):
        payload = status_machine_payload()
        by_value = {row["value"]: row for row in payload["statuses"]}
        assert by_value["INTAKE"]["label"] == "接车"
        assert by_value["INTAKE"]["allowed_transitions"] == ["DIAGNOSING", "CANCELLED"]
        assert payload["auto_repair_path"][0] == "DRAFT"
        assert payload["auto_repair_path"][-1] == "CLOSED"
        assert payload["transitions"]["IN_PROGRESS"] == allowed_transitions("IN_PROGRESS")


class TestAppointmentStatus:
    def test_confirm_then_finish(self):
        assert is_allowed_appointment_transition("PENDING", "CONFIRMED")
        assert is_allowed_appointment_transition("CONFIRMED", "COMPLETED")
        assert not is_allowed_appointment_transition("PENDING", "COMPLETED")
        assert appointment_targets("CANCELLED") == []
        assert is_allowed_appointment_transition("PENDING", "PENDING")


class TestPhase0Models:
    @pytest.mark.parametrize("model,table,column", [
        (Vehicle, "vehicles", "plate"),
        (Vehicle, "vehicles", "vin"),
        (Vehicle, "vehicles", "owner_id"),
        (Customer, "customers", "name"),
        (Store, "stores", "code"),
        (Bay, "bays", "store_id"),
        (Appointment, "appointments", "scheduled_at"),
        (PartSku, "part_skus", "list_price"),
    ])
    def test_table_compiles(self, model, table, column):
        sql = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert table in sql
        assert column in sql

    def test_work_order_and_spare_part_links(self):
        assert "vehicle_id" in WorkOrder.__table__.c
        assert "appointment_id" in WorkOrder.__table__.c
        assert "sku_id" in SparePart.__table__.c


def test_migration_is_single_head():
    versions = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic", "versions")
    revisions = {}
    parents = set()
    for name in os.listdir(versions):
        if not name.endswith(".py"):
            continue
        text = open(os.path.join(versions, name), encoding="utf-8").read()
        rev = None
        down = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("revision") and "=" in stripped and rev is None:
                rev = stripped.split("=", 1)[1].strip().strip('"').strip("'")
            if stripped.startswith("down_revision") and "=" in stripped and down is None:
                raw = stripped.split("=", 1)[1].strip()
                if raw in ("None",):
                    down = None
                else:
                    down = raw.strip('"').strip("'")
        if rev:
            revisions[rev] = down
            if down:
                parents.add(down)
    assert "e7f8a9b0c1d2" in revisions
    assert revisions["e7f8a9b0c1d2"] == "c3d4e5f6a7b9"
    assert revisions["f8a9b0c1d2e3"] == "e7f8a9b0c1d2"
    assert revisions["a9b8c7d6e5f4"] == "f8a9b0c1d2e3"
    heads = [rev for rev in revisions if rev not in parents]
    assert heads == ["a9b8c7d6e5f4"]


def test_domain_routers_import():
    from app.api.vehicles import router as vehicles_router
    from app.api.service_domain import (
        appointments_router,
        bays_router,
        customers_router,
        part_skus_router,
        stores_router,
    )

    paths = {route.path for route in vehicles_router.routes}
    assert "/" in paths
    assert "/{vehicle_id}" in paths
    for router in (customers_router, stores_router, bays_router, appointments_router, part_skus_router):
        assert any(getattr(route, "methods", None) and "GET" in route.methods for route in router.routes)
        assert any(getattr(route, "methods", None) and "POST" in route.methods for route in router.routes)

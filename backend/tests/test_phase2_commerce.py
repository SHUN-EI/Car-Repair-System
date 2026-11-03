"""Phase 2：适配、套餐推荐、报价草案、通知开关、支付占位。不连数据库。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.payments import router as payments_router  # noqa: E402
from app.api.quotes import router as quotes_router  # noqa: E402
from app.api.service_catalog import packages_router, skus_router  # noqa: E402
from app.api.spare_parts import router as spare_router  # noqa: E402
from app.domain.fitment import (  # noqa: E402
    looks_like_fitment_question,
    normalize_fitment,
    parse_fitment_question,
    part_matches,
    rule_matches,
)
from app.domain.owner_notify import owner_status_text  # noqa: E402
from app.domain.payment_status import PAYMENT_STATUSES  # noqa: E402
from app.domain.quote_lines import build_quote_lines, parse_consult_items  # noqa: E402
from app.domain.quote_status import can_transition  # noqa: E402
from app.domain.service_recommend import rank_offers  # noqa: E402
from app.mcp.tools import TOOLS  # noqa: E402


class TestFitment:
    def test_vehicle_matches_brand_year_and_engine(self):
        rules = [{
            "brand": "大众",
            "series": "速腾",
            "year_from": 2016,
            "year_to": 2020,
            "engine": "1.4T",
        }]
        assert part_matches(rules, brand="大众", series="速腾", year=2018, engine="1.4t")
        assert not part_matches(rules, brand="丰田", series="速腾", year=2018, engine="1.4T")
        assert not part_matches(rules, brand="大众", series="速腾", year=2022, engine="1.4T")
        assert not part_matches(rules, brand="大众", series="速腾", year=2018, engine="2.0T")
        assert not part_matches(rules, brand="大众", series="速腾", year=None, engine="1.4T")

    def test_blank_rule_is_universal_and_missing_fitment_is_not(self):
        assert part_matches([{}], brand="任意", series="", year=None, engine="")
        assert not part_matches(None, brand="大众", series="速腾", year=2018, engine="")
        assert not part_matches([], brand="大众", series="速腾", year=2018, engine="")

    def test_year_order_is_rejected(self):
        try:
            normalize_fitment([{"year_from": 2020, "year_to": 2016}])
        except ValueError as exc:
            assert "年款" in str(exc)
        else:
            raise AssertionError("年款起大于年款止时应拒绝")

    def test_empty_engine_does_not_exclude(self):
        assert rule_matches({"brand": "大众", "engine": None}, brand="大众", series="速腾", year=2018, engine="")

    def test_question_parser_keeps_stock_questions_on_the_old_path(self):
        assert not looks_like_fitment_question("查一下保险丝的库存")
        parsed = parse_fitment_question("大众的速腾 2018 1.4T 适配刹车片")
        assert parsed["brand"] == "大众"
        assert parsed["series"] == "速腾"
        assert parsed["year"] == 2018
        assert parsed["engine"] == "1.4T"
        assert parsed["keyword"] == "刹车片"


class TestPackages:
    def test_mileage_and_brand_filter_before_symptom_rank(self):
        rows = [
            {"id": 1, "code": "OIL", "name": "小保养", "brand": "大众", "series": "速腾",
             "mileage_from": 8000, "mileage_to": 12000, "symptom_keywords": ["机油"], "is_active": True, "list_price": 299},
            {"id": 2, "code": "BRAKE", "name": "刹车检查", "brand": "大众", "series": "速腾",
             "mileage_from": 8000, "mileage_to": 40000, "symptom_keywords": ["刹车", "异响"], "is_active": True, "list_price": 80},
            {"id": 3, "code": "TOYOTA", "name": "丰田保养", "brand": "丰田", "series": None,
             "mileage_from": None, "mileage_to": None, "symptom_keywords": ["刹车"], "is_active": True, "list_price": 100},
        ]
        ranked = rank_offers(rows, brand="大众", series="速腾", mileage=10000, symptoms="刹车有异响")
        assert [row["code"] for row in ranked] == ["BRAKE", "OIL"]
        assert ranked[0]["symptom_hits"] == 2
        assert "症状命中" in ranked[0]["reason"]
        outside = rank_offers(rows, brand="大众", series="速腾", mileage=30000, symptoms="")
        assert [row["code"] for row in outside] == ["BRAKE"]


class TestQuoteDraft:
    def test_consult_without_items_does_not_invent_lines(self):
        text = "【症状】刹车异响\n【建议项目】知识库未给出可执行项目\n【是否预约】建议预约到店"
        assert parse_consult_items(text) == []
        lines, note = build_quote_lines(consult_text=text, include_used_parts=False)
        assert lines == []
        assert "没有可报价" in note

    def test_parts_price_and_package_line(self):
        lines, note = build_quote_lines(
            used_parts=[{"name": "前刹车片", "code": "BP-1", "qty": 2}],
            part_prices={"BP-1": 180},
            consult_text="【建议项目】更换机油\n【是否预约】可以",
            service_catalog=[{"id": 9, "code": "OIL", "name": "更换机油", "base_price": 260, "package_id": 3}],
            packages=[{"id": 3, "code": "PKG", "name": "小保养", "list_price": 399}],
            include_packages=True,
        )
        assert lines[0]["line_type"] == "PART"
        assert lines[0]["amount"] == 360
        assert lines[1]["name"] == "更换机油"
        assert lines[1]["unit_price"] == 260
        assert lines[2]["line_type"] == "PACKAGE"
        assert lines[2]["amount"] == 399
        assert "小保养含" in note

    def test_staff_confirm_before_customer(self):
        assert can_transition("DRAFT", "STAFF_CONFIRMED")
        assert not can_transition("DRAFT", "CUSTOMER_CONFIRMED")
        assert can_transition("STAFF_CONFIRMED", "CUSTOMER_CONFIRMED")
        assert not can_transition("CUSTOMER_CONFIRMED", "STAFF_CONFIRMED")


class TestNotifyAndPayment:
    def test_owner_text_mentions_status(self):
        text = owner_status_text("WO-1", "接车", "沪A12345")
        assert "WO-1" in text
        assert "接车" in text
        assert "沪A12345" in text

    def test_sms_notice_mock_when_switch_off(self, monkeypatch):
        from app.core.config import settings
        from app.core.sms import sms_service
        monkeypatch.setattr(settings, "SMS_ENABLED", False)
        assert sms_service.send_notice("13800138000", {"work_order_no": "WO-1", "status": "接车"}) == "mock"
        assert sms_service.send_notice("", {"work_order_no": "WO-1", "status": "接车"}) == "skipped"

    def test_payment_stub_has_no_settled_status(self):
        assert PAYMENT_STATUSES == ("CREATED", "CANCELLED")
        assert "PAID" not in PAYMENT_STATUSES
        assert "SUCCESS" not in PAYMENT_STATUSES


class TestRoutes:
    def test_phase2_routes_exist(self):
        spare_paths = {route.path for route in spare_router.routes}
        assert "/compatible" in spare_paths
        assert "/recommend" in {route.path for route in packages_router.routes}
        assert "/{sku_id}" in {route.path for route in skus_router.routes}
        quote_paths = {route.path for route in quotes_router.routes}
        assert "/draft" in quote_paths
        assert "/{quote_id}/staff-confirm" in quote_paths
        assert "/{quote_id}/customer-confirm" in quote_paths
        pay_paths = {route.path for route in payments_router.routes}
        assert "/intents/" in pay_paths
        assert "/intents/{intent_id}/cancel" in pay_paths

    def test_mcp_and_app_wire_the_new_tools(self):
        for name in ("query_compatible_parts", "recommend_service", "draft_quote"):
            assert name in TOOLS
        root = Path(__file__).resolve().parents[1]
        server = (root / "app" / "mcp" / "server.py").read_text(encoding="utf-8")
        main = (root / "app" / "main.py").read_text(encoding="utf-8")
        assert "async def query_compatible_parts" in server
        assert "async def recommend_service" in server
        assert "async def draft_quote" in server
        assert "service-packages" in main
        assert "quotes_router" in main
        assert "payments_router" in main

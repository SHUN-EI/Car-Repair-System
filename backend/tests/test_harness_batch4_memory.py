"""第四批：记忆门面收口与 key/TTL 自检（不加载真实模型 / Redis）。"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"

EXPECTED = {
    "GUIDED_REPAIR_SESSION_PREFIX": "guided_repair_session:",
    "EXPERT_REPAIR_SESSION_PREFIX": "expert_repair_session:",
    "MCP_STAFF_GUIDED_SESSION_PREFIX": "mcp/staff_guid:session:",
    "MCP_STAFF_GUIDED_LAST_PREFIX": "mcp/staff_guid:last:",
}
EXPECTED_TTL = 24 * 3600
TTL_NAMES = (
    "GUIDED_REPAIR_SESSION_TTL",
    "EXPERT_REPAIR_SESSION_TTL",
    "MCP_STAFF_GUIDED_SESSION_TTL",
)

SESSION_CALLERS = (
    APP / "agents" / "guided_repair_agent.py",
    APP / "agents" / "expert_repair_agent.py",
    APP / "mcp" / "tools.py",
)


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imported_modules(tree: ast.AST) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def _const_value(node: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _const_value(node.left) * _const_value(node.right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_const_value(node.operand)
    raise ValueError(f"unsupported const expr: {ast.dump(node)}")


def _module_assignments(tree: ast.AST) -> dict[str, object]:
    values: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = _const_value(node.value)
            except ValueError:
                continue
    return values


def test_memory_service_key_and_ttl_constants():
    path = APP / "memory" / "memory_service.py"
    assert path.is_file(), "缺少 app.memory.memory_service"
    tree = _parse(path)
    values = _module_assignments(tree)
    for name, expected in EXPECTED.items():
        assert values.get(name) == expected, f"{name} 应变为 {expected!r}，实际 {values.get(name)!r}"
    for name in TTL_NAMES:
        assert values.get(name) == EXPECTED_TTL, f"{name} 应变为 {EXPECTED_TTL}，实际 {values.get(name)!r}"
    # GUIDED_SESSION_TTL 是 MCP 历史对外名，应等于 MCP TTL（可能是 Name 别名）
    text = path.read_text(encoding="utf-8")
    assert "GUIDED_SESSION_TTL" in text
    assert "def get_guided_repair_session" in text
    assert "def set_guided_repair_session" in text
    assert "def get_expert_repair_session" in text
    assert "def set_expert_repair_session" in text
    assert "def get_mcp_staff_guided_session" in text
    assert "def set_mcp_staff_guided_session" in text
    assert "def get_mcp_staff_guided_last" in text
    assert "def set_mcp_staff_guided_last" in text
    assert "def summarize" in text
    assert "def new_scratchpad" in text


def test_session_callers_use_memory_facade_not_cache_service():
    violations = []
    for path in SESSION_CALLERS:
        tree = _parse(path)
        mods = _imported_modules(tree)
        if "app.memory.memory_service" not in mods:
            violations.append(f"{path.relative_to(BACKEND)} 未导入 app.memory.memory_service")
        if "app.core.cache_service" in mods:
            violations.append(f"{path.relative_to(BACKEND)} 仍直接导入 cache_service")
        # 调用点不得再拼 session key
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Attribute):
                    name = func.attr
                    recv = func.value
                    recv_name = recv.id if isinstance(recv, ast.Name) else None
                else:
                    recv_name = None
                if recv_name == "cache_service" and name in {"get", "set", "delete"}:
                    violations.append(
                        f"{path.relative_to(BACKEND)}:{node.lineno} 仍调用 cache_service.{name}"
                    )
        for prefix in EXPECTED.values():
            # 允许作为 import 别名来源出现在 memory_service；调用方文件里不应再出现字面量 key
            if f'"{prefix}"' in source or f"'{prefix}'" in source:
                violations.append(
                    f"{path.relative_to(BACKEND)} 仍字面量拼写 key 前缀 {prefix!r}"
                )
    assert not violations, "会话写入未完全收口到记忆门面:\n" + "\n".join(violations)


def test_consult_guide_summarize_goes_through_memory_facade():
    path = APP / "agents" / "consult_guide_agent.py"
    tree = _parse(path)
    # summarize 方法体内应调用 memory_service.summarize，而不直接实例化 SessionSummarizer
    found_memory = False
    found_direct = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "summarize":
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute) and child.attr == "summarize":
                    if isinstance(child.value, ast.Name) and child.value.id == "memory_service":
                        found_memory = True
                    if isinstance(child.value, ast.Name) and child.value.id == "session_summarizer":
                        found_direct = True
    assert found_memory, "consult_guide_agent.summarize 未走 memory_service"
    assert not found_direct, "consult_guide_agent.summarize 仍直接调用 session_summarizer"


def test_business_cache_not_moved_into_memory_module():
    """库存/用户等业务缓存仍走 cache_service，不被误收进记忆门面。"""
    memory = (APP / "memory" / "memory_service.py").read_text(encoding="utf-8")
    for key in ("user:", "spare_part:", "stock_alerts:"):
        assert key not in memory
    for rel in ("api/users.py", "api/spare_parts.py", "api/purchase_orders.py"):
        text = (APP / rel).read_text(encoding="utf-8")
        assert "from app.core.cache_service import cache_service" in text

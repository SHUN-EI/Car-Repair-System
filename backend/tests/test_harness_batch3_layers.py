"""第三批分层自检：core 不得反向依赖 API；search API 不得内嵌检索编排。"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"

BANNED_SEARCH_FUNCS = frozenset({
    "retrieve_hybrid",
    "_retrieve_hybrid",
    "filter_rerank_cases",
    "_filter_rerank_cases",
    "evaluate_retrieval_quality",
    "_evaluate_retrieval_quality",
    "_run_agent_search",
    "_pipeline_first_with_rescue",
    "_to_reference",
    "_effective_score",
    "make_tools",
    "_make_tools",
})


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module))
    return found


def _is_api_module(mod: str) -> bool:
    return mod == "app.api" or mod.startswith("app.api.")


def test_core_does_not_import_app_api():
    violations = []
    for path in sorted((APP / "core").rglob("*.py")):
        for lineno, mod in _imported_modules(path):
            if _is_api_module(mod):
                rel = path.relative_to(BACKEND)
                violations.append(f"{rel}:{lineno} import {mod}")
    assert not violations, "core 层仍反向依赖 API 层:\n" + "\n".join(violations)


def test_dingtalk_wo_card_uses_domain_transition():
    text = (APP / "core" / "dingtalk_wo_card.py").read_text(encoding="utf-8")
    assert "from app.api.work_orders import" not in text
    assert "from app.domain.work_order_transition import do_transition" in text


def test_search_api_does_not_define_retrieval_orchestration():
    path = APP / "api" / "search.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    leaked = sorted(defined & BANNED_SEARCH_FUNCS)
    assert not leaked, f"search API 仍定义了检索编排函数: {leaked}"

    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                name = alias.asname or alias.name
                if alias.name in BANNED_SEARCH_FUNCS or name in BANNED_SEARCH_FUNCS:
                    imported.append(f"{node.lineno}: {node.module}.{alias.name}")
    assert not imported, "search API 仍直接导入检索编排符号:\n" + "\n".join(imported)


def test_search_orchestration_lives_in_search_app():
    path = APP / "rag" / "search_app.py"
    assert path.is_file(), "缺少 app.rag.search_app"
    text = path.read_text(encoding="utf-8")
    for name in (
        "def quick_search(",
        "def hybrid_search(",
        "def agent_search(",
        "def manual_lookup(",
        "async def iter_analyze_answer_sse(",
        "async def iter_expert_answer_sse(",
        "async def iter_expert_next_step_sse(",
        "def _run_agent_search(",
        "def _pipeline_first_with_rescue(",
        "def _to_reference(",
    ):
        assert name in text, f"search_app 缺少 {name}"
    tree = ast.parse(text)
    used = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "app.agents.router" or node.module.startswith("app.agents.router"):
                used.append(f"import {node.module}")
            for alias in node.names:
                if alias.name == "AgentRouter" or alias.asname == "AgentRouter":
                    used.append(f"from {node.module} import {alias.name}")
        elif isinstance(node, ast.Name) and node.id == "AgentRouter":
            used.append("name AgentRouter")
        elif isinstance(node, ast.Attribute) and node.attr == "AgentRouter":
            used.append("attr AgentRouter")
    assert not used, f"search_app 不应走 AgentRouter: {used}"


def test_work_orders_reexports_transition_helpers():
    path = APP / "api" / "work_orders.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # 路由模块不得再定义 _do_transition，但须从领域层再导出同名符号
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_do_transition" not in defined
    assert "complete_work_order_internal" in defined

    aliases = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "app.domain.work_order_transition":
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
    assert aliases.get("_do_transition") == "do_transition"
    assert aliases.get("_add_progress_log") == "add_progress_log"
    assert aliases.get("_update_workload") == "update_workload"
    assert aliases.get("_build_work_order_response") == "build_work_order_response"

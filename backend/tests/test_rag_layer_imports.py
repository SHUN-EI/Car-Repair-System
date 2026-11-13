"""静态检查：API / scripts / main / tools 不得直接 import 向量存储与推理客户端。"""
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN = frozenset({
    "app.core.vector_store",
    "app.core.embeddings",
    "app.core.reranker",
    "pymilvus",
})

BACKEND = Path(__file__).resolve().parents[1]


def _iter_targets() -> list[Path]:
    paths: list[Path] = []
    paths.extend(sorted((BACKEND / "app" / "api").glob("*.py")))
    paths.extend(sorted((BACKEND / "scripts").glob("*.py")))
    paths.append(BACKEND / "app" / "main.py")
    paths.append(BACKEND / "app" / "agents" / "tools.py")
    return [p for p in paths if p.is_file()]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_api_scripts_and_tools_do_not_import_vector_stack():
    violations = []
    for path in _iter_targets():
        bad = sorted(mod for mod in _imported_modules(path) if mod in FORBIDDEN or mod.split(".")[0] == "pymilvus")
        if bad:
            rel = path.relative_to(BACKEND)
            violations.append(f"{rel}: {', '.join(bad)}")
    assert not violations, "以下文件仍直接 import 向量/推理客户端（应改走 app.rag.rag_service）:\n" + "\n".join(violations)


def test_retrieval_flow_shim_exists():
    shim = BACKEND / "app" / "agents" / "retrieval_flow.py"
    text = shim.read_text(encoding="utf-8")
    assert "from app.rag.retrieval_flow import" in text
    for name in (
        "make_tools",
        "retrieve_hybrid",
        "filter_rerank_cases",
        "evaluate_retrieval_quality",
        "case_rank_score",
        "repair_intent_fast_check",
        "REPAIR_IRRELEVANT_REPLY",
    ):
        assert name in text, f"shim 未再导出 {name}"

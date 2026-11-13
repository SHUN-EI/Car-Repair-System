"""精排模型默认名与 /v1/rerank 响应契约（不加载真实模型）。"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
CONFIG_PY = BACKEND / "app" / "core" / "config.py"
EMBEDDING_SERVER_PY = BACKEND / "app" / "core" / "embedding_server.py"
EXPECTED_MODEL = "BAAI/bge-reranker-v2-m3"


def test_default_reranker_model_name_is_bge_v2_m3():
    """不导入 Settings，直接读源码，避免环境缺 pydantic_settings 时无法收集。"""
    source = CONFIG_PY.read_text(encoding="utf-8")
    assert f'RERANKER_MODEL_NAME: str = "{EXPECTED_MODEL}"' in source
    assert "Qwen/Qwen3-Reranker-0.6B" not in source
    assert "Qwen3-Reranker" not in source or "尚未重标" in source


def test_embedding_server_uses_flag_reranker_not_causal_lm():
    source = EMBEDDING_SERVER_PY.read_text(encoding="utf-8")
    assert "FlagReranker" in source
    assert "compute_score" in source and "normalize=True" in source
    assert "AutoModelForCausalLM" not in source
    assert 'kind = "hf"' not in source
    assert "cross_encoder" in source
    assert "BAAI__bge-reranker-v2-m3" in source
    assert "Qwen3-Reranker-0.6B" not in source


def _have_inference_test_deps() -> bool:
    for name in ("fastapi", "loguru", "numpy", "pydantic", "pydantic_settings", "httpx"):
        if importlib.util.find_spec(name) is None:
            return False
    return True


@pytest.mark.skipif(not _have_inference_test_deps(), reason="缺少 fastapi/loguru 等，跳过接口契约测试（不安装全局包）")
def test_v1_rerank_response_is_index_and_normalized_score(monkeypatch):
    import app.core.embedding_server as es
    from fastapi.testclient import TestClient

    class FakeFlagReranker:
        def compute_score(self, pairs, normalize=True):
            assert normalize is True, "必须使用 normalize=True，禁止输出原始 logit"
            # 模拟已归一化的 0~1 分（与 documents 同序）
            return [0.21, 0.94]

    def fake_load():
        es._reranker_model = FakeFlagReranker()
        es._reranker_kind = "flag"

    monkeypatch.setattr(es, "_load_reranker", fake_load)

    # 关闭 lifespan，避免启动时加载真实模型
    with TestClient(es.app, lifespan="off") as client:
        resp = client.post(
            "/v1/rerank",
            json={"query": "主轴过流", "documents": ["无关条目", "主轴过流报警处理"]},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert "model" in body
    results = body["results"]
    assert {item["index"] for item in results} == {0, 1}
    assert all(set(item) >= {"index", "score"} for item in results)
    assert all(0.0 <= item["score"] <= 1.0 for item in results)
    scores = [item["score"] for item in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0]["index"] == 1 and results[0]["score"] == 0.94

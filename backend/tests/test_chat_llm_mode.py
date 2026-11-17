"""对话模型 CHAT_LLM_MODE 切换（不调用真实 LLM）。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
CONFIG_PY = BACKEND / "app" / "core" / "config.py"
CHAT_LLM_PY = BACKEND / "app" / "core" / "chat_llm.py"


def test_config_defaults_are_qwen_cloud_and_local_7b():
    """不导入 Settings，直接读源码，避免环境缺依赖时无法收集。"""
    source = CONFIG_PY.read_text(encoding="utf-8")
    assert 'CHAT_LLM_MODE: str = "cloud"' in source
    assert 'CHAT_CLOUD_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"' in source
    assert 'CHAT_CLOUD_MODEL: str = "qwen-plus"' in source
    assert 'CHAT_LOCAL_BASE_URL: str = "http://127.0.0.1:8001/v1"' in source
    assert 'CHAT_LOCAL_MODEL: str = "Qwen/Qwen2.5-7B-Instruct"' in source
    assert "CHAT_LOCAL_TIMEOUT_FLOOR: int = 30" in source


def test_call_sites_go_through_make_chat_llm():
    source = CHAT_LLM_PY.read_text(encoding="utf-8")
    assert "def make_chat_llm(" in source
    assert "ChatOpenAI(**params)" in source or "return ChatOpenAI(" in source

    leftover = []
    skip = {"config.py", "chat_llm.py", "test_chat_llm_mode.py"}
    for path in (BACKEND / "app").rglob("*.py"):
        if path.name in skip:
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "settings.DEEPSEEK_" in line or "ChatOpenAI(" in line:
                leftover.append(f"{path.relative_to(BACKEND)}:{i}:{line.strip()}")
    assert leftover == [], "调用点仍直接使用 DeepSeek 配置或自行构造 ChatOpenAI:\n" + "\n".join(leftover)


def _have_settings_deps() -> bool:
    return importlib.util.find_spec("pydantic_settings") is not None


@pytest.mark.skipif(not _have_settings_deps(), reason="缺少 pydantic_settings，跳过解析测试（不安装全局包）")
def test_cloud_mode_resolves_dashscope_qwen():
    from app.core.config import Settings

    s = Settings(
        CHAT_LLM_MODE="cloud",
        CHAT_CLOUD_API_KEY="sk-test",
        CHAT_CLOUD_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1",
        CHAT_CLOUD_MODEL="qwen-plus",
    )
    assert s.chat_llm_mode == "cloud"
    assert s.chat_llm_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert s.chat_llm_model == "qwen-plus"
    assert s.chat_llm_api_key == "sk-test"
    assert s.chat_llm_configured is True


@pytest.mark.skipif(not _have_settings_deps(), reason="缺少 pydantic_settings，跳过解析测试（不安装全局包）")
def test_cloud_mode_falls_back_to_dashscope_api_key():
    from app.core.config import Settings

    s = Settings(CHAT_LLM_MODE="CLOUD", CHAT_CLOUD_API_KEY="", DASHSCOPE_API_KEY="sk-dash")
    assert s.chat_llm_mode == "cloud"
    assert s.chat_llm_api_key == "sk-dash"


@pytest.mark.skipif(not _have_settings_deps(), reason="缺少 pydantic_settings，跳过解析测试（不安装全局包）")
def test_local_mode_resolves_vllm_qwen25():
    from app.core.config import Settings

    s = Settings(CHAT_LLM_MODE="local")
    assert s.chat_llm_mode == "local"
    assert s.chat_llm_base_url == "http://127.0.0.1:8001/v1"
    assert s.chat_llm_model == "Qwen/Qwen2.5-7B-Instruct"
    assert s.chat_llm_api_key == "dummy"
    assert s.chat_llm_configured is True


@pytest.mark.skipif(not _have_settings_deps(), reason="缺少 pydantic_settings，跳过解析测试（不安装全局包）")
def test_deepseek_legacy_mode_still_reads_old_keys():
    from app.core.config import Settings

    s = Settings(
        CHAT_LLM_MODE="deepseek",
        DEEPSEEK_API_KEY="sk-legacy",
        DEEPSEEK_BASE_URL="https://api.deepseek.com",
        DEEPSEEK_MODEL="deepseek-chat",
    )
    assert s.chat_llm_base_url == "https://api.deepseek.com"
    assert s.chat_llm_model == "deepseek-chat"
    assert s.chat_llm_api_key == "sk-legacy"


@pytest.mark.skipif(not _have_settings_deps(), reason="缺少 pydantic_settings，跳过解析测试（不安装全局包）")
def test_invalid_mode_raises():
    from app.core.config import Settings

    s = Settings(CHAT_LLM_MODE="foo")
    with pytest.raises(ValueError, match="CHAT_LLM_MODE"):
        _ = s.chat_llm_mode


def _have_chat_llm_deps() -> bool:
    for name in ("pydantic_settings", "langchain_openai"):
        if importlib.util.find_spec(name) is None:
            return False
    return True


@pytest.mark.skipif(not _have_chat_llm_deps(), reason="缺少 pydantic_settings/langchain_openai，跳过工厂测试")
def test_make_chat_llm_raises_local_timeout_floor(monkeypatch):
    import app.core.chat_llm as chat_llm
    from app.core.config import Settings

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    local = Settings(CHAT_LLM_MODE="local")
    monkeypatch.setattr(chat_llm, "settings", local)
    monkeypatch.setattr(chat_llm, "ChatOpenAI", FakeChatOpenAI)

    chat_llm.make_chat_llm(temperature=0, timeout=15)
    assert captured["model"] == "Qwen/Qwen2.5-7B-Instruct"
    assert captured["base_url"] == "http://127.0.0.1:8001/v1"
    assert captured["timeout"] == 30

    captured.clear()
    chat_llm.make_chat_llm(temperature=0.5, timeout=90, streaming=True)
    assert captured["timeout"] == 90
    assert captured["streaming"] is True

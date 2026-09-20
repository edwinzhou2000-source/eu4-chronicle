"""LLM / OpenAI 兼容路径：不打真实付费 API。"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from eu4_chronicle.agents.llm import LLMError, chat_completion
from eu4_chronicle.config import LLM_KEY_MISSING_HINT, Settings
from eu4_chronicle.pipeline import analyze_saves

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_blank_api_key_treated_as_missing():
    s = Settings(openai_api_key="   ", mode="llm")
    assert not s.has_openai_key()
    with pytest.raises(LLMError) as exc:
        s.ensure_llm_ready()
    assert "OPENAI_API_KEY" in str(exc.value)
    assert "mock" in str(exc.value).lower()


def test_resolved_mode_llm_does_not_silently_fallback():
    s = Settings(openai_api_key=None, mode="llm")
    assert s.resolved_mode() == "llm"


def test_openai_model_env_alias(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gemini-2.0-flash")
    monkeypatch.delenv("EU4_CHRONICLE_MODEL", raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.model == "gemini-2.0-flash"


@pytest.mark.asyncio
async def test_chat_completion_missing_key():
    settings = Settings(openai_api_key=None, mode="llm")
    with pytest.raises(LLMError) as exc:
        await chat_completion(settings, system="sys", user="user")
    assert "OPENAI_API_KEY" in str(exc.value)


@pytest.mark.asyncio
async def test_chat_completion_with_mock_client():
    settings = Settings(
        openai_api_key="test-key-not-real",
        openai_base_url="https://example.test/v1",
        model="gpt-test",
        mode="llm",
    )
    payload = {
        "choices": [{"message": {"content": "  模拟战报正文  "}}],
    }
    response = httpx.Response(
        200,
        json=payload,
        request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
    )
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(return_value=response)

    text = await chat_completion(settings, system="sys", user="user", client=client)
    assert text == "模拟战报正文"
    client.post.assert_awaited_once()
    call_kwargs = client.post.await_args
    assert call_kwargs.args[0].endswith("/chat/completions")
    assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer test-key-not-real"
    body = call_kwargs.kwargs["json"]
    assert body["model"] == "gpt-test"
    assert body["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_analyze_llm_mode_without_key_raises():
    settings = Settings(mode="llm", openai_api_key=None)
    with pytest.raises(LLMError) as exc:
        await analyze_saves(
            SAMPLES / "byz_1444.eu4",
            SAMPLES / "byz_1453.eu4",
            settings=settings,
        )
    msg = str(exc.value)
    assert "OPENAI_API_KEY" in msg
    assert LLM_KEY_MISSING_HINT[:20] in msg or "mock" in msg.lower()


@pytest.mark.asyncio
async def test_analyze_llm_path_with_mocked_chat(monkeypatch):
    """流水线 llm 路径：注入假 chat_completion，不打外网。"""
    settings = Settings(
        mode="llm",
        openai_api_key="test-key-not-real",
        openai_base_url="https://example.test/v1",
        model="gpt-test",
    )

    async def fake_chat(settings, *, system, user, timeout=120.0, client=None):
        if "主编" in system or "合成" in system or "成稿" in system:
            return (
                "# 拜占庭战报：模拟成稿\n\n"
                "**时间** 1444 → 1453\n\n"
                "## 叙事\n\n模拟叙事。\n\n"
                "## 战局要点\n\n- 模拟要点\n\n"
                "## 外交与 AE\n\n当前未见高 AE / 包围网风险低。\n\n"
                "---\n\n*结尾*\n"
            )
        return f"角色草稿：{system[:12]}"

    monkeypatch.setattr("eu4_chronicle.agents.chat_completion", fake_chat)

    report = await analyze_saves(
        SAMPLES / "byz_1444.eu4",
        SAMPLES / "byz_1453.eu4",
        settings=settings,
    )
    assert report.mode == "llm"
    assert report.final_markdown.startswith("# ")
    assert "## 叙事" in report.final_markdown
    assert all(not s.mock for s in report.sections)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY", "").strip(),
    reason="无 OPENAI_API_KEY：跳过真 API 冒烟（本仓库默认不打付费接口）",
)
async def test_live_llm_optional_smoke():
    """仅当本机已 export 真实 Key 时才跑；CI / 默认 pytest 会 skip。"""
    settings = Settings(mode="llm")  # 读环境变量
    settings.ensure_llm_ready()
    text = await chat_completion(
        settings,
        system="你只回复两个字：通过",
        user="ping",
        timeout=60.0,
    )
    assert isinstance(text, str) and len(text) > 0

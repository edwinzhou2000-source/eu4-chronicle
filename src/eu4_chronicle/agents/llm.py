"""OpenAI 兼容聊天客户端（含 Gemini 官方 OpenAI 兼容端点）。

统一走 `/chat/completions`，不引入第二套 Google 专用客户端。
"""

from __future__ import annotations

from typing import Any

import httpx

from eu4_chronicle.config import LLM_KEY_MISSING_HINT, Settings


class LLMError(RuntimeError):
    pass


async def chat_completion(
    settings: Settings,
    *,
    system: str,
    user: str,
    timeout: float = 120.0,
    client: httpx.AsyncClient | None = None,
) -> str:
    """调用 OpenAI 兼容 Chat Completions。

    ``client`` 仅供单测注入 mock，生产路径勿传。
    """
    if not settings.has_openai_key():
        raise LLMError(LLM_KEY_MISSING_HINT)

    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": settings.model,
        "temperature": 0.6,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }

    async def _post(http: httpx.AsyncClient) -> httpx.Response:
        return await http.post(url, headers=headers, json=payload)

    if client is not None:
        resp = await _post(client)
    else:
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await _post(http)

    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = (exc.response.text or "")[:400]
        raise LLMError(
            f"LLM 请求失败（HTTP {exc.response.status_code}）。"
            f"请检查 OPENAI_BASE_URL / OPENAI_MODEL / API Key 是否匹配当前服务商。详情: {body}"
        ) from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise LLMError(f"LLM 响应不是合法 JSON: {resp.text[:400]!r}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("content 非字符串")
        return content.strip()
    except (KeyError, IndexError, AttributeError, TypeError) as exc:
        raise LLMError(f"LLM 响应格式异常: {data!r}") from exc

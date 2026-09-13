"""OpenAI 兼容聊天客户端；无 Key 时由上层走 mock。"""

from __future__ import annotations

import httpx

from eu4_chronicle.config import Settings


class LLMError(RuntimeError):
    pass


async def chat_completion(
    settings: Settings,
    *,
    system: str,
    user: str,
    timeout: float = 120.0,
) -> str:
    if not settings.openai_api_key:
        raise LLMError("未配置 OPENAI_API_KEY")

    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.model,
        "temperature": 0.6,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"LLM 请求失败: {exc.response.status_code} {exc.response.text[:400]}") from exc
        data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError, TypeError) as exc:
        raise LLMError(f"LLM 响应格式异常: {data!r}") from exc

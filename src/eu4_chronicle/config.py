"""本机配置：存档目录、模型、并发。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_windows_save_dir() -> Path:
    """Windows 默认 EU4 存档目录；非 Windows 则回落到用户主目录下的同相对路径。"""
    userprofile = os.environ.get("USERPROFILE") or str(Path.home())
    return (
        Path(userprofile)
        / "Documents"
        / "Paradox Interactive"
        / "Europa Universalis IV"
        / "save games"
    )


# 无 Key 却显式要求 llm 时的人话提示（CLI / API / 单测共用）
LLM_KEY_MISSING_HINT = (
    "未设置 OPENAI_API_KEY。请在项目根目录复制 .env.example 为 .env 并填入密钥，"
    "或改用 --mode mock（不调外部模型）。"
    "Gemini 也走同一套变量：OPENAI_BASE_URL 指向 Google 的 OpenAI 兼容端点，"
    "OPENAI_API_KEY 填 Gemini API Key。"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    save_dir: Path = Field(
        default_factory=default_windows_save_dir,
        validation_alias="EU4_SAVE_DIR",
    )
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="OPENAI_BASE_URL",
    )
    model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("OPENAI_MODEL", "EU4_CHRONICLE_MODEL"),
    )
    mode: str = Field(default="mock", validation_alias="EU4_CHRONICLE_MODE")
    host: str = Field(default="127.0.0.1", validation_alias="EU4_CHRONICLE_HOST")
    port: int = Field(default=18765, validation_alias="EU4_CHRONICLE_PORT")
    agent_concurrency: int = Field(default=3, validation_alias="EU4_CHRONICLE_CONCURRENCY")

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _blank_key_as_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())

    def resolved_mode(self) -> str:
        """归一化 mode；显式 llm 不会静默回退到 mock（缺 Key 由 ensure_llm_ready 报错）。"""
        mode = (self.mode or "mock").strip().lower()
        if mode not in {"mock", "llm"}:
            return "mock"
        return mode

    def ensure_llm_ready(self) -> None:
        """`--mode llm` 前调用：缺 Key 时抛出人话错误。"""
        if self.resolved_mode() != "llm":
            return
        if not self.has_openai_key():
            from eu4_chronicle.agents.llm import LLMError

            raise LLMError(LLM_KEY_MISSING_HINT)


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""本机配置：存档目录、模型、并发。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
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
    model: str = Field(default="gpt-4o-mini", validation_alias="EU4_CHRONICLE_MODEL")
    mode: str = Field(default="mock", validation_alias="EU4_CHRONICLE_MODE")
    host: str = Field(default="127.0.0.1", validation_alias="EU4_CHRONICLE_HOST")
    port: int = Field(default=18765, validation_alias="EU4_CHRONICLE_PORT")
    agent_concurrency: int = Field(default=3, validation_alias="EU4_CHRONICLE_CONCURRENCY")

    def resolved_mode(self) -> str:
        """无 Key 时强制 mock，保证演示可跑通。"""
        mode = (self.mode or "mock").strip().lower()
        if mode == "llm" and not self.openai_api_key:
            return "mock"
        if mode not in {"mock", "llm"}:
            return "mock"
        return mode


@lru_cache
def get_settings() -> Settings:
    return Settings()

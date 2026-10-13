"""本机配置：存档目录、模型、并发。"""

from __future__ import annotations

import os
import re
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PARADOX_SAVE_TAIL = Path("Paradox Interactive") / "Europa Universalis IV" / "save games"
_PARADOX_DOCS_TAIL = Path("Paradox Interactive") / "Europa Universalis IV"
_EU4_STEAM_TAIL = Path("steamapps") / "common" / "Europa Universalis IV"
_SKIP_WIN_USERS = frozenset(
    {
        "public",
        "default",
        "default user",
        "defaultuser",
        "all users",
        "allusers",
        "desktop.ini",
    }
)
# C:\... or C:/... → /mnt/c/...
_WIN_DRIVE_PATH_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def _is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        text = Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in text or "wsl" in text


def _windows_usernames() -> list[str]:
    """推断 Windows 用户名（优先环境变量，再扫 /mnt/c/Users）。"""
    names: list[str] = []
    for key in ("WSL_USER", "USER", "USERNAME"):
        val = (os.environ.get(key) or "").strip()
        if val and val.lower() not in _SKIP_WIN_USERS and val not in names:
            names.append(val)

    users_root = Path("/mnt/c/Users")
    scanned: list[str] = []
    if users_root.is_dir():
        try:
            entries = sorted(users_root.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            entries = []
        for entry in entries:
            if not entry.is_dir():
                continue
            name = entry.name
            if name.lower() in _SKIP_WIN_USERS:
                continue
            if name not in scanned:
                scanned.append(name)

    ordered: list[str] = []
    for n in names:
        if n not in ordered:
            ordered.append(n)
    for n in scanned:
        if n not in ordered:
            ordered.append(n)
    return ordered


def _wsl_save_dir_candidates() -> list[Path]:
    """WSL 下常见 Windows EU4 存档路径（按优先级）。"""
    docs_names = ("Documents", "文档")
    roots: list[Path] = []
    for user in _windows_usernames():
        base = Path("/mnt/c/Users") / user
        for docs in docs_names:
            roots.append(base / docs)
            roots.append(base / "OneDrive" / docs)
            roots.append(base / "OneDrive" / "Documents")
            roots.append(base / "OneDrive" / "文档")
    # 去重且保序
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        cand = root / _PARADOX_SAVE_TAIL
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
    return out


def _native_save_dir_candidates() -> list[Path]:
    userprofile = os.environ.get("USERPROFILE")
    out: list[Path] = []
    if userprofile:
        out.append(Path(userprofile) / "Documents" / _PARADOX_SAVE_TAIL)
        out.append(Path(userprofile) / "OneDrive" / "Documents" / _PARADOX_SAVE_TAIL)
        out.append(Path(userprofile) / "OneDrive" / "文档" / _PARADOX_SAVE_TAIL)
    out.append(Path.home() / "Documents" / _PARADOX_SAVE_TAIL)
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def iter_default_save_dir_candidates() -> list[Path]:
    if _is_wsl():
        return [*_wsl_save_dir_candidates(), *_native_save_dir_candidates()]
    return _native_save_dir_candidates()


def resolve_default_save_dir() -> Path:
    """解析默认存档目录。

    - 优先：存在且含有 ``*.eu4`` 的候选路径
    - 其次：存在的 ``save games`` / Paradox 目录
    - 否则：返回最可能的绝对路径（用于提示），**绝不**返回 ``.``
    """
    candidates = iter_default_save_dir_candidates()
    with_eu4: list[Path] = []
    existing: list[Path] = []
    for cand in candidates:
        try:
            if not cand.is_dir():
                continue
        except OSError:
            continue
        existing.append(cand)
        try:
            if any(cand.glob("*.eu4")):
                with_eu4.append(cand)
        except OSError:
            continue

    chosen: Path
    if with_eu4:
        chosen = with_eu4[0]
    elif existing:
        chosen = existing[0]
    elif candidates:
        chosen = candidates[0]
    else:
        chosen = Path.home() / "Documents" / _PARADOX_SAVE_TAIL

    try:
        return chosen.expanduser().resolve(strict=False)
    except OSError:
        return chosen.expanduser().absolute()


def default_windows_save_dir() -> Path:
    """兼容旧名：默认 EU4 存档目录（含 WSL 自动探测）。"""
    return resolve_default_save_dir()


def iter_default_paradox_docs_candidates() -> list[Path]:
    """Documents/Paradox Interactive/Europa Universalis IV（含 dlc_load.json）。"""
    out: list[Path] = []
    if _is_wsl():
        for user in _windows_usernames():
            base = Path("/mnt/c/Users") / user
            for docs in ("Documents", "文档"):
                out.append(base / docs / _PARADOX_DOCS_TAIL)
                out.append(base / "OneDrive" / docs / _PARADOX_DOCS_TAIL)
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        out.append(Path(userprofile) / "Documents" / _PARADOX_DOCS_TAIL)
    out.append(Path.home() / "Documents" / _PARADOX_DOCS_TAIL)
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def resolve_default_paradox_docs() -> Path | None:
    for cand in iter_default_paradox_docs_candidates():
        try:
            if cand.is_dir() and (cand / "dlc_load.json").is_file():
                return cand.expanduser().resolve(strict=False)
        except OSError:
            continue
    for cand in iter_default_paradox_docs_candidates():
        try:
            if cand.is_dir():
                return cand.expanduser().resolve(strict=False)
        except OSError:
            continue
    return None


def iter_default_game_dir_candidates() -> list[Path]:
    """常见 Steam 安装路径。"""
    out: list[Path] = []
    if _is_wsl():
        for drive in ("d", "c", "e"):
            out.append(Path(f"/mnt/{drive}/Games/Steam") / _EU4_STEAM_TAIL)
            out.append(Path(f"/mnt/{drive}/SteamLibrary") / _EU4_STEAM_TAIL)
            out.append(
                Path(f"/mnt/{drive}/Program Files (x86)/Steam") / _EU4_STEAM_TAIL
            )
            out.append(Path(f"/mnt/{drive}/Program Files/Steam") / _EU4_STEAM_TAIL)
    # Windows / 原生
    for root in (
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramFiles"),
        r"D:\Games\Steam",
        r"C:\Program Files (x86)\Steam",
    ):
        if not root:
            continue
        converted = windows_drive_path_to_wsl(str(root)) if _is_wsl() else None
        base = Path(converted or root)
        out.append(base / _EU4_STEAM_TAIL)
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def resolve_default_game_dir() -> Path | None:
    for cand in iter_default_game_dir_candidates():
        try:
            if cand.is_dir() and (cand / "localisation").is_dir():
                return cand.expanduser().resolve(strict=False)
        except OSError:
            continue
    return None


def windows_drive_path_to_wsl(path_str: str) -> str | None:
    """若为 Windows 盘符路径（``C:\\...`` / ``C:/...``），转为 ``/mnt/<drive>/...``；否则 None。"""
    raw = path_str.strip().strip('"').strip("'")
    match = _WIN_DRIVE_PATH_RE.match(raw)
    if not match:
        return None
    drive = match.group(1).lower()
    rest = match.group(2).replace("\\", "/")
    rest = re.sub(r"/+", "/", rest).strip("/")
    if rest:
        return f"/mnt/{drive}/{rest}"
    return f"/mnt/{drive}"


def wslize_save_dir_value(value: object) -> object:
    """WSL 下把显式 Windows 盘符路径改写成 /mnt/...；非 WSL 或已是 POSIX 则原样返回。"""
    if not _is_wsl():
        return value
    if isinstance(value, Path):
        raw = str(value)
    elif isinstance(value, str):
        raw = value
    else:
        return value
    converted = windows_drive_path_to_wsl(raw)
    if converted is None:
        return value
    return converted


def format_save_dir(path: Path) -> str:
    """UI / API 展示用绝对路径，避免出现裸 ``.`` 或把空配置 resolve 成进程 cwd。"""
    raw = str(path).strip() if path is not None else ""
    if not raw or raw in {".", "./"}:
        return str(resolve_default_save_dir())
    try:
        text = str(Path(raw).expanduser().resolve(strict=False))
    except OSError:
        text = str(Path(raw).expanduser().absolute())
    if not text or text in {".", "./"}:
        return str(resolve_default_save_dir())
    return text


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
        default_factory=lambda: resolve_default_save_dir(),
        validation_alias="EU4_SAVE_DIR",
    )
    game_dir: Path | None = Field(
        default_factory=resolve_default_game_dir,
        validation_alias="EU4_GAME_DIR",
    )
    paradox_docs: Path | None = Field(
        default_factory=resolve_default_paradox_docs,
        validation_alias="EU4_PARADOX_DOCS",
    )
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="OPENAI_BASE_URL",
    )
    model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("OPENAI_MODEL", "EU4_GAME_REPORT_MODEL"),
    )
    mode: str = Field(default="mock", validation_alias="EU4_GAME_REPORT_MODE")
    host: str = Field(default="127.0.0.1", validation_alias="EU4_GAME_REPORT_HOST")
    port: int = Field(default=18765, validation_alias="EU4_GAME_REPORT_PORT")
    agent_concurrency: int = Field(default=4, validation_alias="EU4_GAME_REPORT_CONCURRENCY")

    @field_validator("save_dir", mode="before")
    @classmethod
    def _blank_save_dir_as_default(cls, value: object) -> object:
        """``.env`` 里 ``EU4_SAVE_DIR=`` 空串会被 Path 变成 ``.``，视为未设置。"""
        if value is None:
            return resolve_default_save_dir()
        if isinstance(value, str) and not value.strip():
            return resolve_default_save_dir()
        if isinstance(value, Path) and str(value) in {".", ""}:
            return resolve_default_save_dir()
        # 尽早转写，避免 Path 在 POSIX 上把反斜杠弄乱
        return wslize_save_dir_value(value)

    @field_validator("game_dir", mode="before")
    @classmethod
    def _blank_game_dir_as_default(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return resolve_default_game_dir()
        if isinstance(value, Path) and str(value) in {".", ""}:
            return resolve_default_game_dir()
        return wslize_save_dir_value(value)

    @field_validator("paradox_docs", mode="before")
    @classmethod
    def _blank_paradox_docs_as_default(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return resolve_default_paradox_docs()
        if isinstance(value, Path) and str(value) in {".", ""}:
            return resolve_default_paradox_docs()
        return wslize_save_dir_value(value)

    @field_validator("game_dir", "paradox_docs", mode="after")
    @classmethod
    def _normalize_optional_path(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        raw = str(value).strip()
        if not raw or raw in {".", "./"}:
            return None
        wslized = wslize_save_dir_value(raw)
        if isinstance(wslized, str):
            value = Path(wslized)
        try:
            return value.expanduser().resolve(strict=False)
        except OSError:
            return value.expanduser().absolute()

    @field_validator("save_dir", mode="after")
    @classmethod
    def _normalize_save_dir(cls, value: Path) -> Path:
        raw = str(value).strip() if value is not None else ""
        if not raw or raw in {".", "./"}:
            return resolve_default_save_dir()
        wslized = wslize_save_dir_value(raw)
        if isinstance(wslized, str):
            value = Path(wslized)
            raw = wslized
        # Path('') / Path('.') 在部分环境下 expand 后仍可能指向 cwd；禁止把「未配置」当成仓库根
        try:
            resolved = value.expanduser().resolve(strict=False)
        except OSError:
            resolved = value.expanduser().absolute()
        if str(resolved) in {".", "./"}:
            return resolve_default_save_dir()
        return resolved

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
            from eu4_game_report.agents.llm import LLMError

            raise LLMError(LLM_KEY_MISSING_HINT)


@lru_cache
def get_settings() -> Settings:
    return Settings()

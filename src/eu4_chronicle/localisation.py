"""从 EU4 本体 + 已启用 Mod 加载 localisation，按任务 ID 查 title/desc。

存档只有任务 ID；正文在游戏/Mod 的 ``*_l_*.yml``。中文语言 Mod 常用特制字形编码，
不可读时跳过该键，保留先前可读（多为英文）或降级为可读化 ID。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from eu4_chronicle.config import windows_drive_path_to_wsl, wslize_save_dir_value

logger = logging.getLogger(__name__)

_LOC_LINE_RE = re.compile(
    r'^\s*([A-Za-z0-9_./+\-]+):\d*\s*"(.*)"\s*$'
)
_YAML_ESCAPE_RE = re.compile(r'\\(.)')


@dataclass
class MissionText:
    mission_id: str
    title: str
    desc: str = ""
    loc_found: bool = False
    """title/desc 是否来自本地化（非纯 ID 可读化）。"""


@dataclass
class GameLocalisation:
    """合并后的键值表（后者覆盖前者，但跳过乱码值）。"""

    entries: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)

    def get(self, key: str) -> str | None:
        val = self.entries.get(key)
        if val is None:
            return None
        text = _strip_loc_markup(val).strip()
        return text or None

    def mission_text(self, mission_id: str) -> MissionText:
        mid = (mission_id or "").strip().strip('"')
        if not mid:
            return MissionText(mission_id="", title="未知任务", loc_found=False)
        title = self.get(f"{mid}_title") or self.get(mid)
        desc = self.get(f"{mid}_desc") or ""
        if title:
            return MissionText(
                mission_id=mid, title=title, desc=desc, loc_found=True
            )
        return MissionText(
            mission_id=mid,
            title=humanize_mission_id(mid),
            desc="",
            loc_found=False,
        )


def humanize_mission_id(mission_id: str) -> str:
    """无本地化时的诚实标题：下划线转空格，不编造剧情。"""
    mid = mission_id.strip().strip('"')
    if not mid:
        return "未知任务"
    return mid.replace("_", " ")


_SCRIPT_EVENT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*\.[0-9A-Za-z_]+$")
_SCRIPTISH_MISSION_RE = re.compile(
    r"(?:^|[\s_])(?:NYDD|DD)[\s_A-Z]",
    re.I,
)


def is_readable_display_title(text: str) -> bool:
    """成稿/brief 可用的标题：非空、非乱码、非脚本 ID / humanize 任务 ID。"""
    if not text or is_garbled_loc(text):
        return False
    t = text.strip()
    if _SCRIPT_EVENT_ID_RE.fullmatch(t):
        return False
    if "_" in t and re.fullmatch(r"[A-Za-z0-9_]+", t):
        return False
    if _SCRIPTISH_MISSION_RE.search(t):
        return False
    return True


def is_garbled_loc(text: str) -> bool:
    """中文语言 Mod 常用 0x10/0x12 引导的私有编码；视为不可读。"""
    if not text:
        return True
    bad = 0
    for ch in text:
        o = ord(ch)
        if ch in "\t\n\r":
            continue
        if o < 32 or 0x10 <= o <= 0x12 or 0xE000 <= o <= 0xF8FF:
            bad += 1
    return (bad / len(text)) > 0.05


def looks_mojibake(text: str) -> bool:
    """含替换符 � 或明显编码损坏。"""
    if not text:
        return False
    if "\ufffd" in text or "�" in text:
        return True
    return is_garbled_loc(text)


def looks_mostly_latin(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    latin = sum(
        1
        for ch in letters
        if ("A" <= ch <= "Z")
        or ("a" <= ch <= "z")
        or ch in "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿüöäöß"
    )
    return latin / len(letters) >= 0.6


def sanitize_display_name(text: str | None, *, fallback: str = "") -> str:
    """成稿用：乱码地名/战役名回退为 fallback 或省略。"""
    if not text:
        return fallback
    t = text.strip()
    if looks_mojibake(t):
        return fallback
    return t


def _strip_loc_markup(text: str) -> str:
    """去掉 § 着色与常见预览色脚本包装，保留可读正文。"""
    out = re.sub(r"§.", "", text)
    out = out.replace("§!", "")
    # [Root.GetPreviewColorTEU]Title[Root.GetPreviewColorTEU_end] → Title
    out = re.sub(r"\[Root\.GetPreviewColor[^\]]*\]", "", out)
    out = re.sub(r"\[Root\.GetPreviewColor[^\]]*\_end\]", "", out)
    out = out.replace("\\n", "\n")
    return out.strip()


def _unescape_yml_string(raw: str) -> str:
    def repl(m: re.Match[str]) -> str:
        ch = m.group(1)
        return {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(ch, ch)

    return _YAML_ESCAPE_RE.sub(repl, raw)


def parse_localisation_yml(text: str) -> dict[str, str]:
    """解析 Paradox localisation yml（宽松：逐行 key:N \"value\"）。"""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        # 跳过语言头 l_english:
        stripped = line.strip()
        if re.fullmatch(r"l_[a-zA-Z0-9_]+\s*:", stripped):
            continue
        m = _LOC_LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), _unescape_yml_string(m.group(2))
        if is_garbled_loc(val):
            continue
        out[key] = val
    return out


def _path_from_mod_descriptor(raw: str) -> Path | None:
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return None
    converted = wslize_save_dir_value(raw)
    if isinstance(converted, str):
        raw = converted
    elif windows_drive_path_to_wsl(raw):
        raw = windows_drive_path_to_wsl(raw) or raw
    p = Path(raw)
    try:
        return p.expanduser().resolve(strict=False)
    except OSError:
        return p.expanduser().absolute()


def read_mod_path_from_descriptor(mod_file: Path) -> Path | None:
    """从 ``ugc_*.mod`` 读 path=。"""
    try:
        text = mod_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("path="):
            return _path_from_mod_descriptor(line.split("=", 1)[1])
    return None


def enabled_mod_paths(paradox_docs: Path | None) -> list[Path]:
    """按 dlc_load.json 的 enabled_mods 顺序返回 Mod 根目录。"""
    if paradox_docs is None:
        return []
    dlc_load = paradox_docs / "dlc_load.json"
    if not dlc_load.is_file():
        return []
    try:
        data = json.loads(dlc_load.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("无法读取 dlc_load.json: %s", exc)
        return []
    enabled = data.get("enabled_mods") or []
    out: list[Path] = []
    for rel in enabled:
        # "mod/ugc_xxx.mod"
        mod_file = paradox_docs / str(rel).replace("\\", "/")
        if not mod_file.is_file():
            # 有时 rel 已是绝对片段
            mod_file = Path(str(rel))
        root = read_mod_path_from_descriptor(mod_file) if mod_file.is_file() else None
        if root is not None and root.is_dir():
            out.append(root)
    return out


def iter_localisation_yml(root: Path) -> list[Path]:
    """只收 ``*l_english*.yml``：中文语言 Mod 也写在 english 文件名下；
    避免 fr/de/es 后加载覆盖英文正文。"""
    loc = root / "localisation"
    if not loc.is_dir():
        return []
    files = [
        p
        for p in loc.rglob("*.yml")
        if "l_english" in p.name.lower() or "l_simp_chinese" in p.name.lower()
    ]
    # english 先，simp_chinese 后（可读中文可覆盖；乱码在 parse 时已跳过）
    def sort_key(p: Path) -> tuple[int, str]:
        name = p.name.lower()
        if "l_simp_chinese" in name:
            return (1, str(p))
        return (0, str(p))

    return sorted(files, key=sort_key)


def load_localisation_from_roots(roots: list[Path]) -> GameLocalisation:
    loc = GameLocalisation()
    for root in roots:
        if not root or not root.is_dir():
            continue
        loaded_any = False
        for yml in iter_localisation_yml(root):
            try:
                text = yml.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            parsed = parse_localisation_yml(text)
            if not parsed:
                continue
            loc.entries.update(parsed)
            loaded_any = True
        if loaded_any:
            loc.sources.append(str(root))
    return loc


def load_game_localisation(
    *,
    game_dir: Path | None,
    paradox_docs: Path | None,
) -> GameLocalisation:
    roots: list[Path] = []
    if game_dir is not None and game_dir.is_dir():
        roots.append(game_dir)
    roots.extend(enabled_mod_paths(paradox_docs))
    return load_localisation_from_roots(roots)


@lru_cache
def get_game_localisation(
    game_dir: str | None = None,
    paradox_docs: str | None = None,
) -> GameLocalisation:
    gd = Path(game_dir) if game_dir else None
    pd = Path(paradox_docs) if paradox_docs else None
    return load_game_localisation(game_dir=gd, paradox_docs=pd)


def enrich_mission_diff(
    diff,
    loc: GameLocalisation | None = None,
    *,
    script_index=None,
):
    """为 mission_completed 填入可读任务标题。

    ``desc`` 为任务书面板背景（未完成前的说明），成稿应作「已完成」表述。
    不注入 reward_events：存档无法证明区间内是否真弹出脚本挂接的 country_event。
    ``script_index`` 保留参数以兼容调用方，成稿路径忽略。
    """
    from eu4_chronicle.models import DiffResult

    _ = script_index
    if not isinstance(diff, DiffResult):
        return diff
    loc = loc or GameLocalisation()
    events = []
    for ev in diff.events:
        if ev.kind != "mission_completed":
            events.append(ev)
            continue
        detail = dict(ev.detail or {})
        mid = str(detail.get("mission_id") or "").strip()
        text = loc.mission_text(mid)
        detail["mission_id"] = text.mission_id
        detail["title"] = text.title
        detail["desc"] = text.desc
        detail["loc_found"] = text.loc_found
        detail["background_desc"] = text.desc
        detail["reward_events"] = []
        detail["player_choice_known"] = False
        if text.loc_found and is_readable_display_title(text.title):
            summary = f"已完成任务「{text.title}」"
        else:
            summary = "已完成一项任务（无可用本地化标题）"
        events.append(ev.model_copy(update={"summary": summary, "detail": detail}))
    return diff.model_copy(update={"events": events})

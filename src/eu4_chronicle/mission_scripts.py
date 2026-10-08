"""从游戏/Mod 的 missions、events 脚本提取：任务完成时可能触发的事件正文键。

多选事件不猜玩家点选；恰好一个 option 时沿 country_event 连锁（深度有限）。
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from eu4_chronicle.localisation import (
    GameLocalisation,
    enabled_mod_paths,
    is_garbled_loc,
    is_readable_display_title,
)

_MISSION_START_RE = re.compile(r"^\s*([a-zA-Z0-9_]+)\s*=\s*\{", re.M)
_EVENT_ID_RE = re.compile(
    r"country_event\s*=\s*\{\s*id\s*=\s*([a-zA-Z0-9_.]+)",
    re.M,
)
_EVENT_ID_BARE_RE = re.compile(
    r"country_event\s*=\s*([a-zA-Z0-9_.]+)",
    re.M,
)
_COUNTRY_EVENT_BLOCK_RE = re.compile(
    r"country_event\s*=\s*\{",
    re.M,
)
_OPTION_NAME_RE = re.compile(r"name\s*=\s*\"?([^\s\"=#{}]+)\"?", re.M)
_BARE_EVENT_ID_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]*\.[0-9a-zA-Z_]+")
_COMMENT_NUM_TITLE_RE = re.compile(r"^\s*#\s*\d+\s+(\S.*\S|\S)\s*$")
_COMMENT_CJK_TITLE_RE = re.compile(r"^\s*#\s*(.*[\u4e00-\u9fff].*)\s*$")

# 单选项连锁最大深度（0=任务 effect 直出）
_MAX_CHAIN_DEPTH = 3


@dataclass
class RewardEventText:
    event_id: str
    title: str = ""
    desc: str = ""
    options: list[str] = field(default_factory=list)
    """选项按钮文案（非玩家实际选择；成稿勿注入）。"""
    choice_known: bool = False
    depth: int = 0
    """0=任务 effect 直出；>0=单选项连锁后续。"""
    chain_deterministic: bool = False
    """True：该节点恰有 1 个 option（可继续展开）。"""
    title_source: str = ""
    """loc | script_comment | 空。"""


@dataclass
class MissionScriptIndex:
    """mission_id → 完成 effect 里出现的 country_event id 列表。"""

    mission_events: dict[str, list[str]] = field(default_factory=dict)
    event_keys: dict[str, dict[str, object]] = field(default_factory=dict)
    # event_id -> {
    #   title_key, desc_key, option_keys,
    #   option_followups: list[list[str]], immediate_followups: list[str]
    # }
    sources: list[str] = field(default_factory=list)

    def reward_events_for(
        self, mission_id: str, loc: GameLocalisation
    ) -> list[RewardEventText]:
        """任务 effect 第一跳 + 仅单选项时的后续弹窗（深度≤3、去环）。"""
        out: list[RewardEventText] = []
        seen: set[str] = set()
        queue: deque[tuple[str, int]] = deque()
        for eid in self.mission_events.get(mission_id, []):
            queue.append((eid, 0))

        while queue:
            eid, depth = queue.popleft()
            if eid in seen or depth > _MAX_CHAIN_DEPTH:
                continue
            seen.add(eid)

            keys = self.event_keys.get(eid) or {}
            title_key = str(keys.get("title_key") or "")
            desc_key = str(keys.get("desc_key") or "")
            opt_keys = list(keys.get("option_keys") or [])
            option_followups = list(keys.get("option_followups") or [])
            immediate_followups = list(keys.get("immediate_followups") or [])
            title = (loc.get(title_key) if title_key else None) or ""
            title_source = ""
            if title and is_readable_display_title(title):
                title_source = "loc"
            else:
                title = ""
                comment = str(keys.get("comment_title") or "").strip()
                if comment and is_readable_display_title(comment):
                    title = comment
                    title_source = "script_comment"
            desc = (loc.get(desc_key) if desc_key else None) or ""
            if desc and is_garbled_loc(desc):
                desc = ""
            options: list[str] = []
            for ok in opt_keys:
                t = loc.get(str(ok))
                if t and not is_garbled_loc(t):
                    options.append(t)

            single = len(opt_keys) == 1
            out.append(
                RewardEventText(
                    event_id=eid,
                    title=title,
                    desc=desc,
                    options=options,
                    choice_known=single,
                    depth=depth,
                    chain_deterministic=single,
                    title_source=title_source,
                )
            )

            if not single or depth >= _MAX_CHAIN_DEPTH:
                continue
            next_ids: list[str] = []
            next_seen: set[str] = set()
            for fid in immediate_followups:
                if fid and fid not in next_seen:
                    next_seen.add(fid)
                    next_ids.append(fid)
            if option_followups:
                for fid in option_followups[0]:
                    if fid and fid not in next_seen:
                        next_seen.add(fid)
                        next_ids.append(fid)
            for fid in next_ids:
                if fid not in seen:
                    queue.append((fid, depth + 1))
        return out


def _brace_block(text: str, open_idx: int) -> str | None:
    """open_idx 指向 '{'。"""
    if open_idx < 0 or open_idx >= len(text) or text[open_idx] != "{":
        return None
    depth = 0
    i = open_idx
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx : i + 1]
        i += 1
    return None


def _extract_country_event_ids(block: str) -> list[str]:
    """从任意脚本块中收集 country_event id（保序去重）。"""
    found: list[str] = []
    seen: set[str] = set()
    for em in _EVENT_ID_RE.finditer(block):
        eid = em.group(1).strip()
        if eid and eid not in seen:
            seen.add(eid)
            found.append(eid)
    for em in _EVENT_ID_BARE_RE.finditer(block):
        eid = em.group(1).strip()
        if eid in {"{", "}"} or eid.startswith("{"):
            continue
        if eid not in seen and _BARE_EVENT_ID_RE.fullmatch(eid):
            seen.add(eid)
            found.append(eid)
    return found


def _extract_effect_events(mission_block: str) -> list[str]:
    """从任务块的 effect={...} 中收集 country_event id（保序去重）。"""
    m = re.search(r"\beffect\s*=\s*\{", mission_block)
    if not m:
        return []
    open_b = mission_block.find("{", m.start())
    effect = _brace_block(mission_block, open_b)
    if not effect:
        return []
    return _extract_country_event_ids(effect)


def index_missions_file(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in _MISSION_START_RE.finditer(text):
        mid = m.group(1)
        # 跳过顶层 mission_slot 等容器名的误伤：任务 id 通常含下划线
        if mid in {"effect", "trigger", "option", "if", "else", "limit"}:
            continue
        open_b = text.find("{", m.start())
        block = _brace_block(text, open_b)
        if not block:
            continue
        # 只要含 effect= 的块当作任务候选
        if "effect" not in block or "trigger" not in block:
            continue
        events = _extract_effect_events(block)
        if events:
            out[mid] = events
    return out


def _comment_title_before(text: str, pos: int) -> str:
    """取 country_event 定义正上方注释中的可读标题（如「#17 癫狂之终」）。"""
    idx = pos
    for _ in range(12):
        prev_nl = text.rfind("\n", 0, idx)
        if prev_nl < 0:
            line = text[:idx]
            idx = -1
        else:
            line = text[prev_nl + 1 : idx]
            idx = prev_nl
        stripped = line.strip()
        if not stripped:
            if idx < 0:
                break
            continue
        if stripped.startswith("#"):
            m = _COMMENT_NUM_TITLE_RE.match(stripped)
            if m:
                title = m.group(1).strip()
                if title and not is_garbled_loc(title):
                    return title
            m2 = _COMMENT_CJK_TITLE_RE.match(stripped)
            if m2:
                title = m2.group(1).strip()
                if title and not is_garbled_loc(title):
                    return title
            if idx < 0:
                break
            continue
        break
    return ""


def index_events_file(text: str) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for m in _COUNTRY_EVENT_BLOCK_RE.finditer(text):
        open_b = text.find("{", m.start())
        block = _brace_block(text, open_b)
        if not block:
            continue
        id_m = re.search(r"\bid\s*=\s*([a-zA-Z0-9_.]+)", block)
        if not id_m:
            continue
        eid = id_m.group(1).strip()
        title_m = re.search(r"\btitle\s*=\s*\"?([^\s\"=#{}]+)\"?", block)
        desc_m = re.search(r"\bdesc\s*=\s*\"?([^\s\"=#{}]+)\"?", block)
        option_keys: list[str] = []
        option_followups: list[list[str]] = []
        for om in re.finditer(r"\boption\s*=\s*\{", block):
            ob = block.find("{", om.start())
            oblock = _brace_block(block, ob)
            if not oblock:
                continue
            nm = _OPTION_NAME_RE.search(oblock)
            if nm:
                option_keys.append(nm.group(1).strip())
            else:
                option_keys.append("")
            option_followups.append(_extract_country_event_ids(oblock))
        # 跳过 option 内触发用的 country_event = { id = x } 残块，避免覆盖完整定义
        if not title_m and not desc_m and not option_keys:
            continue
        immediate_followups: list[str] = []
        for im in re.finditer(r"\bimmediate\s*=\s*\{", block):
            ib = block.find("{", im.start())
            iblock = _brace_block(block, ib)
            if iblock:
                for fid in _extract_country_event_ids(iblock):
                    if fid not in immediate_followups:
                        immediate_followups.append(fid)
        comment_title = _comment_title_before(text, m.start())
        out[eid] = {
            "title_key": (title_m.group(1).strip() if title_m else ""),
            "desc_key": (desc_m.group(1).strip() if desc_m else ""),
            "option_keys": option_keys,
            "option_followups": option_followups,
            "immediate_followups": immediate_followups,
            "comment_title": comment_title,
        }
    return out


def build_mission_script_index(roots: list[Path]) -> MissionScriptIndex:
    idx = MissionScriptIndex()
    for root in roots:
        if not root or not root.is_dir():
            continue
        loaded = False
        missions_dir = root / "missions"
        if missions_dir.is_dir():
            for path in sorted(missions_dir.rglob("*.txt")):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for mid, events in index_missions_file(text).items():
                    # 后者覆盖（Mod 优先：roots 顺序应为本体在前、Mod 在后）
                    idx.mission_events[mid] = events
                loaded = True
        events_dir = root / "events"
        if events_dir.is_dir():
            for path in sorted(events_dir.rglob("*.txt")):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for eid, keys in index_events_file(text).items():
                    idx.event_keys[eid] = keys
                loaded = True
        if loaded:
            idx.sources.append(str(root))
    return idx


def content_roots(
    *,
    game_dir: Path | None,
    paradox_docs: Path | None,
) -> list[Path]:
    roots: list[Path] = []
    if game_dir is not None and game_dir.is_dir():
        roots.append(game_dir)
    roots.extend(enabled_mod_paths(paradox_docs))
    return roots


@lru_cache
def get_mission_script_index(
    game_dir: str | None = None,
    paradox_docs: str | None = None,
) -> MissionScriptIndex:
    gd = Path(game_dir) if game_dir else None
    pd = Path(paradox_docs) if paradox_docs else None
    return build_mission_script_index(content_roots(game_dir=gd, paradox_docs=pd))

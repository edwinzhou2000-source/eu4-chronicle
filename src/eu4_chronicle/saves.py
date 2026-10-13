"""存档列表排序、自动档判定与默认选档。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence


_EXACT_AUTOSAVE_STEMS = frozenset(
    {
        "autosave",
        "old_autosave",
        "older_autosave",
        "exitautosave",
    }
)


def is_autosave_name(name: str) -> bool:
    """按文件名判断是否为 EU4 自动存档（大小写不敏感）。"""
    stem = Path(name).stem.strip().lower()
    if not stem:
        return False
    if stem in _EXACT_AUTOSAVE_STEMS:
        return True
    # autosave 123 / Autosave_1 等编号变体
    if stem.startswith("autosave"):
        return True
    return False


def sort_save_entries(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """按 mtime 降序；同秒按文件名稳定排序。"""
    return sorted(
        (dict(e) for e in entries),
        key=lambda e: (-float(e.get("mtime") or 0.0), str(e.get("name") or "")),
    )


def pick_default_saves(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[str | None, str | None]:
    """从已排序（新→旧）列表中取默认 prev/curr 文件名。

    优先两个最新人工档；仅一人造档则两者同名；无人造档则退回全体最新/次新。
    """
    if not entries:
        return None, None
    names = [str(e["name"]) for e in entries if e.get("name")]
    if not names:
        return None, None

    manual = [n for n in names if not is_autosave_name(n)]
    pool = manual if manual else names
    curr = pool[0]
    prev = pool[1] if len(pool) > 1 else pool[0]
    return prev, curr


def list_eu4_files(directory: Path) -> list[dict[str, Any]]:
    """扫描目录中的 .eu4，附带 mtime/size/autosave，并按 mtime 降序。"""
    entries: list[dict[str, Any]] = []
    for f in directory.glob("*.eu4"):
        if not f.is_file():
            continue
        st = f.stat()
        entries.append(
            {
                "name": f.name,
                "path": str(f),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "autosave": is_autosave_name(f.name),
            }
        )
    return sort_save_entries(entries)

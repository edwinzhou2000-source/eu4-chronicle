"""存档排序、自动档判定与默认选档。"""

from __future__ import annotations

import os
import time
from pathlib import Path

from eu4_chronicle.saves import (
    is_autosave_name,
    list_eu4_files,
    pick_default_saves,
    sort_save_entries,
)


def test_is_autosave_name() -> None:
    assert is_autosave_name("autosave.eu4")
    assert is_autosave_name("Autosave.eu4")
    assert is_autosave_name("old_autosave.eu4")
    assert is_autosave_name("older_autosave.eu4")
    assert is_autosave_name("ExitAutosave.eu4")
    assert is_autosave_name("autosave 927.eu4")
    assert is_autosave_name("autosave_1.eu4")
    assert not is_autosave_name("Teutonic_Order1454.eu4")
    assert not is_autosave_name("my_autosave_backup.eu4")  # 不以 autosave 开头
    assert not is_autosave_name("run_autosave_copy.eu4")


def test_pick_default_skips_autosave() -> None:
    entries = sort_save_entries(
        [
            {"name": "autosave.eu4", "mtime": 300},
            {"name": "manual_new.eu4", "mtime": 200},
            {"name": "manual_old.eu4", "mtime": 100},
            {"name": "old_autosave.eu4", "mtime": 250},
        ]
    )
    prev, curr = pick_default_saves(entries)
    assert curr == "manual_new.eu4"
    assert prev == "manual_old.eu4"


def test_pick_default_single_manual() -> None:
    entries = [
        {"name": "autosave.eu4", "mtime": 2},
        {"name": "only.eu4", "mtime": 1},
    ]
    prev, curr = pick_default_saves(sort_save_entries(entries))
    assert prev == "only.eu4"
    assert curr == "only.eu4"


def test_pick_default_all_autosave_fallback() -> None:
    entries = sort_save_entries(
        [
            {"name": "autosave.eu4", "mtime": 3},
            {"name": "old_autosave.eu4", "mtime": 2},
            {"name": "older_autosave.eu4", "mtime": 1},
        ]
    )
    prev, curr = pick_default_saves(entries)
    assert curr == "autosave.eu4"
    assert prev == "old_autosave.eu4"


def test_list_eu4_files_mtime_and_flags(tmp_path: Path) -> None:
    older = tmp_path / "alpha.eu4"
    newer = tmp_path / "zeta.eu4"
    auto = tmp_path / "autosave.eu4"
    older.write_text("old", encoding="utf-8")
    time.sleep(0.02)
    newer.write_text("new", encoding="utf-8")
    time.sleep(0.02)
    auto.write_text("auto", encoding="utf-8")
    # 保证 mtime 顺序（部分文件系统精度不够时强制 touch）
    now = time.time()
    os.utime(older, (now - 20, now - 20))
    os.utime(newer, (now - 10, now - 10))
    os.utime(auto, (now, now))

    files = list_eu4_files(tmp_path)
    names = [f["name"] for f in files]
    assert names == ["autosave.eu4", "zeta.eu4", "alpha.eu4"]
    assert files[0]["autosave"] is True
    assert files[1]["autosave"] is False

    prev, curr = pick_default_saves(files)
    assert curr == "zeta.eu4"
    assert prev == "alpha.eu4"

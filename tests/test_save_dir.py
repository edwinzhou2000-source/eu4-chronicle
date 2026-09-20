"""存档目录解析：空 EU4_SAVE_DIR 不落成「.」；WSL 探测 Windows 路径。"""

from __future__ import annotations

from pathlib import Path

import pytest

from eu4_chronicle import config
from eu4_chronicle.config import (
    Settings,
    format_save_dir,
    resolve_default_save_dir,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_blank_env_save_dir_not_dot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EU4_SAVE_DIR", "")
    monkeypatch.setattr(config, "resolve_default_save_dir", lambda: (tmp_path / "saves").resolve())
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert str(s.save_dir) != "."
    assert s.save_dir == (tmp_path / "saves").resolve()


def test_missing_env_uses_resolver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("EU4_SAVE_DIR", raising=False)
    target = (tmp_path / "Paradox Interactive" / "Europa Universalis IV" / "save games").resolve()
    monkeypatch.setattr(config, "resolve_default_save_dir", lambda: target)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.save_dir == target


def test_explicit_save_dir_honored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom_saves"
    custom.mkdir()
    monkeypatch.setenv("EU4_SAVE_DIR", str(custom))
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.save_dir == custom.resolve()


def test_resolve_prefers_dir_with_eu4(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with_files = tmp_path / "with_files"
    with_files.mkdir()
    (with_files / "a.eu4").write_text("x", encoding="utf-8")

    monkeypatch.setattr(config, "_is_wsl", lambda: True)
    monkeypatch.setattr(
        config,
        "iter_default_save_dir_candidates",
        lambda: [empty, with_files],
    )
    assert resolve_default_save_dir() == with_files.resolve()


def test_resolve_existing_without_eu4(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    only_dir = tmp_path / "save games"
    only_dir.mkdir()
    missing = tmp_path / "missing" / "save games"
    monkeypatch.setattr(config, "_is_wsl", lambda: True)
    monkeypatch.setattr(
        config,
        "iter_default_save_dir_candidates",
        lambda: [missing, only_dir],
    )
    assert resolve_default_save_dir() == only_dir.resolve()


def test_resolve_never_returns_dot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing = tmp_path / "nope" / "save games"
    monkeypatch.setattr(config, "_is_wsl", lambda: True)
    monkeypatch.setattr(config, "iter_default_save_dir_candidates", lambda: [missing])
    got = resolve_default_save_dir()
    assert str(got) != "."
    assert got.is_absolute()
    assert "save games" in str(got)


def test_format_save_dir_rejects_dot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fallback = (tmp_path / "fallback").resolve()
    monkeypatch.setattr(config, "resolve_default_save_dir", lambda: fallback)
    assert format_save_dir(Path(".")) == str(fallback)


def test_wsl_candidates_include_mnt_c(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_is_wsl", lambda: True)
    monkeypatch.setattr(config, "_windows_usernames", lambda: ["edwin"])
    cands = config.iter_default_save_dir_candidates()
    texts = [str(p) for p in cands]
    assert any(
        p.endswith(
            "/mnt/c/Users/edwin/Documents/Paradox Interactive/Europa Universalis IV/save games"
        )
        or "/mnt/c/Users/edwin/Documents/Paradox Interactive/Europa Universalis IV/save games"
        in p
        for p in texts
    )
    assert any("OneDrive" in p for p in texts)

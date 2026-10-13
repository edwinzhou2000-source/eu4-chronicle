"""HTTP UI / health 冒烟：确认前端与现有 API 同服。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from eu4_chronicle.server import app


def test_ui_index_served() -> None:
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    body = res.text
    assert "EU4 战报" in body
    # 硬约束：UI 不得提供 Key 输入框（仅文案提示从 .env 读取）
    assert 'type="password"' not in body
    assert 'name="api' not in body.lower()
    assert "id=\"api" not in body.lower()
    assert ".env" in body
    # 存档目录仅展示，不可前端改路径
    assert 'id="save-dir"' in body
    assert 'id="save-dir-input"' not in body
    assert 'id="browse-btn"' not in body
    assert "EU4_SAVE_DIR" in body
    # 主路径是 LLM；Mock 折叠；全球事件不进主 UI
    assert 'value="llm"' in body
    assert "离线 / 无 Key" in body
    assert "包含全球无关事件" not in body
    assert 'id="include-global"' not in body


def test_health_still_ok() -> None:
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "mode" in data
    assert "has_api_key" in data
    assert isinstance(data["has_api_key"], bool)
    assert "save_dir" in data
    assert "save_dir_override" not in data


def test_saves_with_samples(monkeypatch, tmp_path: Path) -> None:
    samples = Path(__file__).resolve().parents[1] / "samples"
    monkeypatch.setenv("EU4_SAVE_DIR", str(samples))
    from eu4_chronicle import config

    config.get_settings.cache_clear()
    try:
        client = TestClient(app)
        res = client.get("/saves")
        assert res.status_code == 200
        data = res.json()
        names = {f["name"] for f in data["files"]}
        assert "byz_1444.eu4" in names
        assert "byz_1453.eu4" in names
        assert data["default_prev"] in names
        assert data["default_curr"] in names
        mtimes = [f["mtime"] for f in data["files"]]
        assert mtimes == sorted(mtimes, reverse=True)
    finally:
        config.get_settings.cache_clear()


def test_saves_default_skips_autosave(monkeypatch, tmp_path: Path) -> None:
    import os
    import time

    from eu4_chronicle import config

    older = tmp_path / "manual_old.eu4"
    newer = tmp_path / "manual_new.eu4"
    auto = tmp_path / "autosave.eu4"
    older.write_bytes(b"old")
    newer.write_bytes(b"new")
    auto.write_bytes(b"auto")
    now = time.time()
    os.utime(older, (now - 30, now - 30))
    os.utime(newer, (now - 10, now - 10))
    os.utime(auto, (now, now))

    monkeypatch.setenv("EU4_SAVE_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    try:
        client = TestClient(app)
        res = client.get("/saves")
        assert res.status_code == 200
        data = res.json()
        assert [f["name"] for f in data["files"]] == [
            "autosave.eu4",
            "manual_new.eu4",
            "manual_old.eu4",
        ]
        assert data["files"][0]["autosave"] is True
        assert data["default_curr"] == "manual_new.eu4"
        assert data["default_prev"] == "manual_old.eu4"
    finally:
        config.get_settings.cache_clear()

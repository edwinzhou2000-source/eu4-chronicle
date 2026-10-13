"""桌面入口平台分支：WSL/无 GUI 浏览器回退、Windows WebView2。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from eu4_game_report import desktop


def test_is_wsl_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert desktop.is_wsl() is True


def test_is_wsl_proc_version(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)
    proc = tmp_path / "version"
    proc.write_text("Linux version 5.15.0-microsoft-standard-WSL2", encoding="utf-8")
    real_open = open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/proc/version":
            return real_open(proc, *args, **kwargs)
        raise AssertionError(path)

    monkeypatch.setattr("builtins.open", fake_open)
    assert desktop.is_wsl() is True


def test_is_wsl_false_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert desktop.is_wsl() is False


def test_has_gui_display_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert desktop.has_gui_display() is False
    monkeypatch.setenv("DISPLAY", ":0")
    assert desktop.has_gui_display() is True


def test_prefer_browser_fallback_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop, "is_wsl", lambda: True)
    monkeypatch.setattr(desktop, "has_gui_display", lambda: True)
    assert desktop.prefer_browser_fallback() is True


def test_prefer_browser_fallback_no_display(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop, "is_wsl", lambda: False)
    monkeypatch.setattr(desktop, "has_gui_display", lambda: False)
    assert desktop.prefer_browser_fallback() is True


def test_start_webview_windows_edgechromium(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    class FakeWebview:
        @staticmethod
        def create_window(*args, **kwargs):
            calls.append(("create", args, kwargs))
            return SimpleNamespace()

        @staticmethod
        def start(**kwargs):
            calls.append(("start", kwargs))

    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "webview", FakeWebview)
    desktop.start_webview("http://127.0.0.1:18765/")
    assert calls[0][0] == "create"
    assert calls[1] == ("start", {"gui": "edgechromium"})


def test_start_webview_windows_fallback_mshtml(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    class FakeWebview:
        @staticmethod
        def create_window(*args, **kwargs):
            return SimpleNamespace()

        @staticmethod
        def start(**kwargs):
            calls.append(kwargs)
            if kwargs.get("gui") == "edgechromium":
                raise RuntimeError("no webview2")

    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "webview", FakeWebview)
    desktop.start_webview("http://127.0.0.1:18765/")
    assert calls == [{"gui": "edgechromium"}, {"gui": "mshtml"}]


def test_run_browser_fallback_blocks_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    stopped: list[bool] = []
    printed: list[str] = []

    monkeypatch.setattr(desktop, "open_ui_url", lambda url, *, wsl=None: opened.append(url))
    monkeypatch.setattr(desktop, "_stop_server", lambda: stopped.append(True))
    monkeypatch.setattr(desktop, "wait_until_user_stop", lambda: None)
    monkeypatch.setattr(
        "builtins.print",
        lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
    )

    desktop.run_browser_fallback("http://127.0.0.1:18765/", owned=True, wsl=True)
    assert opened == ["http://127.0.0.1:18765/"]
    assert stopped == [True]
    joined = "\n".join(printed)
    assert "选档页" in joined


def test_wait_until_user_stop_tty_uses_input(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(desktop, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: called.append("in") or "")
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    desktop.wait_until_user_stop()
    assert called == ["in"]


def test_wait_until_user_stop_notty_sleeps_until_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    def fake_sleep(secs: float) -> None:
        sleeps.append(secs)
        raise KeyboardInterrupt

    monkeypatch.setattr(desktop, "_stdin_is_tty", lambda: False)
    monkeypatch.setattr(desktop.time, "sleep", fake_sleep)
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    desktop.wait_until_user_stop()
    assert sleeps == [3600.0]


def test_open_ui_url_wsl_uses_cmd_start(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[object] = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(desktop.subprocess, "run", fake_run)
    desktop.open_ui_url("http://127.0.0.1:18765/", wsl=True)
    assert runs == [["cmd.exe", "/c", "start", "", "http://127.0.0.1:18765/"]]


def test_main_uses_browser_when_prefer_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    monkeypatch.setattr(
        desktop,
        "get_settings",
        lambda: SimpleNamespace(host="127.0.0.1", port=18765),
    )
    monkeypatch.setattr(
        desktop,
        "ensure_server",
        lambda host, port: ("http://127.0.0.1:18765/", True),
    )
    monkeypatch.setattr(desktop, "prefer_browser_fallback", lambda: True)

    def fake_browser(url, *, owned, wsl=None):
        called["url"] = url
        called["owned"] = owned

    monkeypatch.setattr(desktop, "run_browser_fallback", fake_browser)
    desktop.main()
    assert called == {"url": "http://127.0.0.1:18765/", "owned": True}


def test_main_webview_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    monkeypatch.setattr(
        desktop,
        "get_settings",
        lambda: SimpleNamespace(host="127.0.0.1", port=18765),
    )
    monkeypatch.setattr(
        desktop,
        "ensure_server",
        lambda host, port: ("http://127.0.0.1:18765/", False),
    )
    monkeypatch.setattr(desktop, "prefer_browser_fallback", lambda: False)
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace())
    monkeypatch.setattr(
        desktop,
        "start_webview",
        lambda url: (_ for _ in ()).throw(ImportError("No module named 'gi'")),
    )

    def fake_browser(url, *, owned, wsl=None):
        called["url"] = url
        called["owned"] = owned

    monkeypatch.setattr(desktop, "run_browser_fallback", fake_browser)
    desktop.main()
    assert called == {"url": "http://127.0.0.1:18765/", "owned": False}

"""桌面入口：后台拉起本机 FastAPI，并用 pywebview（或浏览器回退）打开选档界面。"""

from __future__ import annotations

import atexit
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from typing import Optional

import uvicorn

from eu4_chronicle.config import get_settings
from eu4_chronicle.server import app as fastapi_app

_server: Optional[uvicorn.Server] = None
_thread: Optional[threading.Thread] = None

_BROWSER_HINT = (
    "在 WSL / 无桌面窗环境下无法打开原生窗口，已用系统浏览器打开选档页；"
    "回车或 Ctrl+C 退出并停服。"
)
_WSL_HINT = (
    "检测到 WSL。请优先用 Windows 资源管理器双击 scripts\\EU4战报.bat（或 EU4战报.cmd），"
    "不要在 WSL 里 uv run eu4-chronicle-desktop。"
)


def _wait_for_health(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if 200 <= getattr(resp, "status", 200) < 300:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
            time.sleep(0.15)
    raise RuntimeError(f"本机服务未在 {timeout:.0f}s 内就绪: {url}") from last_err


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) != 0


def _start_server(host: str, port: int) -> None:
    global _server, _thread
    config = uvicorn.Config(
        fastapi_app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    _server = uvicorn.Server(config)

    def _run() -> None:
        assert _server is not None
        _server.run()

    _thread = threading.Thread(target=_run, name="eu4-chronicle-uvicorn", daemon=True)
    _thread.start()


def _stop_server() -> None:
    global _server, _thread
    if _server is not None:
        _server.should_exit = True
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=8.0)
    _server = None
    _thread = None


def is_wsl() -> bool:
    """是否运行在 WSL（无可靠 Win32 WebView2 / GTK 桌面时）。"""
    if sys.platform != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version", encoding="utf-8") as fh:
            text = fh.read().lower()
    except OSError:
        return False
    return "microsoft" in text or "wsl" in text


def has_gui_display() -> bool:
    """Linux 是否有可用 DISPLAY；Windows / macOS 视为有桌面能力。"""
    if sys.platform in {"win32", "darwin"}:
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def prefer_browser_fallback() -> bool:
    """WSL 或无 GUI 时直接走浏览器，避免 pywebview 因缺 gi/QT 崩掉。"""
    return is_wsl() or not has_gui_display()


def start_webview(ui_url: str) -> None:
    """打开原生窗口。Windows 优先 Edge WebView2，失败再试 MSHTML。"""
    import webview

    webview.create_window(
        "EU4 战报",
        ui_url,
        width=980,
        height=820,
        min_size=(720, 560),
    )
    if sys.platform == "win32":
        try:
            webview.start(gui="edgechromium")
            return
        except Exception as edge_exc:  # noqa: BLE001 — 后端探测需吞掉再试
            print(
                f"Edge WebView2 不可用（{edge_exc}），尝试 MSHTML…",
                file=sys.stderr,
            )
            webview.start(gui="mshtml")
            return
    webview.start()


def run_browser_fallback(ui_url: str, *, owned: bool, wsl: bool | None = None) -> None:
    """无原生窗时：打开系统浏览器并阻塞到用户结束，再按需停服。"""
    if wsl is None:
        wsl = is_wsl()
    if wsl:
        print(_WSL_HINT, file=sys.stderr)
    webbrowser.open(ui_url)
    print(_BROWSER_HINT)
    print(f"选档页：{ui_url}")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        print()
    finally:
        if owned:
            _stop_server()


def ensure_server(host: str, port: int) -> tuple[str, bool]:
    """确保本机服务可用；返回 (ui_url, owned)。owned=True 表示本进程拉起的服务。"""
    base = f"http://{host}:{port}"
    health_url = f"{base}/health"
    ui_url = f"{base}/"

    already_up = False
    try:
        with urllib.request.urlopen(health_url, timeout=1.0) as resp:
            already_up = 200 <= getattr(resp, "status", 200) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        already_up = False

    owned = False
    if not already_up:
        if not _port_free(host, port):
            print(
                f"端口 {host}:{port} 已被占用且 /health 不可用。"
                "请关闭占用进程，或设置 EU4_CHRONICLE_PORT。",
                file=sys.stderr,
            )
            raise SystemExit(2)
        _start_server(host, port)
        owned = True
        atexit.register(_stop_server)
        try:
            _wait_for_health(health_url)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            _stop_server()
            raise SystemExit(3) from exc
    return ui_url, owned


def main() -> None:
    """启动本机服务并打开桌面窗口（或浏览器回退）；结束后按需停服。"""
    settings = get_settings()
    host = settings.host or "127.0.0.1"
    port = int(settings.port or 18765)
    ui_url, owned = ensure_server(host, port)

    if prefer_browser_fallback():
        run_browser_fallback(ui_url, owned=owned)
        return

    try:
        import webview  # noqa: F401
    except ImportError:
        print(
            "未安装桌面依赖。请执行：uv sync --extra desktop\n"
            "然后再运行：uv run eu4-chronicle-desktop\n"
            "（Linux/WSL 无 GTK 时也会自动改用浏览器。）",
            file=sys.stderr,
        )
        # 无 pywebview 时仍给浏览器回退，避免纯命令行环境直接崩
        run_browser_fallback(ui_url, owned=owned)
        return

    try:
        start_webview(ui_url)
    except Exception as exc:  # noqa: BLE001 — 任意 GUI 后端失败都回退
        print(
            f"桌面窗口启动失败（{exc}）。已改用系统浏览器。\n"
            "Windows 请用资源管理器双击 scripts\\EU4战报.bat；"
            "WSL 请勿在此环境强开 pywebview。",
            file=sys.stderr,
        )
        run_browser_fallback(ui_url, owned=owned)
        return

    if owned:
        _stop_server()


if __name__ == "__main__":
    main()

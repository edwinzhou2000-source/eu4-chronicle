"""桌面入口：后台拉起本机 FastAPI，并用 pywebview 打开选档界面。"""

from __future__ import annotations

import atexit
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

import uvicorn

from eu4_chronicle.config import get_settings
from eu4_chronicle.server import app as fastapi_app

_server: Optional[uvicorn.Server] = None
_thread: Optional[threading.Thread] = None


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


def main() -> None:
    """启动本机服务并打开桌面窗口；关窗后停服。"""
    try:
        import webview
    except ImportError:
        print(
            "未安装桌面依赖。请执行：uv sync --extra desktop\n"
            "然后再运行：uv run eu4-chronicle-desktop",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    settings = get_settings()
    host = settings.host or "127.0.0.1"
    port = int(settings.port or 18765)
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

    window = webview.create_window(
        "EU4 战报",
        ui_url,
        width=980,
        height=820,
        min_size=(720, 560),
    )
    try:
        webview.start()
    finally:
        # webview.start 返回即窗口已关
        del window
        if owned:
            _stop_server()


if __name__ == "__main__":
    main()

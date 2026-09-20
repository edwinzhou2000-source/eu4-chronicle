@echo off
setlocal EnableExtensions
REM ============================================================
REM  EU4 战报 — Windows 双击启动器
REM
REM  请用「Windows 资源管理器」双击本文件（或放到桌面的快捷方式）。
REM  不要在 WSL / bash 里执行本 bat，也不要在 WSL 里：
REM      uv run eu4-chronicle-desktop
REM  否则会走到 Linux Python + pywebview，因缺少 GTK/gi 报错。
REM
REM  本脚本刻意走 Windows 的 cmd / PATH（uv / python），以启用
REM  Win32 WebView2（edgechromium）。
REM ============================================================

cd /d "%~dp0.."

REM 若被错误地从 WSL 调起，尽量给出提示（WSL 下偶发能见到 %WSL_DISTRO_NAME%）
if defined WSL_DISTRO_NAME (
  echo [提示] 检测到 WSL 环境变量。请改用 Windows 资源管理器双击本 bat，
  echo        或在资源管理器地址栏打开本仓库 scripts 目录。
  echo        若坚持在 WSL 跑，程序会回退到系统浏览器，而不是原生窗。
  echo.
)

where uv >nul 2>nul
if errorlevel 1 (
  REM 常见用户级安装路径
  if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
  ) else if exist "%LOCALAPPDATA%\Programs\uv\uv.exe" (
    set "PATH=%LOCALAPPDATA%\Programs\uv;%PATH%"
  )
)

where uv >nul 2>nul
if errorlevel 1 (
  echo 未找到 Windows 的 uv。请先安装 https://github.com/astral-sh/uv
  echo 并确保 uv.exe 在 PATH 中，然后再用资源管理器双击本文件。
  pause
  exit /b 1
)

uv sync --extra desktop --extra llm
if errorlevel 1 (
  echo 依赖安装失败。
  pause
  exit /b 1
)

uv run eu4-chronicle-desktop
if errorlevel 1 (
  echo 桌面端退出异常。请确认已配置 .env（LLM 模式需要 OPENAI_API_KEY），且端口 18765 空闲。
  echo 若仍报 gi / GTK / QT：说明当前不是 Win32 Python——请用资源管理器双击本 bat，勿在 WSL 执行。
  pause
  exit /b 1
)

endlocal

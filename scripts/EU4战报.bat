@echo off
setlocal EnableExtensions
REM ============================================================
REM  [已弃用路径] scripts\EU4战报.bat
REM
REM  仓库若在 WSL：不要在资源管理器打开 \\wsl$\... 再双击本文件。
REM  那样常弹出「如何打开」（正常 / Microsoft Store），选「正常」后无反应。
REM
REM  正确做法（在 WSL 终端执行一次安装）：
REM      cd ~/genesis
REM      bash scripts/install-desktop-shortcut.sh
REM  然后只双击 Windows 桌面上的「EU4战报.cmd」
REM  （路径形如 C:\Users\<你>\Desktop\EU4战报.cmd，不是 \\wsl$）。
REM
REM  本 bat 仅留给「仓库本身就在 Windows NTFS」的旧用法；能跑就继续，
REM  否则请改用上面的桌面安装脚本。
REM ============================================================

cd /d "%~dp0.."

if defined WSL_DISTRO_NAME (
  echo [提示] 检测到 WSL。请勿依赖本 bat。
  echo        请在 WSL 执行: bash scripts/install-desktop-shortcut.sh
  echo        然后只双击 Windows 桌面上的 EU4战报.cmd。
  echo.
)

where uv >nul 2>nul
if errorlevel 1 (
  if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
  ) else if exist "%LOCALAPPDATA%\Programs\uv\uv.exe" (
    set "PATH=%LOCALAPPDATA%\Programs\uv;%PATH%"
  )
)

where uv >nul 2>nul
if errorlevel 1 (
  echo 未找到 Windows 的 uv。推荐改用桌面快捷方式（经 WSL 调 uv）：
  echo   在 WSL: bash scripts/install-desktop-shortcut.sh
  echo 若坚持本 bat：请先安装 https://github.com/astral-sh/uv 并把 uv.exe 加入 PATH。
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
  echo 若仍报 gi / GTK / QT：请改用桌面 EU4战报.cmd（WSL 安装脚本生成）。
  pause
  exit /b 1
)

endlocal

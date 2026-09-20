@echo off
setlocal
REM 双击启动 EU4 战报桌面窗口（自动启停本机服务）
REM 工作目录固定为仓库根，以便读取根目录 .env（API Key / 存档路径）
cd /d "%~dp0.."

where uv >nul 2>nul
if errorlevel 1 (
  echo 未找到 uv。请先安装 https://github.com/astral-sh/uv 并确保在 PATH 中。
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
  pause
  exit /b 1
)

endlocal

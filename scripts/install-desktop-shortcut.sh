#!/usr/bin/env bash
# 从 WSL 一键在 Windows 真实桌面写入「EU4战报.cmd」（可重复执行覆盖）。
# 用法（在仓库根）:
#   bash scripts/install-desktop-shortcut.sh
# 可选环境变量:
#   EU4_WSL_DISTRO   指定发行版（默认 $WSL_DISTRO_NAME）
#   EU4_REPO_PATH    指定仓库 Linux 路径（默认本脚本所在 git 根）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if command -v git >/dev/null 2>&1; then
  git_root="$(git -C "$REPO_ROOT" rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -n "$git_root" ]]; then
    REPO_ROOT="$git_root"
  fi
fi
REPO_PATH="${EU4_REPO_PATH:-$REPO_ROOT}"
# 烘焙绝对路径（解析 symlink）
REPO_PATH="$(cd "$REPO_PATH" && pwd)"

if [[ ! -f "$REPO_PATH/pyproject.toml" ]]; then
  echo "错误：找不到仓库 pyproject.toml：$REPO_PATH" >&2
  exit 1
fi
if [[ ! -f "$REPO_PATH/scripts/launch-desktop-from-windows.sh" ]]; then
  echo "错误：缺少 scripts/launch-desktop-from-windows.sh" >&2
  exit 1
fi

DISTRO="${EU4_WSL_DISTRO:-${WSL_DISTRO_NAME:-}}"
if [[ -z "$DISTRO" ]]; then
  # 优先带 * 的默认发行版；否则第一项。输出可能是 UTF-16。
  DISTRO="$(
    wsl.exe -l -v 2>/dev/null | tr -d '\0\r' | awk '
      NR>1 && $0 ~ /\*/ { gsub(/^\*[[:space:]]*/, "", $1); print $1; exit }
      NR==2 { print $1; exit }
    ' || true
  )"
fi
if [[ -z "$DISTRO" ]]; then
  DISTRO="$(wsl.exe -l -q 2>/dev/null | tr -d '\0\r' | sed '/^$/d' | head -n1 || true)"
fi
if [[ -z "$DISTRO" ]]; then
  echo "错误：无法探测 WSL 发行版。请设置 EU4_WSL_DISTRO=你的发行版名" >&2
  exit 1
fi
# 去掉首尾空白
DISTRO="$(echo "$DISTRO" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

win_userprofile="$(cmd.exe /c "echo %USERPROFILE%" 2>/dev/null | tr -d '\r')"
if [[ -z "$win_userprofile" ]]; then
  echo "错误：无法读取 %USERPROFILE%。请确认在 WSL 且 Windows 互通正常。" >&2
  exit 1
fi

desktop_win="${win_userprofile}\\Desktop"
desktop_wsl="$(wslpath -u "$desktop_win" 2>/dev/null || true)"
if [[ -z "$desktop_wsl" || ! -d "$desktop_wsl" ]]; then
  desktop_win="${win_userprofile}\\OneDrive\\Desktop"
  desktop_wsl="$(wslpath -u "$desktop_win" 2>/dev/null || true)"
fi
if [[ -z "$desktop_wsl" || ! -d "$desktop_wsl" ]]; then
  echo "错误：找不到 Windows 桌面目录（试过 Desktop / OneDrive\\Desktop）。" >&2
  exit 1
fi

cmd_path="$desktop_wsl/EU4战报.cmd"
repo_q="${REPO_PATH//\'/\'\\\'\'}"
launcher="scripts/launch-desktop-from-windows.sh"

# 生成的 .cmd：失败必 pause；成功时由 WSL 内进程阻塞，黑框保持到结束后再 pause
cat > "$cmd_path" <<EOF
@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title EU4 战报
echo ========================================
echo   EU4 战报 — 经 WSL 启动
echo ========================================
echo 发行版: ${DISTRO}
echo 仓库:   ${REPO_PATH}
echo.
echo 请保持本窗口打开，直到选档页出现。
echo 结束请在本窗口按 Ctrl+C，或关闭本窗口。
echo.

where wsl.exe >nul 2>nul
if errorlevel 1 (
  echo [错误] 找不到 wsl.exe。请先启用 Windows 的 WSL。
  echo.
  pause
  exit /b 1
)

wsl.exe -d ${DISTRO} -e bash -lc "export EU4_REPO_PATH='${repo_q}'; cd '${repo_q}' || exit 10; exec bash './${launcher}'"
set "ERR=%ERRORLEVEL%"

echo.
if not "%ERR%"=="0" (
  echo [失败] WSL 启动退出码 %ERR%。
  echo 常见原因：
  echo   1. 发行版名不对（当前: ${DISTRO}）
  echo   2. 仓库路径不对（当前: ${REPO_PATH}）
  echo   3. WSL 里没有 uv（需装到 ~/.local/bin）
  echo   4. 未 uv sync --extra desktop --extra llm
  echo.
  echo 请在 WSL 重装快捷方式：
  echo   cd '${repo_q}' ^&^& bash scripts/install-desktop-shortcut.sh
  echo.
  pause
  exit /b %ERR%
)

echo [结束] 进程已退出。若选档页未打开，请手动访问 http://127.0.0.1:18765/
echo.
pause
endlocal
EOF

if command -v powershell.exe >/dev/null 2>&1; then
  cmd_win="$(wslpath -w "$cmd_path" 2>/dev/null || true)"
  if [[ -n "$cmd_win" ]]; then
    powershell.exe -NoProfile -Command \
      "Unblock-File -LiteralPath '$cmd_win'; exit 0" \
      >/dev/null 2>&1 || true
  fi
fi

echo "已写入/覆盖桌面快捷方式："
echo "  ${desktop_win}\\EU4战报.cmd"
echo "  （WSL 可见：${cmd_path}）"
echo "发行版: ${DISTRO}"
echo "仓库:   ${REPO_PATH}"
echo
echo "请只双击桌面上的「EU4战报.cmd」。黑框应保持到选档页出现；失败会 pause 显示原因。"

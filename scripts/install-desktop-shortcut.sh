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

# Desktop .cmd MUST be ASCII-only + CRLF.
# Chinese Windows cmd.exe defaults to GBK/CP936; UTF-8 Chinese becomes mojibake
# and splits lines so fragments are executed as commands.
# Keep Chinese in this installer stdout / README only — never inside the .cmd body.
tmp_cmd="$(mktemp)"
# LF here; convert to CRLF below. All bytes must be ASCII.
cat > "$tmp_cmd" <<EOF
@echo off
setlocal EnableExtensions
title EU4 Chronicle
echo ========================================
echo   EU4 Chronicle - launch via WSL
echo ========================================
echo Distro: ${DISTRO}
echo Repo:   ${REPO_PATH}
echo.
echo Keep this window open until the UI opens.
echo Stop with Ctrl+C in this window, or close it.
echo.

where wsl.exe >nul 2>nul
if errorlevel 1 (
  echo [ERROR] wsl.exe not found. Enable WSL on Windows first.
  echo.
  pause
  exit /b 1
)

wsl.exe -d ${DISTRO} -e bash -lc "export EU4_REPO_PATH='${repo_q}'; cd '${repo_q}' || exit 10; exec bash './${launcher}'"
set "ERR=%ERRORLEVEL%"

echo.
if not "%ERR%"=="0" (
  echo [FAILED] WSL exited with code %ERR%.
  echo Common causes:
  echo   1. Wrong distro name (now: ${DISTRO})
  echo   2. Wrong repo path (now: ${REPO_PATH})
  echo   3. uv missing in WSL (install to ~/.local/bin)
  echo   4. Need: uv sync --extra desktop --extra llm
  echo.
  echo Reinstall shortcut from WSL:
  echo   cd '${repo_q}' ^&^& bash scripts/install-desktop-shortcut.sh
  echo.
  pause
  exit /b %ERR%
)

echo [DONE] Process exited. If UI did not open, open http://127.0.0.1:18765/
echo.
pause
endlocal
EOF

# Validate ASCII (reject any non-ASCII so GBK mangling cannot recur)
non_ascii="$(LC_ALL=C tr -d '\0-\177' < "$tmp_cmd" | wc -c | tr -d ' ')"
if [[ "${non_ascii}" != "0" ]]; then
  echo "错误：生成的 .cmd 含非 ASCII 字符，已中止写入。" >&2
  rm -f "$tmp_cmd"
  exit 1
fi

# Write CRLF (pure ASCII)
sed 's/$/\r/' "$tmp_cmd" > "$cmd_path"
rm -f "$tmp_cmd"

if command -v powershell.exe >/dev/null 2>&1; then
  cmd_win="$(wslpath -w "$cmd_path" 2>/dev/null || true)"
  if [[ -n "$cmd_win" ]]; then
    powershell.exe -NoProfile -Command \
      "Unblock-File -LiteralPath '$cmd_win'; exit 0" \
      >/dev/null 2>&1 || true
  fi
fi

echo "已写入/覆盖桌面快捷方式（.cmd 正文为 ASCII 英文，避免 GBK 乱码）："
echo "  ${desktop_win}\\EU4战报.cmd"
echo "  （WSL 可见：${cmd_path}）"
echo "发行版: ${DISTRO}"
echo "仓库:   ${REPO_PATH}"
echo
echo "请只双击桌面上的「EU4战报.cmd」。黑框应为英文提示；失败会 pause。"

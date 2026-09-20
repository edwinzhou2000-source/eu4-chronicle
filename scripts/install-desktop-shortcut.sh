#!/usr/bin/env bash
# 从 WSL 一键在 Windows 真实桌面写入「EU4战报.cmd」。
# 用法（在仓库根）:
#   bash scripts/install-desktop-shortcut.sh
# 可选环境变量:
#   EU4_WSL_DISTRO   指定发行版（默认 $WSL_DISTRO_NAME 或 wsl -l -q 第一项）
#   EU4_REPO_PATH    指定仓库 Linux 路径（默认本脚本所在仓库根）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_PATH="${EU4_REPO_PATH:-$REPO_ROOT}"

if [[ ! -f "$REPO_PATH/pyproject.toml" ]]; then
  echo "错误：找不到仓库 pyproject.toml：$REPO_PATH" >&2
  exit 1
fi

DISTRO="${EU4_WSL_DISTRO:-${WSL_DISTRO_NAME:-}}"
if [[ -z "$DISTRO" ]]; then
  # wsl -l -q 在 WSL 内也可调；输出可能带 CRLF / UTF-16 空字节
  DISTRO="$(wsl.exe -l -q 2>/dev/null | tr -d '\0\r' | sed '/^$/d' | head -n1 || true)"
fi
if [[ -z "$DISTRO" ]]; then
  echo "错误：无法探测 WSL 发行版。请设置 EU4_WSL_DISTRO=你的发行版名" >&2
  exit 1
fi

# 解析 Windows 桌面路径 → WSL 可写路径
win_userprofile="$(cmd.exe /c "echo %USERPROFILE%" 2>/dev/null | tr -d '\r')"
if [[ -z "$win_userprofile" ]]; then
  echo "错误：无法读取 %USERPROFILE%。请确认在 WSL 且 Windows 互通正常。" >&2
  exit 1
fi

desktop_win="${win_userprofile}\\Desktop"
desktop_wsl="$(wslpath -u "$desktop_win" 2>/dev/null || true)"
if [[ -z "$desktop_wsl" || ! -d "$desktop_wsl" ]]; then
  # OneDrive 桌面回退
  desktop_win="${win_userprofile}\\OneDrive\\Desktop"
  desktop_wsl="$(wslpath -u "$desktop_win" 2>/dev/null || true)"
fi
if [[ -z "$desktop_wsl" || ! -d "$desktop_wsl" ]]; then
  echo "错误：找不到 Windows 桌面目录（试过 Desktop / OneDrive\\Desktop）。" >&2
  exit 1
fi

cmd_path="$desktop_wsl/EU4战报.cmd"

# 转义单引号供 bash -lc 使用
repo_q="${REPO_PATH//\'/\'\\\'\'}"

cat > "$cmd_path" <<EOF
@echo off
REM 由 scripts/install-desktop-shortcut.sh 生成 — 请双击本文件（Windows 桌面，非 \\\\wsl\$）
REM 仓库: ${REPO_PATH}  发行版: ${DISTRO}
title EU4 战报
wsl.exe -d ${DISTRO} -e bash -lc "cd '${repo_q}' && uv run eu4-chronicle-desktop"
if errorlevel 1 (
  echo.
  echo 启动失败。请确认：WSL 可用、已 uv sync --extra desktop --extra llm、仓库 .env 已配置。
  pause
)
EOF

# 去掉 Zone.Identifier，避免偶发「已阻止」
if command -v powershell.exe >/dev/null 2>&1; then
  cmd_win="$(wslpath -w "$cmd_path" 2>/dev/null || true)"
  if [[ -n "$cmd_win" ]]; then
    powershell.exe -NoProfile -Command \
      "Unblock-File -LiteralPath '$cmd_win'; exit 0" \
      >/dev/null 2>&1 || true
  fi
fi

echo "已写入桌面快捷方式："
echo "  ${desktop_win}\\EU4战报.cmd"
echo "  （WSL 可见：${cmd_path}）"
echo "发行版: ${DISTRO}"
echo "仓库:   ${REPO_PATH}"
echo
echo "请只双击桌面上的「EU4战报.cmd」，不要再从 \\\\wsl\$ 路径点 bat。"

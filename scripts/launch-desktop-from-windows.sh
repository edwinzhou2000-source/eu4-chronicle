#!/usr/bin/env bash
# 供 Windows 桌面 EU4战报.cmd 经 wsl.exe 调用（非交互、非登录也可）。
# 用法: bash scripts/launch-desktop-from-windows.sh
# 可选: EU4_REPO_PATH=/abs/path
set -euo pipefail

echo "[EU4 战报] 正在启动…"

# 非交互 wsl.exe 常不带 ~/.local/bin；显式补齐，并尽量加载用户 rc
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:/usr/local/bin:${PATH}"
if [[ -f "${HOME}/.profile" ]]; then
  # shellcheck disable=SC1090,SC1091
  source "${HOME}/.profile" || true
fi
if [[ -f "${HOME}/.bashrc" ]]; then
  # shellcheck disable=SC1090,SC1091
  source "${HOME}/.bashrc" || true
fi
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:/usr/local/bin:${PATH}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
if command -v git >/dev/null 2>&1; then
  git_root="$(git -C "${REPO_ROOT}" rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -n "${git_root}" ]]; then
    REPO_ROOT="${git_root}"
  fi
fi
REPO_PATH="${EU4_REPO_PATH:-${REPO_ROOT}}"

if [[ ! -d "${REPO_PATH}" ]]; then
  echo "[错误] 仓库目录不存在：${REPO_PATH}" >&2
  echo "请在 WSL 重新执行：bash scripts/install-desktop-shortcut.sh" >&2
  exit 10
fi
if [[ ! -f "${REPO_PATH}/pyproject.toml" ]]; then
  echo "[错误] 不是 EU4 战报仓库（缺少 pyproject.toml）：${REPO_PATH}" >&2
  exit 11
fi

cd "${REPO_PATH}"
echo "[信息] 仓库：${REPO_PATH}"

if ! command -v uv >/dev/null 2>&1; then
  echo "[错误] 找不到 uv（当前 PATH=${PATH}）" >&2
  echo "请在 WSL 安装：curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "并确认 ~/.local/bin 可用，然后重装桌面快捷方式。" >&2
  exit 12
fi
echo "[信息] uv：$(command -v uv)"

if [[ ! -d "${REPO_PATH}/.venv" ]]; then
  echo "[信息] 未检测到 .venv，正在 uv sync --extra desktop --extra llm …"
  uv sync --extra desktop --extra llm
fi

echo "[信息] 启动 eu4-game-report-desktop（窗口/浏览器打开前请勿关本黑框）…"
echo "[信息] 选档页通常为 http://127.0.0.1:18765/"
exec uv run eu4-game-report-desktop

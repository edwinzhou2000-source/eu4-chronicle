#Requires -Version 5.0
<#
.SYNOPSIS
  在 Windows 真实桌面（%USERPROFILE%\Desktop）写入「EU4战报.cmd」（可重复覆盖）。

.DESCRIPTION
  生成的 .cmd 经 wsl.exe 调用仓库内 scripts/launch-desktop-from-windows.sh。
  失败会 pause 并打印中文原因；成功时黑框保持到进程结束。

.PARAMETER RepoPath
  WSL 内仓库绝对路径。省略时从脚本位置 / $HOME/genesis 推断。

.PARAMETER Distro
  WSL 发行版名。省略时用 $env:WSL_DISTRO_NAME 或 wsl 默认项。
#>
[CmdletBinding()]
param(
  [string]$RepoPath = "",
  [string]$Distro = ""
)

$ErrorActionPreference = "Stop"
$ScriptFile = $MyInvocation.MyCommand.Path

function Get-DefaultWslDistro {
  if ($env:WSL_DISTRO_NAME) {
    return $env:WSL_DISTRO_NAME.Trim()
  }
  $raw = & wsl.exe -l -v 2>$null
  if ($raw) {
    foreach ($line in @($raw)) {
      $t = ($line -replace "`0", "").Trim()
      if ($t -match '^\*\s*(\S+)') {
        return $Matches[1]
      }
    }
  }
  $q = & wsl.exe -l -q 2>$null
  if (-not $q) {
    throw "未检测到 WSL 发行版。请先安装并启用 WSL，再重试。"
  }
  $lines = @($q | ForEach-Object {
      ($_ -replace "`0", "").Trim()
    } | Where-Object { $_ })
  if (-not $lines) {
    throw "wsl -l -q 无可用发行版。"
  }
  return $lines[0]
}

function Get-RepoPathFromScript {
  param([string]$ScriptPath)
  $here = Split-Path -Parent $ScriptPath
  $root = Split-Path -Parent $here
  if (-not (Test-Path (Join-Path $root "pyproject.toml"))) {
    return $null
  }
  if ($root -match '^\\\\wsl\$\\([^\\]+)\\(.+)$') {
    $linux = "/" + ($Matches[2] -replace "\\", "/")
    return @{ Distro = $Matches[1]; RepoPath = $linux }
  }
  if ($root -match '^\\\\wsl\.localhost\\([^\\]+)\\(.+)$') {
    $linux = "/" + ($Matches[2] -replace "\\", "/")
    return @{ Distro = $Matches[1]; RepoPath = $linux }
  }
  return $null
}

if (-not $Distro) {
  $Distro = Get-DefaultWslDistro
}

if (-not $RepoPath) {
  $inferred = Get-RepoPathFromScript -ScriptPath $ScriptFile
  if ($inferred) {
    if (-not $PSBoundParameters.ContainsKey("Distro") -and $inferred.Distro) {
      $Distro = $inferred.Distro
    }
    $RepoPath = $inferred.RepoPath
  }
}

if (-not $RepoPath) {
  $probe = & wsl.exe -d $Distro -e bash -lc 'echo "$HOME/genesis"' 2>$null
  if ($probe) {
    $RepoPath = ($probe -replace "`0", "").Trim()
  }
}

if (-not $RepoPath) {
  throw "无法推断仓库路径。请传入 -RepoPath /home/<你>/genesis"
}

$check = & wsl.exe -d $Distro -e bash -lc "test -f '$RepoPath/pyproject.toml' && test -f '$RepoPath/scripts/launch-desktop-from-windows.sh' && echo OK" 2>$null
$checkText = if ($check) { ($check -replace "`0", "").Trim() } else { "" }
if ($checkText -ne "OK") {
  throw "发行版 '$Distro' 中找不到仓库或 launch 脚本：$RepoPath"
}

$desktop = [Environment]::GetFolderPath("Desktop")
if (-not $desktop -or -not (Test-Path $desktop)) {
  $desktop = Join-Path $env:USERPROFILE "Desktop"
}
if (-not (Test-Path $desktop)) {
  $onedrive = Join-Path $env:USERPROFILE "OneDrive\Desktop"
  if (Test-Path $onedrive) { $desktop = $onedrive }
}
if (-not (Test-Path $desktop)) {
  throw "找不到 Windows 桌面目录：$desktop"
}

$cmdPath = Join-Path $desktop "EU4战报.cmd"
$cmdBody = @"
@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title EU4 战报
echo ========================================
echo   EU4 战报 — 经 WSL 启动
echo ========================================
echo 发行版: $Distro
echo 仓库:   $RepoPath
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

wsl.exe -d $Distro -e bash -lc "export EU4_REPO_PATH='$RepoPath'; cd '$RepoPath' || exit 10; exec bash './scripts/launch-desktop-from-windows.sh'"
set "ERR=%ERRORLEVEL%"

echo.
if not "%ERR%"=="0" (
  echo [失败] WSL 启动退出码 %ERR%。
  echo 常见原因：
  echo   1. 发行版名不对（当前: $Distro）
  echo   2. 仓库路径不对（当前: $RepoPath）
  echo   3. WSL 里没有 uv（需装到 ~/.local/bin）
  echo   4. 未 uv sync --extra desktop --extra llm
  echo.
  echo 请在 WSL 重装快捷方式：
  echo   cd '$RepoPath' ^&^& bash scripts/install-desktop-shortcut.sh
  echo.
  pause
  exit /b %ERR%
)

echo [结束] 进程已退出。若选档页未打开，请手动访问 http://127.0.0.1:18765/
echo.
pause
endlocal
"@

Set-Content -Path $cmdPath -Value $cmdBody -Encoding ASCII
try { Unblock-File -LiteralPath $cmdPath -ErrorAction SilentlyContinue } catch {}

Write-Host "已写入/覆盖桌面快捷方式："
Write-Host "  $cmdPath"
Write-Host "发行版: $Distro"
Write-Host "仓库:   $RepoPath"
Write-Host ""
Write-Host "请只双击桌面上的「EU4战报.cmd」。失败会 pause；成功时黑框保持到选档页出现。"

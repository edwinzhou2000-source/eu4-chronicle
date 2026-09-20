#Requires -Version 5.0
<#
.SYNOPSIS
  在 Windows 真实桌面（%USERPROFILE%\Desktop）写入「EU4战报.cmd」。

.DESCRIPTION
  解决仓库在 WSL 时，双击 \\wsl$\... 下 bat 被拦 / 「如何打开」选「正常」无反应的问题。
  生成的 .cmd 从 Windows 调用 wsl.exe，在发行版内 uv run eu4-chronicle-desktop。
  API Key 仍只读仓库 .env，本脚本不处理密钥。

.PARAMETER RepoPath
  WSL 内仓库绝对路径（如 /home/edwin/genesis）。省略时尝试从脚本位置推断，
  再退到 $HOME/genesis。

.PARAMETER Distro
  WSL 发行版名。省略时用 $env:WSL_DISTRO_NAME，再退到 wsl -l -q 的默认项。

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/Install-DesktopShortcut.ps1
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
  $raw = & wsl.exe -l -q 2>$null
  if (-not $raw) {
    throw "未检测到 WSL 发行版。请先安装并启用 WSL，再重试。"
  }
  $lines = @($raw | ForEach-Object {
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

$check = & wsl.exe -d $Distro -e bash -lc "test -f '$RepoPath/pyproject.toml' && echo OK" 2>$null
$checkText = if ($check) { ($check -replace "`0", "").Trim() } else { "" }
if ($checkText -ne "OK") {
  throw "发行版 '$Distro' 中找不到仓库：$RepoPath（缺少 pyproject.toml）。请用 -RepoPath 指定。"
}

$desktop = [Environment]::GetFolderPath("Desktop")
if (-not $desktop -or -not (Test-Path $desktop)) {
  $desktop = Join-Path $env:USERPROFILE "Desktop"
}
if (-not (Test-Path $desktop)) {
  throw "找不到 Windows 桌面目录：$desktop"
}

$cmdPath = Join-Path $desktop "EU4战报.cmd"
$bashLc = "cd '$RepoPath' && uv run eu4-chronicle-desktop"
$cmdBody = @"
@echo off
REM 由 Install-DesktopShortcut.ps1 生成 — 请双击本文件（位于 Windows 桌面，非 \\wsl$）
REM 仓库: $RepoPath  发行版: $Distro
title EU4 战报
wsl.exe -d $Distro -e bash -lc "$bashLc"
if errorlevel 1 (
  echo.
  echo 启动失败。请确认：WSL 可用、已 uv sync --extra desktop --extra llm、仓库 .env 已配置。
  pause
)
"@

Set-Content -Path $cmdPath -Value $cmdBody -Encoding ASCII

Write-Host "已写入桌面快捷方式："
Write-Host "  $cmdPath"
Write-Host "发行版: $Distro"
Write-Host "仓库:   $RepoPath"
Write-Host ""
Write-Host "请只双击桌面上的「EU4战报.cmd」，不要再从 \\wsl$ 路径点 bat。"

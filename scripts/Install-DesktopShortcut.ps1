#Requires -Version 5.0
<#
.SYNOPSIS
  在 Windows 真实桌面（%USERPROFILE%\Desktop）写入「EU4战报.cmd」（可重复覆盖）。

.DESCRIPTION
  生成的 .cmd 经 wsl.exe 调用仓库内 scripts/launch-desktop-from-windows.sh。
  .cmd 正文为 ASCII 英文 + CRLF（避免中文 Windows GBK 乱码）；失败会 pause。

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
# Desktop .cmd MUST be ASCII-only + CRLF (Chinese Windows cmd = GBK/CP936).
$cmdLines = @(
  '@echo off'
  'setlocal EnableExtensions'
  'title EU4 Game Report'
  'echo ========================================'
  'echo   EU4 Game Report - launch via WSL'
  'echo ========================================'
  "echo Distro: $Distro"
  "echo Repo:   $RepoPath"
  'echo.'
  'echo Keep this window open until the UI opens.'
  'echo Stop with Ctrl+C in this window, or close it.'
  'echo.'
  ''
  'where wsl.exe >nul 2>nul'
  'if errorlevel 1 ('
  '  echo [ERROR] wsl.exe not found. Enable WSL on Windows first.'
  '  echo.'
  '  pause'
  '  exit /b 1'
  ')'
  ''
  "wsl.exe -d $Distro -e bash -lc `"export EU4_REPO_PATH='$RepoPath'; cd '$RepoPath' || exit 10; exec bash './scripts/launch-desktop-from-windows.sh'`""
  'set "ERR=%ERRORLEVEL%"'
  ''
  'echo.'
  'if not "%ERR%"=="0" ('
  '  echo [FAILED] WSL exited with code %ERR%.'
  '  echo Common causes:'
  "  echo   1. Wrong distro name (now: $Distro)"
  "  echo   2. Wrong repo path (now: $RepoPath)"
  '  echo   3. uv missing in WSL (install to ~/.local/bin)'
  '  echo   4. Need: uv sync --extra desktop --extra llm'
  '  echo.'
  '  echo Reinstall shortcut from WSL:'
  "  echo   cd '$RepoPath' ^&^& bash scripts/install-desktop-shortcut.sh"
  '  echo.'
  '  pause'
  '  exit /b %ERR%'
  ')'
  ''
  'echo [DONE] Process exited. If UI did not open, open http://127.0.0.1:18765/'
  'echo.'
  'pause'
  'endlocal'
)
$cmdBody = ($cmdLines -join "`r`n") + "`r`n"

foreach ($ch in $cmdBody.ToCharArray()) {
  if ([int]$ch -gt 127) {
    throw "Generated .cmd contains non-ASCII character; aborting write."
  }
}

$ascii = [System.Text.Encoding]::ASCII
[System.IO.File]::WriteAllText($cmdPath, $cmdBody, $ascii)
try { Unblock-File -LiteralPath $cmdPath -ErrorAction SilentlyContinue } catch {}

Write-Host "Wrote/overwrote Desktop shortcut (ASCII English .cmd body):"
Write-Host "  $cmdPath"
Write-Host "Distro: $Distro"
Write-Host "Repo:   $RepoPath"
Write-Host ""
Write-Host "Double-click Desktop EU4战报.cmd only. Console messages are English; pause on failure."

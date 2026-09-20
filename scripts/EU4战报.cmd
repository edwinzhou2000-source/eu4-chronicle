@echo off
REM [已弃用路径] 与 EU4战报.bat 相同。
REM 仓库在 WSL 时：勿从 \\wsl$ 双击。请先:
REM   bash scripts/install-desktop-shortcut.sh
REM 然后只点 Windows 桌面上的 EU4战报.cmd。
call "%~dp0EU4战报.bat" %*

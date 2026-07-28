@echo off
title AGVG Lab Tools Installer
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install_Lab_Tools.ps1"
if errorlevel 1 (
  echo.
  echo Installation did not complete. Please send install_log.txt to the lab.
  pause
  exit /b 1
)
echo.
echo Installation complete. A Lab Tools shortcut is on your Desktop.
pause

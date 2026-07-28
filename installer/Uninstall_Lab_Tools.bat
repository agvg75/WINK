@echo off
echo This removes the per-user AGVG Lab Tools installation and shortcuts.
echo Experimental images and analysis outputs are not removed.
choice /M "Continue"
if errorlevel 2 exit /b 0
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath (Join-Path $env:LOCALAPPDATA 'AGVGLab') -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath (Join-Path $env:LOCALAPPDATA 'Fiji.app') -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Desktop')) 'AGVG Lab Tools.lnk') -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Fiji - AGVG Lab.lnk') -Force -ErrorAction SilentlyContinue"
echo Uninstall complete.
pause

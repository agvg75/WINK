@echo off
rem Double-click to open the Lab Tools hub: one window with every tool.
rem Finds the Python environment in the in-folder, all-users, or per-user
rem location, whichever exists on this computer.
set "L1=%~dp0.venv\Scripts\pythonw.exe"
set "L2=%ProgramData%\LabTools\.venv\Scripts\pythonw.exe"
set "L3=%LOCALAPPDATA%\LabTools\.venv\Scripts\pythonw.exe"
set "L4=%LOCALAPPDATA%\AGVGLab\runtime\Scripts\pythonw.exe"
if exist "%L1%" ( start "" "%L1%" "%~dp0app\lab_hub.py" & exit )
if exist "%L2%" ( start "" "%L2%" "%~dp0app\lab_hub.py" & exit )
if exist "%L3%" ( start "" "%L3%" "%~dp0app\lab_hub.py" & exit )
if exist "%L4%" ( start "" "%L4%" "%~dp0app\lab_hub.py" & exit )
echo.
echo Python environment not found on this computer.
echo Please run Setup_Lab_Tools.bat here first.
echo.
pause
exit

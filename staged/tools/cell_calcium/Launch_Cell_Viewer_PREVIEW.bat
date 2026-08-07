@echo off
rem ===================================================================
rem  WINK Cultured Cell Viewer - PREVIEW BUILD
rem
rem  This is a preview. It is expected to break; when it does you get a
rem  dialog and the details are written to a crash log on the L drive.
rem  Tell Andres what you were doing.
rem
rem  It does NOT auto-update and does NOT touch the published Lab Tools
rem  folder. Running this changes nothing about the WINK you normally use.
rem ===================================================================
setlocal
set "HERE=%~dp0"

rem Find a Python that has the lab's scientific libraries. Order matters:
rem the all-users install is the one students actually have.
set "PY="
if exist "%ProgramData%\LabTools\.venv\Scripts\pythonw.exe" set "PY=%ProgramData%\LabTools\.venv\Scripts\pythonw.exe"
if not defined PY if exist "%LOCALAPPDATA%\LabTools\.venv\Scripts\pythonw.exe" set "PY=%LOCALAPPDATA%\LabTools\.venv\Scripts\pythonw.exe"
if not defined PY if exist "%LOCALAPPDATA%\AGVGLab\runtime\Scripts\pythonw.exe" set "PY=%LOCALAPPDATA%\AGVGLab\runtime\Scripts\pythonw.exe"
if not defined PY if exist "%HERE%..\..\.venv\Scripts\pythonw.exe" set "PY=%HERE%..\..\.venv\Scripts\pythonw.exe"

if not defined PY (
    echo.
    echo   The Lab Tools Python environment was not found on this computer.
    echo.
    echo   Looked in:
    echo     %ProgramData%\LabTools\.venv
    echo     %LOCALAPPDATA%\LabTools\.venv
    echo     %LOCALAPPDATA%\AGVGLab\runtime
    echo.
    echo   Run Setup_Lab_Tools.bat once on this computer, then try again.
    echo.
    pause
    exit /b 1
)

rem Probe the dependencies BY USE before opening a window. An import can
rem succeed against a broken wheel; a call cannot. Uses python.exe rather
rem than pythonw.exe so the message is visible in this console.
set "PYC=%PY:pythonw.exe=python.exe%"
"%PYC%" "%HERE%..\..\app\preview_build_check.py"
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

start "" "%PY%" "%HERE%cell_calcium_tool.py"
exit /b 0

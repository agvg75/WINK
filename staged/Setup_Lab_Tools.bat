@echo off
setlocal
cd /d "%~dp0"
set "ENVDIR=%ProgramData%\LabTools\.venv"

echo ============================================================
echo   Lab Tools - one-time setup (per COMPUTER, all users)
echo ============================================================
echo This builds ONE Python environment on this computer that
echo every user who logs in can share. Run it ONCE per computer.
echo For it to serve all users, Python must be installed "for all
echo users" and this should be run as Administrator.
echo.
echo Environment location: %ENVDIR%
echo.

rem --- warn if not running as administrator ---
net session >nul 2>&1
if errorlevel 1 (
  echo NOTE: not running as Administrator. If setup cannot write to
  echo   %ProgramData%\LabTools, right-click this file and choose
  echo   "Run as administrator", or use the per-user setup instead.
  echo.
)

rem --- find a Python to build the environment with ---
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
  echo ERROR: No Python found. Install Python 3 "for all users" from
  echo https://www.python.org/downloads/ ^(check "Add python.exe to PATH"^),
  echo then run this again.
  pause
  exit /b 1
)
echo Using Python: %PYEXE%
echo.

echo Step 1 of 2: creating the shared environment ...
%PYEXE% -m venv "%ENVDIR%"
if errorlevel 1 (
  echo ERROR: could not create the environment.
  echo Try right-clicking this file and "Run as administrator".
  pause
  exit /b 1
)

echo.
echo Step 2 of 2: installing libraries (first time downloads a few hundred MB) ...
"%ENVDIR%\Scripts\python.exe" -m pip install --upgrade pip
REM magpylib is PINNED to v5.x on purpose. v5 takes polarization= in tesla with
REM dimensions in metres, which is what app/stimulus_fields.py passes. v4 took
REM magnetization= in mT with dimensions in mm - a v4 install does not fail
REM loudly, it produces field values that are wrong by orders of magnitude and
REM entirely plausible. Do not relax this pin without re-reading MagnetProvider.
"%ENVDIR%\Scripts\python.exe" -m pip install numpy pandas scipy matplotlib pillow tifffile imageio imageio-ffmpeg opencv-python tkinterdnd2 scikit-image nd2 czifile readlif "magpylib>=5,<6"
if errorlevel 1 (
  echo ERROR: something went wrong installing the libraries.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Setup complete. Any user on this computer can now use the
echo   tool buttons in the Lab tools folder.
echo ============================================================
pause

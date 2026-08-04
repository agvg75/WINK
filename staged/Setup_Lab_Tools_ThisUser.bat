@echo off
setlocal
cd /d "%~dp0"
set "ENVDIR=%LOCALAPPDATA%\LabTools\.venv"

echo ============================================================
echo   Lab Tools - setup for THIS USER only (no Administrator)
echo ============================================================
echo Use this when Setup_Lab_Tools.bat fails with "access is
echo denied". That one builds a shared environment under
echo %%ProgramData%%, which needs Administrator rights. This one
echo builds a private environment under your own profile, which
echo does not.
echo.
echo Only you will be able to use it. If several people share this
echo computer, an administrator should run Setup_Lab_Tools.bat
echo instead so everyone shares one environment.
echo.
echo Environment location: %ENVDIR%
echo.

rem --- find a Python to build the environment with ---
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
  echo ERROR: No Python found on this computer.
  echo.
  echo Install Python 3 from https://www.python.org/downloads/
  echo and TICK "Add python.exe to PATH" on the first screen.
  echo You do NOT need to install it for all users.
  echo Then run this file again.
  echo.
  pause
  exit /b 1
)
echo Using Python: %PYEXE%
echo.

echo Step 1 of 2: creating your environment ...
%PYEXE% -m venv "%ENVDIR%"
if errorlevel 1 (
  echo.
  echo ERROR: could not create the environment at
  echo   %ENVDIR%
  echo That folder is inside your own profile, so this is unlikely
  echo to be a permissions problem - check that there is free disk
  echo space, and that Python installed correctly.
  echo.
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
REM This list must stay in step with Setup_Lab_Tools.bat: two setup paths that
REM install different libraries would give two students different results from
REM the same data, and nothing would report that they differed.
"%ENVDIR%\Scripts\python.exe" -m pip install numpy pandas scipy matplotlib pillow tifffile imageio imageio-ffmpeg opencv-python tkinterdnd2 scikit-image nd2 czifile readlif "magpylib>=5,<6"
if errorlevel 1 (
  echo.
  echo ERROR: something went wrong installing the libraries.
  echo If you are on a restricted network, pip may have been blocked.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Setup complete for %USERNAME%.
echo   Now double-click Launch_Lab_Hub.bat to open the tools.
echo ============================================================
pause

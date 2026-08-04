@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "ENVDIR=%LOCALAPPDATA%\LabTools\.venv"
set "LOGDIR=%LOCALAPPDATA%\LabTools"
set "LOG=%LOGDIR%\setup_log.txt"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1

echo ============================================================
echo   Lab Tools - setup for THIS USER only (no Administrator)
echo ============================================================
echo Use this when Setup_Lab_Tools.bat fails with "access is
echo denied". That one builds a shared environment under
echo %%ProgramData%%, which needs Administrator rights. This one
echo builds a private environment under your own profile, which
echo does not. Only you will be able to use it.
echo.
echo Environment: %ENVDIR%
echo Log file:    %LOG%
echo.
echo A log is written as this runs, so if anything fails you can
echo read what happened after this window closes.
echo.

echo === Lab Tools per-user setup, %DATE% %TIME% === > "%LOG%"

rem --- find a Python to build the environment with ---
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
  echo No Python found. >> "%LOG%"
  call :fail "No Python is installed on this computer." ^
    "Install Python 3 from https://www.python.org/downloads/ and TICK" ^
    "'Add python.exe to PATH' on the FIRST screen of the installer." ^
    "You do NOT need to install it for all users. Then run this again."
  exit /b 1
)
echo Using Python: %PYEXE%
echo Using Python: %PYEXE% >> "%LOG%"
echo.

echo Step 1 of 2: creating your environment ...
%PYEXE% -m venv "%ENVDIR%" >> "%LOG%" 2>&1
if errorlevel 1 (
  call :fail "Could not create the environment at" "  %ENVDIR%" ^
    "That folder is inside your own profile, so this is unlikely to be" ^
    "a permissions problem - check free disk space and that Python" ^
    "installed correctly."
  exit /b 1
)

echo Step 2 of 2: installing libraries ...
echo   (first time downloads a few hundred MB - this takes several minutes)
"%ENVDIR%\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
REM magpylib is PINNED to v5.x on purpose. v5 takes polarization= in tesla with
REM dimensions in metres, which is what app/stimulus_fields.py passes. v4 took
REM magnetization= in mT with dimensions in mm - a v4 install does not fail
REM loudly, it produces field values that are wrong by orders of magnitude and
REM entirely plausible. Do not relax this pin without re-reading MagnetProvider.
REM This list must stay in step with Setup_Lab_Tools.bat: two setup paths that
REM install different libraries would give two students different results from
REM the same data, and nothing would report that they differed.
"%ENVDIR%\Scripts\python.exe" -m pip install numpy pandas scipy matplotlib pillow tifffile imageio imageio-ffmpeg opencv-python tkinterdnd2 scikit-image nd2 czifile readlif "magpylib>=5,<6" >> "%LOG%" 2>&1
if errorlevel 1 (
  call :fail "Something went wrong installing the libraries." ^
    "If you are on a restricted network, pip may have been blocked." ^
    "The full error is in the log file."
  exit /b 1
)

rem --- prove it actually works before claiming success ---
"%ENVDIR%\Scripts\python.exe" -c "import numpy, scipy, matplotlib, skimage, readlif, tifffile" >> "%LOG%" 2>&1
if errorlevel 1 (
  call :fail "The libraries installed but could not be loaded." ^
    "The full error is in the log file."
  exit /b 1
)

echo. >> "%LOG%"
echo SUCCESS >> "%LOG%"
echo.
echo ############################################################
echo #                                                          #
echo #   SETUP COMPLETE for %USERNAME%
echo #                                                          #
echo ############################################################
echo.
choice /c YN /n /m "Open the Lab Tools hub now? [Y/N] "
if errorlevel 2 goto :done
if exist "%~dp0Launch_Lab_Hub.bat" (
  start "" "%~dp0Launch_Lab_Hub.bat"
) else (
  echo Could not find Launch_Lab_Hub.bat next to this file.
  pause
)
:done
echo.
echo You can reopen the tools any time with Launch_Lab_Hub.bat
timeout /t 8 >nul
exit /b 0

rem ---------------------------------------------------------------- fail ----
rem Failures must not look like success. The window stays open until it is
rem closed deliberately, and the log path is repeated, because a batch window
rem that vanishes on a keypress leaves nothing to diagnose.
:fail
echo.
echo ############################################################
echo #                    SETUP FAILED                          #
echo ############################################################
echo.
:fail_loop
if not "%~1"=="" (
  echo   %~1
  shift
  goto :fail_loop
)
echo.
echo   A log of what happened was saved to:
echo     %LOG%
echo.
echo   Nothing was installed. Send that log file to the lab if the
echo   message above does not explain it.
echo.
echo   This window will stay open. Close it when you have read this.
echo.
pause
pause
goto :eof

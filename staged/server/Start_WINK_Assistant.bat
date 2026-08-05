@echo off
REM ---------------------------------------------------------------------------
REM  Start the WINK assistant on this PC, for students on the lab network.
REM
REM  Nothing is hosted anywhere. This machine answers, this machine holds the
REM  key, and closing this window stops it. No account, no monthly fee.
REM
REM  The key is read from a file OUTSIDE the repository, so it cannot be
REM  committed by accident and does not travel with the app.
REM ---------------------------------------------------------------------------
setlocal

set "LT=%LOCALAPPDATA%\LabTools"
set "PY=%LT%\.venv\Scripts\python.exe"
set "KEYFILE=%LT%\assistant_key.txt"
set "HERE=%~dp0"

if not exist "%PY%" (
    echo.
    echo   The WINK runtime was not found at:
    echo     %PY%
    echo.
    echo   Run Setup_Lab_Tools_ThisUser.bat first, then try again.
    echo.
    pause
    exit /b 1
)

if not exist "%KEYFILE%" (
    echo.
    echo   No API key found. Create this file:
    echo     %KEYFILE%
    echo.
    echo   and paste your Anthropic API key into it as a single line,
    echo   nothing else. Get one at https://console.anthropic.com
    echo   - and set a monthly spend limit while you are there.
    echo.
    pause
    exit /b 1
)

REM Read the key without echoing it to the console.
set "ANTHROPIC_API_KEY="
for /f "usebackq delims=" %%K in ("%KEYFILE%") do if not defined ANTHROPIC_API_KEY set "ANTHROPIC_API_KEY=%%K"

REM Ledger and tokens live beside the runtime, not in the repository: the
REM ledger holds real student questions and the tokens are credentials.
set "WINK_LEDGER_DB=%LT%\wink_ledger.sqlite"
set "WINK_TOKENS=%LT%\tokens.json"

if not exist "%WINK_TOKENS%" (
    echo.
    echo   No student tokens found. Copying the template to:
    echo     %WINK_TOKENS%
    copy /y "%HERE%tokens.example.json" "%WINK_TOKENS%" >nul
    echo.
    echo   Open it, replace the example tokens with random strings, and
    echo   put one student's name against each. Then run this again.
    echo.
    notepad "%WINK_TOKENS%"
    pause
    exit /b 1
)

"%PY%" -c "import flask, anthropic" 2>nul
if errorlevel 1 (
    echo.
    echo   Installing the two packages the assistant needs...
    "%PY%" -m pip install --quiet flask anthropic
    if errorlevel 1 (
        echo   Install failed. Check the network and try again.
        pause
        exit /b 1
    )
)

echo.
"%PY%" "%HERE%wink_assistant_server.py" --port 5000

echo.
echo   The assistant has stopped.
pause
endlocal

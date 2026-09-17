@echo off
REM ---------------------------------------------------------------------------
REM Agentic Warehouse - start everything
REM
REM Double-click this file, or run it from a command prompt. It starts the
REM database, the API and the web interface with one command; the front end is
REM rebuilt automatically only when its source has changed.
REM
REM   run.bat            http://localhost:8000
REM   run.bat --https    https://<your-lan-ip>:8443, so phone cameras work
REM   run.bat --port 8080
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Python was not found on this machine.
    echo   Install Python 3.8 or newer from https://python.org and tick
    echo   "Add Python to PATH" during the installer.
    echo.
    pause
    exit /b 1
)

python app.py %*

REM Keep the window open if the server stopped because of an error, so the
REM message is readable instead of vanishing with the console.
if errorlevel 1 (
    echo.
    echo   The server stopped with an error. The message above says why.
    pause
)
endlocal

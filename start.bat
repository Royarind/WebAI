@echo off
setlocal EnableExtensions EnableDelayedExpansion
title WebAI - Update, Install and Start
color 0B

REM Always run from the folder containing this BAT file.
cd /d "%~dp0"
set "PROJECT=%CD%"
set "VENV_PY=%PROJECT%\.venv\Scripts\python.exe"
set "PORT=8765"
set "URL=http://127.0.0.1:%PORT%"

echo.
echo ============================================================
echo   WebAI - One-click updater and launcher
echo ============================================================
echo Project: %PROJECT%
echo.

if not exist ".git\" (
  echo [ERROR] Git repository metadata not found in:
  echo         %PROJECT%
  echo Save start.bat inside D:MiscAI ProjectsWebAI and try again.
  pause
  exit /b 1
)

where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Git is not installed or not on PATH.
  pause
  exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python was not found on PATH. Install Python 3.11+ first.
  pause
  exit /b 1
)

echo [1/7] Checking for an existing WebAI server on port %PORT%...
set "PIDS="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  if not "%%P"=="0" set "PIDS=!PIDS! %%P"
)
REM Enable delayed expansion only in a nested scope for PID collection.
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  if not "%%P"=="0" (
    echo Stopping process PID %%P listening on port %PORT%...
    taskkill /PID %%P /T /F >nul 2>&1
  )
)

echo [2/7] Updating source from GitHub...
REM Ignore untracked files (including a newly downloaded start.bat) when deciding whether tracked source is safe to update.
git diff --quiet
if errorlevel 1 (
  echo [WARNING] Tracked local changes detected. Skipping git pull to protect your edits.
  goto :install
)
git diff --cached --quiet
if errorlevel 1 (
  echo [WARNING] Staged local changes detected. Skipping git pull to protect your edits.
  goto :install
)
git pull --ff-only
if errorlevel 1 (
  echo [ERROR] Git update failed. Check network access and resolve any Git conflicts.
  pause
  exit /b 1
)

:install
echo [3/8] Ensuring project virtual environment exists...
if not exist "%VENV_PY%" (
  python -m venv ".venv"
  if errorlevel 1 (
    echo [ERROR] Could not create .venv.
    pause
    exit /b 1
  )
)

echo [4/8] Updating pip tooling...
"%VENV_PY%" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 (
  echo [ERROR] pip upgrade failed.
  pause
  exit /b 1
)

echo [5/8] Installing/updating WebAI and computer-use dependencies...
"%VENV_PY%" -m pip install --disable-pip-version-check -e ".[computer-use]"
if errorlevel 1 (
  echo [ERROR] Dependency installation failed. WebAI will not be started.
  pause
  exit /b 1
)

echo [6/8] Verifying the installed WebAI source...
"%VENV_PY%" -c "import webai, webai.agent; print('webai package:', webai.__file__); print('agent module:', webai.agent.__file__)"
if errorlevel 1 (
  echo [ERROR] Could not import WebAI from this environment.
  pause
  exit /b 1
)
echo Current Git commit:
git rev-parse --short HEAD
echo [7/8] Opening WebAI dashboard...
start "" "%URL%"
timeout /t 2 /nobreak >nul

echo [8/8] Starting WebAI server...
echo Dashboard: %URL%
echo Keep this window open while using WebAI.
echo Press Ctrl+C in this window to stop the server.
echo.
"%VENV_PY%" -m uvicorn webai.server:app --host 127.0.0.1 --port %PORT%

echo.
echo WebAI server has stopped.
pause
endlocal

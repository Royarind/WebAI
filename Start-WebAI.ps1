$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host ""
Write-Host "=== WebAI Auto-Updater and Launcher ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"

if (-not (Test-Path ".git")) {
    throw "This folder is not a Git checkout. Download/clone the WebAI repository first."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating project virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$GitStatus = git status --porcelain
if ($LASTEXITCODE -ne 0) { throw "Could not inspect Git working tree." }

if ($GitStatus) {
    Write-Host "Local changes detected. Skipping automatic git pull to avoid overwriting your work." -ForegroundColor Yellow
    Write-Host "Commit/stash your changes, or review them before updating."
} else {
    Write-Host "Checking GitHub for updates..." -ForegroundColor Cyan
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        throw "Automatic update failed. Resolve the Git issue, then rerun Start-WebAI.ps1."
    }
}

Write-Host "Installing/updating WebAI and its computer-use dependencies..." -ForegroundColor Cyan
& $Python -m pip install --disable-pip-version-check -e ".[computer-use]"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. WebAI was not started." }

Write-Host "Checking whether port 8765 is already in use..." -ForegroundColor Cyan
$Existing = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($Existing) {
    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($Existing.OwningProcess)" -ErrorAction SilentlyContinue
    Write-Host "Port 8765 is already in use by PID $($Existing.OwningProcess)." -ForegroundColor Yellow
    if ($ProcessInfo) { Write-Host "Command: $($ProcessInfo.CommandLine)" }
    $Answer = Read-Host "Stop that process and restart WebAI? Enter Y to confirm"
    if ($Answer -notin @("Y","y","YES","yes")) {
        Write-Host "Not stopping the existing process. If WebAI is already running, open http://127.0.0.1:8765."
        exit 0
    }
    Stop-Process -Id $Existing.OwningProcess -Force
    Start-Sleep -Seconds 1
}

Write-Host "Starting WebAI. Keep this window open." -ForegroundColor Green
Write-Host "Dashboard: http://127.0.0.1:8765"
Start-Process "http://127.0.0.1:8765"
& $Python -m uvicorn webai.server:app --host 127.0.0.1 --port 8765

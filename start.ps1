#Requires -Version 5.1
# NOTE for future edits: this file must be saved as UTF-8 **with a BOM**.
# Windows PowerShell 5.1 has no way to detect UTF-8 without one and falls
# back to the system codepage, which silently corrupts the Persian string
# literals below and then fails with a confusing "string is missing the
# terminator" parse error on an unrelated line. Every .ps1 file in this
# project that contains Persian text needs the same treatment - verify with
# `Format-Hex path.ps1 -Count 3` and expect `EF BB BF`.
<#
.SYNOPSIS
    Starts the Local AI Content Creator Platform.

.DESCRIPTION
    Verifies the backend environment exists, starts the FastAPI backend
    (which also serves the built frontend from frontend/dist), waits for it
    to become healthy, and opens it in the default browser.

    For frontend development with hot reload, run `npm run dev` in
    frontend/ separately instead of relying on the built bundle here.

.PARAMETER NoBrowser
    Do not open a browser window automatically.

.PARAMETER Port
    Override the port. Defaults to the backend's own default (see
    backend/app/core/config.py); only needed if you have set CCA_PORT.
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [int]$Port
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"

function Write-ErrorAndExit($message) {
    Write-Host ""
    Write-Host "خطا: $message" -ForegroundColor Red
    Write-Host "Error: $message" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $venvPython)) {
    Write-ErrorAndExit "Backend environment not found. Run scripts\setup.ps1 first."
}

if (-not (Test-Path (Join-Path $backend "..\bin\ffmpeg\ffmpeg.exe"))) {
    Write-Warning "Bundled FFmpeg not found. Audio extraction and video rendering will not work until you run scripts\setup.ps1 or set the FFmpeg path in Settings."
}

if ($Port) {
    $env:CCA_PORT = $Port
}

Write-Host "Starting backend..." -ForegroundColor Cyan
Push-Location $backend
$process = Start-Process -FilePath $venvPython -ArgumentList "-m", "app.main" -NoNewWindow -PassThru
Pop-Location

# The backend probes for a free port if the configured one is unavailable
# (Windows reserves ranges for Hyper-V/WinNAT); read the actual port back
# from its log rather than assuming the configured default.
$logFile = Join-Path $root "logs\app.log"
$actualPort = if ($Port) { $Port } else { 8420 }
$deadline = (Get-Date).AddSeconds(30)
$ready = $false

Write-Host "Waiting for the backend to become ready..."
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) {
        Write-ErrorAndExit "Backend process exited unexpectedly. Check logs\app.log for details."
    }
    if (Test-Path $logFile) {
        $match = Select-String -Path $logFile -Pattern "listening on http://[^:]+:(\d+)" -ErrorAction SilentlyContinue | Select-Object -Last 1
        if ($match) { $actualPort = [int]$match.Matches[0].Groups[1].Value }
    }
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$actualPort/api/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        continue
    }
}

if (-not $ready) {
    Write-ErrorAndExit "Backend did not become ready within 30 seconds. Check logs\app.log."
}

$url = "http://127.0.0.1:$actualPort/"
Write-Host ""
Write-Host "پلتفرم آماده است: $url" -ForegroundColor Green
Write-Host "Platform ready: $url" -ForegroundColor Green
Write-Host "برای توقف، این پنجره را ببندید یا Ctrl+C را بزنید." -ForegroundColor Yellow

if (-not $NoBrowser) {
    Start-Process $url
}

try {
    Wait-Process -Id $process.Id
} finally {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
}

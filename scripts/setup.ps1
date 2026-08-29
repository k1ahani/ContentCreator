#Requires -Version 5.1
<#
.SYNOPSIS
    First-time setup for the Local AI Content Creator Platform.

.DESCRIPTION
    Provisions everything the platform needs to run:
      - a pinned Python 3.12 virtual environment for the backend (via uv)
      - backend Python dependencies
      - a bundled FFmpeg (downloaded only if not already present)
      - frontend npm dependencies and a production build

    Safe to re-run: every step is idempotent and skips work that is already
    done. Run this after cloning the repository, and again after pulling
    changes to backend/requirements*.txt or frontend/package.json.

.PARAMETER SkipAsr
    Skip installing the optional local speech-recognition engine
    (faster-whisper). Use scripts\install_asr.ps1 to add it later.

.PARAMETER SkipFrontendBuild
    Install frontend dependencies but skip `npm run build`. Use this if you
    plan to run the frontend with `npm run dev` instead of the built bundle.
#>
[CmdletBinding()]
param(
    [switch]$SkipAsr,
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

function Write-Step($text) {
    Write-Host ""
    Write-Host "==> $text" -ForegroundColor Cyan
}

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "Local AI Content Creator Platform - Setup" -ForegroundColor Green
Write-Host "Root: $root"

# -- uv (Python package/version manager) ------------------------------------
Write-Step "Checking for uv (Python environment manager)"
if (-not (Test-Command "uv")) {
    Write-Host "uv not found. Installing via the official installer..."
    Invoke-Expression (Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1")
    $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
    if (-not (Test-Command "uv")) {
        throw "uv installation did not complete. Install it manually from https://docs.astral.sh/uv/ and re-run this script."
    }
}
Write-Host "uv: $(uv --version)"

# -- Python virtual environment ---------------------------------------------
Write-Step "Creating backend virtual environment (Python 3.12)"
Push-Location $backend
try {
    if (-not (Test-Path ".venv")) {
        uv venv --python 3.12 ".venv"
    } else {
        Write-Host "Virtual environment already exists, skipping creation."
    }

    Write-Step "Installing backend dependencies"
    uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt

    if (-not $SkipAsr) {
        Write-Step "Installing speech-recognition engine (faster-whisper)"
        uv pip install --python ".venv\Scripts\python.exe" -r requirements-asr.txt
    } else {
        Write-Host "Skipping ASR engine install (-SkipAsr). Run scripts\install_asr.ps1 later."
    }
} finally {
    Pop-Location
}

# -- FFmpeg -------------------------------------------------------------------
Write-Step "Checking for FFmpeg"
$ffmpegDir = Join-Path $root "bin\ffmpeg"
$ffmpegExe = Join-Path $ffmpegDir "ffmpeg.exe"

if (Test-Path $ffmpegExe) {
    Write-Host "Bundled FFmpeg already present at $ffmpegExe"
} else {
    Write-Host "Downloading a static FFmpeg build (gyan.dev, ~100 MB)..."
    $downloadDir = Join-Path $root "bin\_setup_download"
    New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
    $zipPath = Join-Path $downloadDir "ffmpeg.zip"

    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $downloadDir -Force

    $extracted = Get-ChildItem -Path $downloadDir -Directory | Where-Object { $_.Name -like "ffmpeg-*" } | Select-Object -First 1
    if (-not $extracted) { throw "Could not find the extracted FFmpeg folder." }

    New-Item -ItemType Directory -Force -Path $ffmpegDir | Out-Null
    Copy-Item -Path (Join-Path $extracted.FullName "bin\*") -Destination $ffmpegDir -Force
    Copy-Item -Path (Join-Path $extracted.FullName "LICENSE") -Destination (Join-Path $ffmpegDir "LICENSE") -Force -ErrorAction SilentlyContinue

    Remove-Item -Recurse -Force $downloadDir
    Write-Host "FFmpeg installed to $ffmpegDir"
}
& $ffmpegExe -version | Select-Object -First 1

# -- Claude CLI (verify only; this platform does not install it) -----------
Write-Step "Checking for Claude CLI"
if (Test-Command "claude") {
    Write-Host "Claude CLI found: $(claude --version)"
} else {
    Write-Warning "Claude CLI was not found on PATH. Install it separately, then set its path in Settings if it is still not detected automatically."
}

# -- Frontend -----------------------------------------------------------------
Write-Step "Installing frontend dependencies"
Push-Location $frontend
try {
    npm install
    if (-not $SkipFrontendBuild) {
        Write-Step "Building the frontend for production"
        npm run build
    } else {
        Write-Host "Skipping frontend build (-SkipFrontendBuild)."
    }
} finally {
    Pop-Location
}

# -- Directories ----------------------------------------------------------
Write-Step "Creating runtime directories"
foreach ($dir in @("logs", "storage\projects", "storage\models", "config")) {
    $path = Join-Path $root $dir
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Start the platform with: .\start.bat  (or .\start.ps1)"

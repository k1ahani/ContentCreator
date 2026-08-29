#Requires -Version 5.1
<#
.SYNOPSIS
    Installs the optional local speech-recognition engine (faster-whisper).

.DESCRIPTION
    The platform runs without this - every other feature works - but
    "تبدیل صدا به متن" (Feature 2) needs it. Separated from setup.ps1 because
    it pulls in CTranslate2/onnxruntime/numpy, a few hundred megabytes, which
    a user who only wants audio extraction or TTS should not be forced to
    download.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"

Push-Location $backend
try {
    if (-not (Test-Path ".venv")) {
        throw "Backend virtual environment not found. Run scripts\setup.ps1 first."
    }
    Write-Host "Installing faster-whisper (local Whisper speech recognition)..." -ForegroundColor Cyan
    uv pip install --python ".venv\Scripts\python.exe" -r requirements-asr.txt
    Write-Host "Done. The 'small' model (~470 MB) will download automatically the first time you transcribe." -ForegroundColor Green
} finally {
    Pop-Location
}

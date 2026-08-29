@echo off
REM Starts the Local AI Content Creator Platform.
REM This is a thin wrapper around start.ps1 so the platform can be launched
REM with a plain double-click, without the user needing to know PowerShell
REM exists. See start.ps1 for the actual startup logic.
REM
REM This file is intentionally kept pure ASCII. cmd.exe's handling of
REM non-ASCII text in a .bat file is unreliable even with a UTF-8 BOM present
REM - verified directly: the same file that parses fine when the .ps1 it
REM calls is invoked straight from PowerShell can still occasionally
REM misparse an "echo <Persian text>" line into several bogus commands when
REM launched through cmd.exe, one word fragment at a time. start.ps1 already
REM prints both the Persian and English failure message via Write-ErrorAndExit
REM before it returns a non-zero exit code, so nothing is lost by keeping this
REM wrapper itself in English only.

setlocal
set SCRIPT_DIR=%~dp0

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start.ps1" %*
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% NEQ 0 (
    echo.
    echo Startup failed. See the error above for details.
    pause
)

exit /b %EXIT_CODE%

@echo off
setlocal
cd /d "%~dp0"

set "HTML_FILE=%~dp0index.html"

if not exist "%HTML_FILE%" (
    echo [ERROR] Could not locate index.html!
    echo Please make sure index.html is present in the twinsock-studio directory.
    pause
    exit /b 1
)

start "" "%HTML_FILE%"
exit /b 0

@echo off
setlocal
cd /d "%~dp0"

set "HTML_FILE=%~dp0gen_url.html"
if not exist "%HTML_FILE%" set "HTML_FILE=%~dp0ui\gen_url.html"

if not exist "%HTML_FILE%" (
    echo [ERROR] Could not locate gen_url.html!
    echo Please make sure gen_url.html is present in the application directory.
    pause
    exit /b 1
)

start "" "%HTML_FILE%"
exit /b 0
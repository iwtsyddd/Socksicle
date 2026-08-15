@echo off
chcp 65001 >nul 2>&1
title Socksicle Installer

echo.
echo  ========================================
echo    Socksicle - Windows Installer
echo  ========================================
echo.

echo  [1/3] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [ERROR] Python is not installed or not in PATH!
    echo.
    echo  Please install Python 3.10+ from:
    echo  https://www.python.org/downloads/
    echo.
    echo  Make sure to check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
echo         Python %PY_VER% found
echo.

echo  [2/3] Installing Python dependencies...
echo.
pip install .
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [ERROR] Failed to install dependencies!
    echo.
    pause
    exit /b 1
)
echo.
echo         Dependencies installed successfully
echo.

echo  [3/3] Checking proxy engines...
echo.

set FOUND_ENGINE=0
setlocal enabledelayedexpansion

for %%e in (sslocal xray sing-box) do (
    where %%e.exe >nul 2>&1
    if !errorlevel! equ 0 (
        echo         [OK] %%e.exe found
        set FOUND_ENGINE=1
    ) else (
        echo         [--] %%e.exe not found
    )
)
endlocal & set FOUND_ENGINE=%FOUND_ENGINE%

echo.
if %FOUND_ENGINE% equ 0 (
    color 0E
    echo  +------------------------------------------+
    echo  |      NO PROXY ENGINE FOUND               |
    echo  +------------------------------------------+
    echo  |                                          |
    echo  |  Socksicle requires at least one engine: |
    echo  |  sslocal, xray, or sing-box              |
    echo  |                                          |
    echo  |  --- Shadowsocks (sslocal) ---           |
    echo  |  1. github.com/shadowsocks/              |
    echo  |     shadowsocks-rust/releases            |
    echo  |  2. Download latest for Windows          |
    echo  |  3. Extract sslocal.exe to PATH          |
    echo  |     OR: cargo install shadowsocks-rust   |
    echo  |                                          |
    echo  |  --- Xray ---                            |
    echo  |  1. github.com/XTLS/Xray-core/releases   |
    echo  |  2. Download Xray-windows-64.zip         |
    echo  |  3. Extract xray.exe to PATH             |
    echo  |                                          |
    echo  |  --- sing-box ---                        |
    echo  |  1. github.com/SagerNet/sing-box/releases|
    echo  |  2. Download for Windows                 |
    echo  |  3. Extract sing-box.exe to PATH         |
    echo  |                                          |
    echo  +------------------------------------------+
    echo.
) else (
    color 0A
    echo         At least one proxy engine found - OK
    echo.
)

echo  ========================================
echo   Installation complete!
echo  ========================================
echo.
echo   Run the application with:
echo.
echo     python main.py
echo.
echo   Supported engines: sslocal, xray, sing-box
echo   (install at least one to connect)
echo.
echo  ========================================
echo.
pause

@echo off
setlocal
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo  CS2 Toolkit
echo  ===========
echo  1. Auto Derank   (invite + queue + derank)
echo  2. Derank AFK    (accept + disconnect on warmup)
echo  3. AFK Reconnect (accept + reconnect)
echo.
set /p MODE="Select mode (1/2/3): "

if "%MODE%"=="1" (
    set "CS2_TOOLKIT_DERANK_AFK=0"
    set "CS2_TOOLKIT_AUTO_RECONNECT=0"
) else if "%MODE%"=="2" (
    set "CS2_TOOLKIT_DERANK_AFK=1"
    set "CS2_TOOLKIT_AUTO_RECONNECT=0"
) else if "%MODE%"=="3" (
    set "CS2_TOOLKIT_DERANK_AFK=1"
    set "CS2_TOOLKIT_AUTO_RECONNECT=1"
) else (
    echo Invalid option.
    pause
    exit /b
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3 "%~dp0launcher.py"
) else (
    python "%~dp0launcher.py"
)

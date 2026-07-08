@echo off
chcp 65001 >nul
title Ticarion Bot
cd /d "%~dp0"

python "%~dp0otomasyon.py"

if errorlevel 1 (
    echo.
    echo Bot bir hatayla durdu.
)

echo.
pause

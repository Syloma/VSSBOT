@echo off
chcp 65001 >nul
title Ticarion Uzay Farmi - Jack ve Yavuz
cd /d "%~dp0"
python uzay_farmi.py
if errorlevel 1 (
    echo.
    echo Uzay farmi bir hatayla durdu.
)
pause

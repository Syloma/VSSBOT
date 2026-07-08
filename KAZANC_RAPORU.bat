@echo off
chcp 65001 >nul
title Ticarion Kazanc Raporu
cd /d "%~dp0"

python -c "import otomasyon; otomasyon.kazanc_raporunu_yazdir()"

echo.
if errorlevel 1 echo Kazanc raporu bir hatayla durdu.
pause

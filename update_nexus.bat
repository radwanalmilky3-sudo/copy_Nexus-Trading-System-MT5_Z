@echo off
REM ============================================================
REM  update_nexus.bat — تحديث يمن سمارت بضغطة واحدة (PAPER ONLY)
REM  يسحب آخر تطوير من GitHub ثم يبني الواجهة ويعيد تشغيل الأسطول
REM  ضع هذا الملف في جذر المستودع: D:\Nexus-Trading-System-MT5_Z
REM ============================================================
chcp 65001 >nul
title Nexus Update - Yemen Smart
cd /d "%~dp0"

echo.
echo ============================================
echo   [1/4] Pulling latest from GitHub ...
echo ============================================
git pull --rebase origin main
if errorlevel 1 goto :err

echo.
echo ============================================
echo   [2/4] Building dashboard (2-4 min) ...
echo ============================================
for /f %%i in ('git rev-parse --short HEAD') do set BUILD=%%i
cd dashboard
call npm install --no-audit --no-fund --loglevel=error
if errorlevel 1 goto :err
set NEXT_PUBLIC_BUILD_ID=%BUILD%
call npm run build
if errorlevel 1 goto :err
cd ..

echo.
echo ============================================
echo   [3/4] Restarting fleet (PAPER) ...
echo ============================================
call venv-nexus\Scripts\python.exe run.py --stop
start "NEXUS" /min call venv-nexus\Scripts\python.exe run.py --paper

echo.
echo ============================================
echo   [4/4] DONE - build %BUILD%
echo   Open: http://127.0.0.1:3100
echo   (wait ~60s for all 9 services)
echo ============================================
pause
exit /b 0

:err
echo.
echo *** UPDATE FAILED - read the messages above ***
pause
exit /b 1

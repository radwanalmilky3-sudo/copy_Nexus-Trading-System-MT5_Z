@echo off
setlocal
REM ============================================================
REM  Nexus Trader - stop script  (created 2026-10-24)
REM   1) .venv python run.py --stop  -> graceful stop of the
REM      9 services :9000-9008 + dashboard :3100
REM   2) taskkill ollama.exe         -> only if it is running
REM   3) redis5 Windows service      -> intentionally left alone
REM ============================================================
cd /d "D:\Nexus-Trading-System-MT5"

echo [nexus] Stopping Nexus ...

REM --- 1) graceful supervisor stop -----------------------------------
if exist ".venv\Scripts\python.exe" (
    echo [nexus] run.py --stop: services on :9000-9008 and dashboard :3100
    ".venv\Scripts\python.exe" run.py --stop >nul 2>&1
) else (
    echo [nexus] WARNING: .venv\Scripts\python.exe not found - run.py --stop skipped
)
echo [nexus] Note: run.py --stop also stops the foreground supervisor from start_nexus

REM --- 2) short grace period ------------------------------------------
REM     timeout needs an interactive console; ping is the fallback.
cmd /c exit 0
timeout /t 3 /nobreak >nul 2>&1
if errorlevel 1 ping -n 4 127.0.0.1 >nul 2>&1

REM --- 3) count listeners that are still up (read-only) ----------------
set /a LEFT=0
for %%P in (9000 9001 9002 9003 9004 9005 9006 9007 9008 3100) do (
    netstat -ano -p TCP | findstr "LISTENING" | findstr /r /c:":%%P " >nul
    if not errorlevel 1 set /a LEFT+=1
)

REM --- 4) Ollama: terminate only when it is really running -------------
set "OLLAMA_STOPPED=0"
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | findstr /I "ollama.exe" >nul
if errorlevel 1 (
    echo [nexus] Ollama not running - :11434 untouched
) else (
    taskkill /IM ollama.exe /F >nul 2>&1
    if not errorlevel 1 set "OLLAMA_STOPPED=1"
    echo [nexus] Ollama stopped - ollama.exe terminated
)

REM --- 5) Redis 5 service: deliberately NOT stopped ---------------------
echo [nexus] Windows service "redis5" left running on :6379 on purpose
sc query redis5 2>nul | findstr "STATE"

REM --- 6) summary -------------------------------------------------------
echo.
echo [nexus] ---------- STOP SUMMARY ----------
if "%LEFT%"=="0" (
    echo [nexus] Nexus services : all stopped - ports 9000-9008 and 3100 free
) else (
    echo [nexus] Nexus services : %LEFT% of 10 ports still listening - not fully stopped
)
if "%OLLAMA_STOPPED%"=="1" (
    echo [nexus] Ollama         : stopped - ollama.exe killed
) else (
    echo [nexus] Ollama         : was not running - unchanged
)
echo [nexus] Redis 5         : left running - redis5 service on port 6379
echo [nexus] ================================
endlocal

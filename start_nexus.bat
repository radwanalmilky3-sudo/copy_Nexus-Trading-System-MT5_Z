@echo off
setlocal
REM ============================================================
REM  Nexus Trader - launcher  (rev 2026-10-24)
REM  Order: Redis 5 service -> Ollama portable -> run.py
REM  run.py boots the 9 services on :9000-9008 + dashboard :3100,
REM  health-gates them and auto-restarts crashed ones.
REM  Stop with: stop_nexus.bat
REM ============================================================
cd /d "D:\Nexus-Trading-System-MT5_Z"

set "NEEDWAIT=0"

REM --- Redis 5.0.14 (Streams: XADD/XREADGROUP are required) ---------
REM     Redis 5 runs as the Windows service "redis5" (Automatic).
REM     Only when :6379 is free do we start it, and only via
REM     Start-Service (never a second redis-server on top of it).
REM     redis-server.exe is a last resort if the service is absent.
netstat -ano -p TCP | findstr "LISTENING" | findstr /r /c:":6379 " >nul
if errorlevel 1 (
    set "NEEDWAIT=1"
    sc query redis5 >nul 2>&1
    if not errorlevel 1 (
        echo [nexus] Service redis5 exists but :6379 is free - starting it
        powershell -NoProfile -Command "Start-Service redis5"
    ) else if exist "C:\redis5\redis-server.exe" (
        echo [nexus] Service redis5 not installed - fallback redis-server.exe
        start "Redis 5" /min "C:\redis5\redis-server.exe" "C:\redis5\redis.conf"
    ) else (
        echo [nexus] WARNING: no redis5 service and no redis-server.exe - :6379 stays down
    )
) else (
    echo [nexus] Redis 5 already listening on :6379
)

REM --- Ollama (portable, models on D:) --------------------------------
REM     The "OllamaServe" logon task owns autostart; we only start
REM     ollama.exe ourselves when :11434 is free, so we never fight it.
netstat -ano -p TCP | findstr "LISTENING" | findstr /r /c:":11434 " >nul
if errorlevel 1 (
    set "NEEDWAIT=1"
    if exist "D:\Ollama\app\ollama.exe" (
        echo [nexus] Ollama not on :11434 - starting portable "ollama serve"
        set "OLLAMA_MODELS=D:\Ollama\models"
        set "OLLAMA_KEEP_ALIVE=-1"
        start "" /min "D:\Ollama\app\ollama.exe" serve
    ) else (
        echo [nexus] WARNING: D:\Ollama\app\ollama.exe missing - AI will be offline
    )
) else (
    echo [nexus] Ollama already listening on :11434
)

REM --- grace period, only if something was just started ---------------
if "%NEEDWAIT%"=="1" (
    echo [nexus] Waiting for Redis/Ollama to accept connections ...
    cmd /c exit 0
    timeout /t 10 /nobreak >nul 2>&1
    if errorlevel 1 ping -n 11 127.0.0.1 >nul 2>&1
)

REM --- read-only re-check so run.py preflight does not fail blind -----
netstat -ano -p TCP | findstr "LISTENING" | findstr /r /c:":6379 " >nul
if errorlevel 1 echo [nexus] WARNING: :6379 still not listening - preflight may fail
netstat -ano -p TCP | findstr "LISTENING" | findstr /r /c:":11434 " >nul
if errorlevel 1 echo [nexus] WARNING: :11434 still not listening - AI features offline

REM --- pre-flight sanity ------------------------------------------------
set "PYEXE=.venv\Scripts\python.exe"
if not exist ".venv\Scripts\python.exe" set "PYEXE=venv-nexus\Scripts\python.exe"
if not exist "%PYEXE%" (
    echo [nexus] ERROR: no .venv or venv-nexus python found in %CD%
    exit /b 1
)
if not exist "run.py" (
    echo [nexus] ERROR: run.py not found in %CD%
    exit /b 1
)

REM --- full system supervisor (foreground) ------------------------------
REM     Use --skip-preflight only if you need to boot with AI/MT5 offline.
echo [nexus] Starting supervisor run.py - services :9000-9008 + dashboard :3100
"%PYEXE%" run.py
endlocal

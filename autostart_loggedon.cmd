@echo off
REM ============================================================
REM  Nexus Trader - auto-start at user logon
REM  Referenced by the "NexusTrader" shortcut in shell:startup.
REM  Safety rules:
REM    1. Never start a second instance (ports already open = exit).
REM    2. Wait for Ollama (the "OllamaServe" logon task may be
REM       racing us) before run.py's pre-flight runs.
REM  Stopping the system: run stop_nexus.bat (or run.py --stop).
REM ============================================================
title Nexus Trader - autostart

REM --- already running? then do nothing ---
netstat -ano | findstr ":9001" | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo [nexus] System already running on :9001 - autostart skipped.
    timeout /t 10 /nobreak >nul
    exit /b 0
)

REM --- wait for Ollama, max 60s ---
set /a waited=0
:wait_ollama
netstat -ano | findstr ":11434" | findstr "LISTENING" >nul
if not errorlevel 1 goto ollama_ready
timeout /t 5 /nobreak >nul
set /a waited+=5
if %waited% lss 60 goto wait_ollama
echo [nexus] Ollama not up after 60s - starting anyway (pre-flight may warn).
:ollama_ready

REM --- give the desktop a moment to settle after logon ---
timeout /t 10 /nobreak >nul

call "D:\Nexus-Trading-System-MT5\start_nexus.bat"
exit /b %ERRORLEVEL%

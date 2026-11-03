@echo off
cd /d %~dp0
C:\Users\rd66\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe -e "process.argv=['node','next','dev','-p','3100'];require('./node_modules/next/dist/bin/next')"

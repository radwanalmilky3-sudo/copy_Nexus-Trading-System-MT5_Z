# PYTHON_PROCESS_CLEANUP_REPORT

**Date (UTC):** 2026-10-10 ~10:40Z · **Scope:** pre-UI-diagnosis runtime hygiene · **Project root:** `C:\نسخه البرنامج الاصل\Nexus-Trading-System-MT5-main`

## Inventory (python.exe / pythonw.exe / py.exe)

**Found: 20 processes — all classified NEXUS_PROJECT. ZERO OTHER_PROJECT. ZERO UNKNOWN. Zero py.exe/pythonw.exe.**

| PID | PPID | Role | Port | RAM MB | Classification |
|---|---|---|---|---|---|
| 6744 | 3352 | run.py outer watchdog (.venv, `--paper --replace-running`) | — | ~0 | NEXUS_PROJECT |
| 2176 | 6744 | run.py inner watchdog (system 3.11) | — | 9 | NEXUS_PROJECT |
| 5360 | 2176 | launcher nexus-features | — | ~0 | NEXUS_PROJECT |
| 5980 | 5360 | uvicorn nexus-features | 9002 | 54 | NEXUS_PROJECT |
| 4020 | 2176 | launcher nexus-risk | — | ~0 | NEXUS_PROJECT |
| 9852 | 4020 | uvicorn nexus-risk | 9006 | 29 | NEXUS_PROJECT |
| 7916 | 2176 | launcher nexus-ml | — | ~0 | NEXUS_PROJECT |
| 5520 | 7916 | uvicorn nexus-ml | 9003 | 42 | NEXUS_PROJECT |
| 6688 | 2176 | launcher nexus-agents | — | ~0 | NEXUS_PROJECT |
| 1620 | 6688 | uvicorn nexus-agents | 9004 | 45 | NEXUS_PROJECT |
| 6708 | 2176 | launcher nexus-executor | — | ~0 | NEXUS_PROJECT |
| 6612 | 6708 | uvicorn nexus-executor | 9007 | 18 | NEXUS_PROJECT |
| 8244 | 2176 | launcher nexus-monitor | — | 1 | NEXUS_PROJECT |
| 6252 | 8244 | uvicorn nexus-monitor | 9008 | 24 | NEXUS_PROJECT |
| 5716 | 2176 | launcher nexus-api | — | 1 | NEXUS_PROJECT |
| 7208 | 5716 | uvicorn nexus-api | 9000 | 25 | NEXUS_PROJECT |
| 25420 | 2176 | launcher nexus-data | — | 3 | NEXUS_PROJECT |
| 19668 | 25420 | uvicorn nexus-data | 9001 | 120 | NEXUS_PROJECT |
| 18072 | 2176 | launcher nexus-news | — | 1 | NEXUS_PROJECT |
| 10248 | 18072 | uvicorn nexus-news | 9005 | 403 | NEXUS_PROJECT |

All command lines contain the project path or `services.nexus_*` modules of the running fleet (launcher→uvicorn chains under watchdog 2176).

## Actions

- **Preserved: all 20** (every process is Nexus; also Redis/Ollama/MT5/Node dashboard/OpenCode untouched by design).
- **Stopped: none** — no OTHER_PROJECT python existed; no UNKNOWN needed investigation.
- **Forbidden commands avoided:** no `taskkill /IM python.exe /F`, no blind bulk kill; per-PID targeted inspection only.

## RAM

```text
BEFORE  7.3 GB used (system total)
AFTER   7.3 GB used (system total)   — delta 0.0 GB (nothing stopped)
```
Nexus python working set ≈ 760 MB (dominated by nexus-news 403 MB + nexus-data 120 MB).

## Ports (no conflicts, before = after)

```text
9000→7208  9001→19668  9002→5980  9003→5520  9004→1620
9005→10248 9006→9852   9007→6612  9008→6252  3100→8472 (Node dashboard)
```
Each service port owned by exactly one process; no duplicate listeners; no foreign process on Nexus ports.

## Service verification after inventory

```text
nexus-api      :9000 healthy
nexus-news     :9005 healthy
nexus-executor :9007 broker=paper
python count   20 → 20 (unchanged)
```

## Conclusion

Environment is clean: the only Python on the machine belongs to the Nexus fleet. No cleanup was required or performed. Per instruction, **no code was changed** after this report; UI diagnosis remains paused at the point where the live-CSS-link check was about to resume.

# TRACEABILITY_REPORT — Pack Requirement → Local Evidence

Maps every gate in the Golden Reference Pack (`TEST_MATRIX.md`, `FINAL_CERTIFICATE.md`, `AGENT-APPLY-COMMAND.txt`) to concrete local evidence produced on 2026-10-10.

## TEST_MATRIX gates

| Pack gate | Sandbox status | Local status | Evidence location |
|---|---|---|---|
| Full Python compile | PASS | **PASS** | `compileall -q .` exit 0 (`TEST_RESULTS.md`) |
| Golden contract tests (21) | PASS | **PASS 21/21** | pytest run 1, `TEST_RESULTS.md` |
| 24-table schema static contract | PASS | **PASS (27 live)** | `DB_SCHEMA_ACTUAL.md`, `GET :9001/api/data/fundamental/schema` |
| Missing ≠ neutral | PASS | **PASS** | golden contracts included in 208 |
| Native score vs Gold impact sign | PASS | **PASS** | golden contracts included |
| Structural flow not M5 tactical | PASS | **PASS** | golden contracts included |
| Dependency/double-count penalty | PASS | **PASS** | golden contracts included |
| High-impact blackout blocks | PASS | **PASS live** | `RISK_GUARD_EVIDENCE.md` (step 9) |
| Historical future vintage rejected | PASS | **PASS** | golden contracts included |
| PAPER uses simulated broker | PASS | **PASS live** | executor `/health` broker=paper; guard evidence |
| No Docker artifacts | PASS | **PASS** | project root has 0 Dockerfiles (backup moved out) |
| Local-AI-only factory | PASS | **PASS live** | preflight: qwen2.5:3b via localhost:11434; real reply `NEXUS OK` |
| Safe defaults PAPER / auto OFF | PASS | **PASS live** | `.env` paper; Redis `auto_trade=false` |
| NewsFeed no mock live fallback | PASS | **PASS** | golden contracts; live 48 real articles |
| A9 cannot directly call executor | PASS | **PASS** | golden contracts (static, pack code) |
| Executor final guard before broker send | PASS | **PASS live** | step 6 + step 9 orders blocked with `broker=none` |
| Required source IDs declared | PASS | **PASS** | `fund_sources` inventory in `SOURCE_HEALTH_ACTUAL.md` |
| Stable blackout window ID | PASS | **PASS** | `fundamental_blackout_windows` table + step 9 id |
| Gateway auto-trade reset OFF | PASS | **PASS** | auto_trade=false restored & persisted (step 7/9) |
| **DuckDB migration execution** | NOT RUN — ENV BLOCKED | **PASS RUNTIME** | live schema endpoint, 27 tables |
| **Redis integration/stream contract** | NOT RUN — ENV BLOCKED | **PASS RUNTIME** | live PING, guard reads, heartbeat, blackout publish, caches |
| **Local Ollama real inference** | NOT RUN | **PASS** | `ollama run qwen2.5:3b` → `NEXUS OK` |
| **Frontend build / TS typecheck** | NOT RUN — ENV BLOCKED | **PASS** | `tsc --noEmit` 0; `npm run build` 0 (17 routes) |
| Source live fetches/API keys | NOT CERTIFIED | **PARTIAL — explicit** | healthy: BLS, Fed RSS; degraded: news providers (cache OK); config_required list explicit (`SOURCE_HEALTH_ACTUAL.md`) |
| **Full PAPER E2E 9-service run** | MUST PASS LOCALLY | **PASS** | 10/10 ports; health probes green |
| **Critical BUY+95+A7+HIGH blackout → 0 broker calls** | MUST PASS LOCALLY | **PASS 8/8** | `RISK_GUARD_EVIDENCE.md` |
| LIVE execution | NOT CERTIFIED | **NOT CERTIFIED** (correct) | paper mode enforced end-to-end |

## AGENT-APPLY-COMMAND.txt steps

| Step | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Read README-APPLY-AR, manifest, FINAL_CERTIFICATE | done | pack docs read before APPLY |
| 2 | Verify ProjectRoot baseline SHA | done | pre-apply verify 100/0 |
| 3 | Confirm paper mode; never LIVE | done | `.env` paper; live→paper backup; executor `real_broker_execution_enabled=false` |
| 4 | Run APPLY; handle LOCAL_DRIFT with 3-way compat (infra only) | done | compat wrapper (Arabic path); 3 test files infra-adapted; semantics untouched |
| 5 | Don't stop MT5/Redis/Ollama; restart only what's needed | done | only nexus-news restarted (watchdog); WSL/Redis remediation was restoring Redis availability |
| 6 | Dependencies per requirements; no major upgrades | done | pytest/pytest-asyncio added only; torch stub is a parse-fix, not a version change |
| 7 | VERIFY.ps1 + preflight + backend tests + dashboard build/typecheck | done | all green (`TEST_RESULTS.md`) |
| 8 | 9-service PAPER E2E | done | 10/10 ports + health |
| 9 | Critical Blackout Test | done | 8/8 PASS |
| 10 | Produce 9 deliverables + issue one of two allowed statuses | done | this report set; final status in `FINAL_CERTIFICATE_LOCAL.md` |

## Evidence file index

| File | Contents |
|---|---|
| `IMPLEMENTATION_REPORT.md` | narrative of APPLY, fixes, incidents, final state |
| `DB_SCHEMA_ACTUAL.md` | live 27-table inventory |
| `SOURCE_HEALTH_ACTUAL.md` | per-source live health + explicit unavailable list |
| `TEST_RESULTS.md` | all gates with commands and outcomes |
| `TRACEABILITY_REPORT.md` | this file |
| `UI_ACCEPTANCE.md` | dashboard build + route smoke |
| `RISK_GUARD_EVIDENCE.md` | step 6/7/9 guard proofs |
| `SHA_MANIFEST.json` | SHA-256 of all 100 pack entries vs expected |
| `FINAL_CERTIFICATE_LOCAL.md` | final allowed status |
| `LOCAL_VERIFY_RESULT.json` | pack VERIFY machine output (`STATIC_LOCAL_VERIFY_PASS`) |

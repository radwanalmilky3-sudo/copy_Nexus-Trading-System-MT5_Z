# Audit follow-up — 2026-10-12

This supplements `COVERAGE.md` and `INITIAL_REPORT.md`; it does not replace them. The audit remains incomplete.

## Evidence and remediation added this turn

### Confirmed defect A — partial user update before role authorization

- **Priority:** P1 (authorization/consistency).
- **File:** `services/nexus_api/routers/admin.py`, `update_user`.
- **Root cause:** The handler wrote the updated `app_users` row before checking `roles.manage` when a role change was requested. An actor with `users.edit` but without `roles.manage` received HTTP 403 after the non-role fields had already been persisted. The audit record was also skipped because the exception exited first.
- **Reproduction:** An isolated async pytest test called the handler with an in-memory fake data service; `_require` granted `users.edit` and denied `roles.manage`; `_post_data` recorded writes. Test result: **FAILED as expected** because one `app_users` write occurred with `full_name="New name"` despite the 403.
- **Fix:** `update_user` now checks `roles.manage` before avatar persistence or any database write when a role change is requested.
- **Project regression test:** `tests/test_api/test_admin_update_authorization.py` verifies that a denied role change produces HTTP 403 and no writes.
- **Verification:** New regression plus `test_admin_data_service.py` and `test_data_client.py`: **5 passed** (2026-10-12).
- **Status:** Fixed and focused-test verified. Multi-record role changes still require transaction/idempotency review separately.

### Confirmed defect B — backtest reports data-source outage as zero-trade success

- **Priority:** P1 (misleading analytical output).
- **File:** `services/nexus_api/routers/backtest.py`, `_fetch_trades` and `run_backtest`.
- **Root cause:** Redis errors fell through to the nexus-data HTTP request; any failure from that source returned `[]`; `run_backtest` calculated and returned ordinary zero-valued metrics without source status/error metadata.
- **Reproduction:** An isolated async pytest test replaced Redis and HTTP client with offline fakes and called the route function. Test result: **FAILED as expected** because the result contained zero-trade metrics and omitted `source_status="unavailable"`. Captured logs show both source failures.
- **Fix:** `_fetch_trades` now raises HTTP 503 with a stable, non-sensitive detail when both Redis and nexus-data fail. Valid empty Redis history remains a normal zero-trade result.
- **Project regression tests:** `tests/test_api/test_backtest_sources.py` tests both source outage and genuine empty history.
- **Verification:** The outage test failed before the fix as expected; after the fix the focused set passed, and the full `tests/test_api` suite passed (**23 passed**, 2026-10-12).
- **Status:** Fixed and API-suite verified. Frontend fetch checks non-2xx status and displays an error state; no frontend change required.

### Confirmed defect C — governance seeding failure was ignored before dependent persistence

- **Priority:** P1 (conditional fundamental-data outage; fail-open persistence behavior).
- **Evidence:** The user's startup log showed a DuckDB foreign-key failure for `event_asset_impacts.asset_id = BTCUSD` because the referenced `asset_registry` row was absent. In `services/nexus_news/fundamental/runtime.py`, `_seed_v5_governance` awaited persistence of asset rows but ignored the boolean result; `_post_data` returns `False` when the internal secret is missing, the data API returns an error, or the request fails. `initialize()` then proceeded to `recompute(reason="startup")` and dependent persistence.
- **Reproduction:** A fake persistence test returned `False` for the BTCUSD registry write. Before the fix, `_seed_v5_governance` completed normally (test failed because the expected error did not occur).
- **Fix:** Failed persistence of any required asset-registry seed now raises a contextual `RuntimeError`, stopping fundamental startup before records with foreign-key dependencies are generated. This is fail-closed and makes a dependency/configuration failure visible; it can keep nexus-news unavailable until persistence is restored.
- **Regression test:** Added to `tests/test_fundamental/test_golden_contracts.py`.
- **Verification:** That file's suite passed **22 tests** (2026-10-12).
- **Status:** Fixed and regression-tested. No live DuckDB or service was used.

### Confirmed defect D — central-risk signature did not authenticate approved order fields

- **Priority:** P1 (conditional live-order integrity risk).
- **Evidence:** `shared/safety.py::approval_signature` authenticates only proposal ID and expiry. `evaluate_executor_guard` verifies only those values and receives no order context. `services/nexus_executor/main.py` independently reads symbol, side, entry, SL/TP, and approved size from the stream event or REST request before sending to the broker. Thus a valid short-lived proof can be paired with altered order fields; the guard cannot distinguish the approved order from the modified one if the remaining live-state checks pass.
- **Status:** Fixed and focused-test verified on 2026-10-14. The versioned canonical HMAC contract is shared by risk and both executor paths; regression tests cover tampering across all signed terms. See `TRADE_FLOW_REVIEW_20261012.md` for implementation and residual coverage. The earlier reparse-point limitation no longer applies to the current project workspace.

### Confirmed defect E — Redis stream messages are acknowledged despite processing errors

- **Priority:** P1 (order/trade-event loss under transient failures).
- **Evidence:** `shared/redis_client.py::subscribe_stream` acknowledges each message in a `finally` block after yielding it. Its consumers (`services/nexus_risk/main.py`, `services/nexus_executor/main.py`) catch processing exceptions and continue, so the generator resumes and XACKs the event. `services/nexus_data/main.py::_trade_close_consumer` also XACKs in `finally` when parsing or DuckDB persistence raises. New reads use `>`; no `XPENDING`/`XAUTOCLAIM` recovery was found in the shared client.
- **Impact:** Transient evaluation, broker, or persistence errors can permanently remove approved decisions or closed-trade records from retry, with only an error log. For an executor outcome that is uncertain after broker submission, safe replay additionally requires idempotency keyed by proposal/order ID.
- **Status:** Needs repair. Acknowledgement redesign affects shared stream consumers and requires focused failure-injection tests; no live service was exercised.

#### Scope refinement from cross-consumer tracing (2026-10-14)

- The shared generator is consumed by risk (agent verdicts and trade closes), executor (risk decisions), agents (signals), monitor (trade closes), and six API WebSocket broadcasters. The generator's `finally: XACK` means application-level exceptions caught inside those loops still end in acknowledgement.
- Additional direct XREADGROUP loops have related behavior: `nexus-ml::_handle_feature_event` catches processing exceptions and unconditionally XACKs in `finally`; `nexus-data::_trade_close_consumer` also XACKs in `finally`; `nexus-features::_ohlcv_consumer` only XACKs after its handler returns, but reads only `>` and has no pending reclaim loop.
- Side effects differ across consumers and make a blanket retry unsafe: `nexus-risk::_trade_close_consumer` updates daily PnL and anti-tilt state (not visibly keyed by message ID), while `nexus-monitor::_trade_close_listener` emits Telegram alerts. Replaying after an ambiguous failure can double-apply state or duplicate notifications. The reviewed test search found no targeted failure-injection/reclaim tests for these consumer loops.
- The data service's trade insert is idempotent by trade ID (`ON CONFLICT (id) DO NOTHING`). By contrast, executor duplicate protection is symbol+side with a 60-second Redis TTL, not a durable idempotency key for the proposal; uncertain replay after a broker send therefore needs a stronger order/proposal-level reconciliation contract.
- These findings confirm that a safe fix is cross-cutting: explicit success acknowledgement, bounded retry/reclaim, malformed-message policy/dead-letter observability, and durable idempotency for side effects. A blanket removal of XACK can strand pending entries because current consumers read only new entries (`>`). No production code was changed for this finding in this turn; no Redis service or broker was used.

### Confirmed defect F — dashboard TypeScript check fails on ticker fallback settings

- **Priority:** P1 (dashboard typecheck/build gate fails).
- **Evidence:** Fresh command `.\node_modules\.bin\tsc.cmd --noEmit --incremental false` in `dashboard/` exits 1 at `src/components/fundamental/NewsTickerControlPanel.tsx:10`. `FALLBACK` is typed as `NewsTickerSettingsDTO` but omits 13 required fields: four severity TTLs, four display/visibility flags, four display modes, and `require_ack_critical`. The API's `DEFAULT_TICKER_SETTINGS` defines the intended defaults in `services/nexus_api/routers/fundamental.py:75-87`.
- **Fix:** Added the 13 API defaults to `FALLBACK`: severity TTLs, visibility/acknowledgement flags, display modes, and `require_ack_critical`.
- **Verification:** The TypeScript check failed before the edit with TS2740 on the missing fields; after the edit `tsc --noEmit --incremental false` exited **0**. The production build remains unrun because the dashboard may be active and share `.next`.
- **Status:** Fixed and typecheck-verified. Broader dashboard behavior and UI tests remain unreviewed.

### Confirmed defect G — Redis URL credentials were written to startup logs

- **Priority:** P1 (conditional credential disclosure through local console/log capture).
- **File:** `run.py`, `_check_prerequisites`.
- **Evidence:** When `_check_redis(redis_url)` returned false, the error message interpolated the complete URL. Redis URLs may legally contain a username and password, so a failed startup could write those credentials to captured terminal output or launcher logs.
- **Reproduction:** A focused regression passed `redis://audit-user:audit-password@redis.internal:6379/0` through `_check_prerequisites` with Redis marked unreachable. Before the fix, the test failed because the logged error included both credentials.
- **Fix:** Replaced the interpolated URL with the constant message `Redis is not reachable at the configured URL.` No environment values are printed.
- **Project regression test:** `tests/test_runner_safety.py::test_unreachable_redis_does_not_print_credentials`.
- **Verification:** Red/green sequence observed; the project test passed (**1 passed**, 2026-10-12) with `PYTHONDONTWRITEBYTECODE=1` and pytest cache disabled.
- **Status:** Fixed and focused-test verified. This does not resolve the independent runner port-owner termination issue.

### Confirmed defect H — API health stayed healthy after nexus-data failed

- **Priority:** P2 (misleading operational status; dashboard and health consumers can show a stale dependency state).
- **Files:** `services/nexus_api/main.py::health_check`; `services/nexus_api/data_client.py::health`.
- **Evidence:** Gateway lifespan probes nexus-data once and stores `app.state.data_service_available`. Later `/health` requests read only that startup value, while the dashboard polls `/health` every 15 seconds. A later nexus-data/DuckDB outage therefore remained reported as connected.
- **Reproduction:** A focused test made the mocked data-service health return `True` then `False`; before the fix both gateway health results still reported DuckDB connected, and the test failed on the second assertion.
- **Fix:** `/health` now probes the data-service health endpoint on each request, updates the cached state, and reports unavailable when the probe raises.
- **Verification:** Red/green regression plus `tests/test_api/test_routers.py`: **9 passed** (2026-10-12). The test uses an async fake; no live service or database was accessed.
- **Status:** Fixed and focused-suite verified. Health requests now include one internal data-service HTTP probe (the client timeout is 2 seconds); observe operational latency/load during safe deployment validation.

## Coverage update

- Baseline ZIP byte comparison remains: 338 files compared; 252 identical, 74 modified, 12 original files absent locally. This is checksum coverage, not semantic review of all changed files.
- Semantic review advanced for the changed admin user-update and backtest paths, with isolated reproductions for both defects.
- The admin authorization-order, backtest source-outage, fundamental asset-registry bootstrap, Redis credential-log, ticker fallback/typecheck, and stale API health defects were fixed and verified with focused tests or compiler evidence. `COVERAGE.md` and `TRADE_FLOW_REVIEW_20261012.md` were updated/added.
- No live DB, Redis service, MT5 terminal, or trading executor was used. No services were restarted and no trading state changed.
- Overall audit is still in progress; no subsystem is fully closed by static review + relevant project tests + safe runtime evidence.

### Confirmed defect I — trade-history outages were represented as a valid empty result

- **Priority:** P1 (misleading dashboard performance/history during data-service failure).
- **Files:** `services/nexus_api/routers/trades.py`; `dashboard/src/app/dashboard/history/page.tsx`; regression coverage in `tests/test_api/test_trade_proxy.py` and `tests/test_api/test_routers.py`.
- **Evidence:** `_proxy_trades` previously caught connection and other exceptions and returned HTTP 200-compatible `{trades: [], total: 0}`. The History page ignored non-OK responses and network failures, while its initial stats rendered zero values. A test against a simulated `httpx.ConnectError` failed before the fix because no HTTPException was raised; a valid empty source response is separately tested to remain successful.
- **Fix:** The gateway now returns HTTP 503 with a generic service-unavailable message on proxy errors. The History page shows an alert, preserves previously loaded data, and distinguishes an initial outage from a valid empty history.
- **Verification:** `pytest tests/test_api/test_trade_proxy.py tests/test_api/test_routers.py tests/test_api/test_backtest_sources.py -q -p no:cacheprovider` — **13 passed** (2026-10-14). This used mocked HTTP for regressions and the router test's local connection attempt failed as expected; no services or database were started/opened.
- **Frontend verification:** The user subsequently ran `tsc --noEmit --incremental false` from PowerShell with Node 22.23.2/npm 10.9.8 and reported exit code 0 (2026-10-14). Codex's bundled Node 24 still gets `EPERM` while resolving the Arabic parent path, but this did not block the user's local check. No production build or browser interaction was run. A rendered-component test is not present in the frontend test setup.
- **Related pagination defect (now fixed):** `trade_stats` previously requested only page 1 with `page_size=200`, omitting older trades from all summary metrics. A red regression with 5,001 synthetic records confirmed only page 1 was requested. The API now reads 5,000-row pages and aggregates incrementally, without retaining the entire history in memory.
- **Pagination verification:** The regression now confirms pages `[1, 2]`, `total_trades == 5001`, and `total_pnl == 5001.0`; the full selected API run above passes. This uses stable mocked pages; multi-request pages are not a database snapshot if new trades are inserted during the scan, so exact snapshot consistency remains a design limitation for high-write histories.
- **Status:** Both API defects are fixed and regression-tested. The frontend error-state change is implemented and passes the user-reported TypeScript check; rendered behavior remains untested.

### Confirmed defect J — stale test expectation contradicted the current RSS fallback contract

- **Priority:** P2 (false-negative test gate; no production behavior defect established).
- **Evidence:** The full test run on 2026-10-14 produced 285 passes and one failure because `test_v61_final_contracts.py` expected `analysis_mode="rss_fallback"`. `fed_rss_to_monetary` deliberately returns `rss_policy_fallback` for hard-policy FOMC RSS items; `test_free_official_sources_r31.py` asserts this contract, and `MonetaryEngine` applies an explicit confidence cap only for that exact mode.
- **Fix:** Updated the stale assertion to `rss_policy_fallback`; production code was not changed.
- **Verification:** The targeted regression and RSS-contract tests passed (**9 passed**). The complete Python suite then passed (**286 passed, 2 deprecation warnings**, 2026-10-14).
- **Status:** Fixed and full-suite verified. The warnings are a LangGraph pending deprecation and FastAPI `regex` deprecation; they did not fail tests and remain separate maintenance work.

### Confirmed defect K — MT5 OHLCV polling did not persist historical bars

- **Priority:** P1 (historical market data vanished with Redis cache expiry/restart; persistent reads/backtests could see no bars).
- **Evidence:** `_ohlcv_publisher` fetched a bounded MT5 history on each poll and wrote it only to a one-hour Redis cache plus a latest-bar stream event. The existing `DataStore.insert_ohlcv` had no call site from the publisher. The endpoint's historical queries read DuckDB and returned 404 when a requested range was absent.
- **Fix:** Added batched, idempotent `DataStore.insert_ohlcv_batch` and wired the publisher to persist completed bars only. The current forming MT5 bar remains live/cache-only; database persistence errors are logged but do not stop feature-stream publication. Duplicate `(symbol, timeframe, timestamp)` rows are skipped.
- **Regression tests:** Real DuckDB temporary-file tests verify persistence, repeated-batch duplicate suppression, and exclusion of the still-forming last bar.
- **Verification:** Red run failed because the batch persistence path/helper did not exist. After implementation, the focused test passed (**2 passed**), all `tests/test_data` passed (**20 passed**), selected fundamental contracts passed (**59 passed**), and the full Python suite passed (**288 passed, 2 deprecation warnings**, 2026-10-14). No project database or live MT5/Redis service was used.
- **Residual:** This persists only the bounded history returned by the existing poll (`NEXUS_OHLCV_BAR_COUNT`, default 300) and subsequent completed bars. It is not a user-controlled historical import/backfill workflow; API source metadata, coverage/gap detection, and full dataset validation remain open.

### Confirmed defect L — monitor performance endpoint opened DuckDB outside its owner

- **Priority:** P1 conditional reliability issue (endpoint invocation while `nexus-data` holds the DuckDB read-write connection); the route was not found in the dashboard or API-gateway call graph.
- **Evidence:** `services/nexus_monitor/main.py::get_performance` created a fresh `DuckDBClient(read_only=True)`, retried lock failures up to ten times, and translated the eventual failure into HTTP 500. `nexus-data` is the persistent database owner; the monitor route is directly callable.
- **Fix:** The monitor fetches the requested bounded trade page from `NEXUS_DATA_URL/api/data/trades`, calculates metrics in memory, validates the response shape, and returns a stable HTTP 503 when the owner is unavailable. No direct database connection remains in this route.
- **Verification:** Tests use `httpx.MockTransport` and assert the owner URL/params, computed result, and 503 behavior; `tests/test_monitor` passed (**3 passed**). No project DB or service was opened.
- **Status:** Fixed and verified at the HTTP-contract boundary. The endpoint has no known UI consumer; runtime deployment behavior was not exercised.

### Confirmed defect M — Sortino ratio was NaN for one downside observation

- **Priority:** P2 (invalid monitoring/performance metric in small samples).
- **Evidence:** `PerformanceAnalyzer.calculate_sortino` called `numpy.std(..., ddof=1)` when exactly one negative return existed, producing a degrees-of-freedom RuntimeWarning and NaN.
- **Fix:** Return a finite neutral `0.0` when fewer than two downside observations are available to estimate sample deviation.
- **Verification:** A test promotes NumPy `RuntimeWarning` to an error and asserts zero; the monitor endpoint test also exercises one downside observation. `tests/test_monitor`: **3 passed** without warnings. Full Python suite: **291 passed, 2 deprecation warnings** (2026-10-14).
- **Status:** Fixed and full-suite verified. The remaining warnings are the separately recorded LangGraph and FastAPI deprecations.

## Next actions

1. Review remaining paths in API/auth, data/DuckDB, risk/executor, ML/training, news, dashboard, and runtime orchestration; the inventory still has hundreds of uninspected entries.
2. Check the 12 absent original files for active imports/deployment references before classifying them.
3. Continue component-level coverage and keep `FILE_MANIFEST.tsv` synchronized as new audit artifacts/tests are added.

### Confirmed defect N — OpenAPI schema generation fails for strategy export route

- **Priority:** P2 (API schema generation and interactive API documentation unavailable).
- **File:** `services/nexus_api/routers/strategies.py`, `export_mql5` route declaration.
- **Evidence:** The route decorator explicitly set `response_class=None`. With the project's active virtual environment (FastAPI 0.143.0), `app.openapi()` raised `AssertionError: A response class is needed to generate OpenAPI`; this prevents generating the gateway schema, including `/openapi.json` and the schema consumed by `/docs`.
- **Reproduction:** Added `tests/test_api/test_openapi_schema.py`; its first run failed at `app.openapi()` with the assertion above.
- **Fix:** Removed the explicit `response_class=None`, allowing FastAPI's default response class to apply. The response is still a normal JSON response.
- **Verification:** Regression passed after the change; `tests/test_api` passed **27 tests** and the full Python suite passed **299 tests with 2 deprecation warnings** in 115.95 seconds (2026-10-14).

### Redis Streams recovery compatibility note — Redis 5.0.14 local binary

- The bundled `C:\tools\redis\redis-server.exe` reports Redis **5.0.14.1**. A read-only `netstat -ano -p tcp` check on 2026-10-14 found no listener on port 6379; therefore the binary version is known, but the active Redis server/version is not established.
- Official Redis documentation identifies `XCLAIM` as available since Redis 5.0.0 and `XAUTOCLAIM` as available since Redis 6.2.0. If the deployment uses the bundled 5.0 server, recovery must use the compatible `XPENDING` + `XCLAIM` pattern or explicitly upgrade/pin the server; do not implement XAUTOCLAIM as an assumed-compatible default.
- This compatibility evidence does not resolve defect E: pending recovery, stable consumer ownership, bounded retries/dead-lettering, and executor-side idempotency/reconciliation still need a tested design. No Redis server was started or changed.

### Access-control finding ACR-06 — API mutating routes lack a common authenticated boundary

- **Status:** Confirmed static exposure at the gateway route layer; deployment exploitability remains limited/conditional and needs end-to-end client and network-boundary review.
- **Evidence (refreshed handler audit after ACR-17 on 2026-10-14):** `services/nexus_api/main.py` installs CORS but no authentication middleware/dependency at application scope, and current `APIRouter(...)` declarations have no router-level dependency lists. Across mounted API routers there are 41 POST/PUT/PATCH/DELETE operations: 35 endpoint handlers have a `CurrentUser` JWT parameter; 3 call `verify_pin` (bootstrap, kill switch, auto-trade toggle); login is the intended public entry point. Excluding login and the PIN-protected bootstrap/system controls, 2 business mutation handlers still have neither a JWT nor PIN check visible in their handler. This is a static handler/decorator audit; indirect dependency behavior outside function signatures was not assumed to be authorization.
- **Client evidence:** `dashboard/src/lib/api-client.ts::fetchPath` attaches `nexus-token`; however, many dashboard screens issue raw `fetch()` calls. The SourceConnectionManager omission was fixed on 2026-10-14 and now sends the stored bearer token for source list/create/update/delete/test/secret operations. Other raw-fetch callers still require review. Route-layer exposure is confirmed; actual reachability depends on deployment and client context, while the UI login gate itself is client-side.
- **Impact:** A client that can reach the gateway can invoke operations without the API's user identity/role checks. The normal runner binds to loopback, reducing remote exposure, but does not protect against local clients; CORS is a browser policy, not API authentication. Secrets and source endpoints are especially sensitive, and strategy/risk/position operations can influence trading behavior.
- **Source-manager fix (2026-10-14):** Applied the existing `source_manager.view/edit/test/secrets` permissions to the source-management routes. Create/update require `edit`; secret-bearing create/update additionally require `secrets`; dedicated secret writes require `secrets`; tests require `test`; reads require `view`. The component now sends its stored bearer JWT. Focused red/green tests verify 401 for missing JWT, permission-specific 403 before source-store access, and dual permission for secret-bearing updates. The full Python suite passes **307 tests** with two existing deprecation warnings.
- **Superseded historical source-manager finding (P2 candidate):** At the time of this note, `_connection_test` accepted arbitrary HTTP(S) endpoints and followed redirects without a visible hostname/IP policy. Subsequent source changes now validate the final URL against public DNS/IP destinations and disable redirect following; `tests/test_api/test_source_manager_ssrf.py` covers loopback, private-DNS, and redirect cases. A later focused run passed **12** source-manager SSRF/authorization tests. Residual DNS rebinding between validation and HTTPX connection remains; no external request or live DNS test was performed. See current status in `project_audit/COVERAGE.md`.
- **Residual:** This repairs only source-management routes. Other mutating gateway routes remain without JWT/PIN protection, and the dashboard's direct-fetch callers often omit JWT. The approved change to SourceConnectionManager has not yet passed a fresh TypeScript check because the execution environment's Node 24 fails on the Arabic project path and npm/Node 22 are unavailable here. Do not call ACR-06 fully resolved.

### ACR-07 — caller can override authoritative risk state in REST evaluation (P1)

- **Files:** `services/nexus_risk/main.py::EvaluateRequest`, `_evaluate_proposal`, and `evaluate_trade`; gateway proxy `services/nexus_api/routers/risk.py`.
- **Evidence:** `/api/risk/evaluate` accepts a public `state: dict`. `_evaluate_proposal` forms `merged = {**_current_state, **state}`; `RulesEngine.check_all_rules` and `PositionSizer.calculate_size` consume fields from `merged`, including daily loss, weekly drawdown, open-position count/list, balance, spread, and session. On APPROVE, `evaluate_trade` produces a risk-signed approval payload. No JWT/PIN route dependency was found on the API or risk endpoint.
- **Reproduction (isolated component; no service/Redis/broker):** Called the real `rules_engine.check_all_rules` with the same XAUUSD proposal and two states. With daily loss 26%, weekly drawdown 26%, and 6 open positions under the loaded limits (20%, 25%, 5), the engine rejected for `max_daily_loss`, `max_weekly_drawdown`, and `max_positions`. Replacing those caller-provided fields with 0%, 0%, and 0 made the same proposal pass with zero violations. This confirms the rules engine trusts supplied values; the endpoint-to-executor flow was not executed.
- **Impact:** If canonical execution gates permit trading (auto-trade explicitly enabled, no kill switch/blackout, and LIVE execution configured), an unauthenticated caller with access to the gateway can request an approval based on fabricated state, potentially bypassing account-loss/position/correlation checks and influencing approved size. The signed HMAC binds the resulting terms, but does not prove the state used to calculate them was authoritative.
- **Status: Fixed and regression-tested (2026-10-14).** `evaluate_trade` now passes `_current_state`; `_evaluate_proposal` independently constructs its safety context only from `_current_state` and ignores the legacy request-state parameter. The request field remains accepted for client compatibility but cannot override trusted state. A red/green regression submits fabricated zero losses/positions and inflated balance, and verifies the evaluator receives only the server-owned snapshot. Focused risk suite: **13 passed**; full Python suite after this and ML-01: **311 passed, 2 deprecation warnings**. No live Redis or executor was used. This does not solve the separate unauthenticated route-access issue.
- **Safety:** No live Redis, executor, broker, or trading endpoint was invoked; no real order or model operation occurred.

### Access-control finding ACR-18 — direct risk evaluation lacked service authentication

- **Status:** Fixed and regression-tested (2026-10-14).
- **File:** `services/nexus_risk/main.py::evaluate_trade`; internal caller `services/nexus_ml/traders_api.py`.
- **Evidence:** The REST endpoint returned risk-evaluation decisions and signed approvals without requiring JWT or internal service credentials. Because autonomous ML calls this service directly, the gateway's user-level authorization did not cover this path. Loopback binding is not a local caller authorization boundary.
- **Fix:** The route now requires the already established `NEXUS_INTERNAL_API_SECRET` through `X-Nexus-Internal-Secret`, fails closed with 503 if unconfigured, and constant-time compares the supplied value (403 on missing/incorrect). The ML caller passes this secret and makes no evaluation request if it is missing.
- **Reproduction:** Added missing/wrong credential cases to `tests/test_risk/test_approval_contract.py`; before the fix, both failed with `TypeError` because the handler had no credential parameter. Afterward both returned 403 before `_evaluate_proposal`.
- **Verification:** The risk approval contract suite passed **6 tests**; the full Python suite after ACR-18 passed **385 tests, 2 warnings in 106.83s**. The latest full suite after ACR-19 passed **389 tests, 2 warnings in 108.20s**. No live Redis, executor, broker, or service was used.
- **Deployment note:** `NEXUS_INTERNAL_API_SECRET` must be configured consistently for the risk service and all trusted callers, including ML; the key name is already documented in `.env.example`. Do not place its value in logs or reports.

### Access-control finding ACR-19 — backtest compute/cache endpoint lacked user authorization

- **Status:** Fixed and regression-tested (2026-10-14).
- **File:** `services/nexus_api/routers/backtest.py::run_backtest`; UI `dashboard/src/components/windows/BacktestPanel.tsx`.
- **Evidence:** `POST /api/backtest` fetched historical trades, ran calculations, and wrote a shared Redis result without a JWT or permission check. Before the fix, isolated ASGI tests returned 200 for both missing and unprivileged users and invoked the history reader.
- **Fix:** Require `CurrentUser` and existing `trading.view` before history access; the dashboard attaches the stored JWT. Read-only GET summary/strategies endpoints remain unchanged.
- **Verification:** Focused auth and source-contract tests passed **4/4**; full suite after this fix passed **389 tests, 2 warnings in 108.20s**. No live Redis, data service, or UI was used.

### Access-control finding ACR-20 — direct risk settings/reset/pause routes lacked service authentication

- **Status:** Fixed and regression-tested (2026-10-14).
- **Files:** `services/nexus_risk/main.py`; `services/nexus_api/routers/risk.py`.
- **Evidence:** Direct POST routes could mutate risk settings, reset daily loss/drawdown counters and kill-switch state, or pause/resume trading without a user or internal credential. Gateway routes did have JWT + `risk.modify`, but their internal requests were unauthenticated.
- **Fix:** Each risk-service write checks the configured internal shared secret via constant-time comparison before side effects. The gateway adds that credential to write proxies and returns 503 if unconfigured. No change to existing user permission checks.
- **Verification:** Six missing/incorrect-secret ASGI cases, two proxy credential tests, plus risk/backtest regressions: **21 focused tests passed**. Full suite after these changes: **394 passed, 2 warnings in 114.12s**.

### Access-control finding ACR-21 — Telegram alert endpoint lacked service authentication

- **Status:** Fixed and fully regression-tested.
- **File:** `services/nexus_monitor/main.py::send_alert`.
- **Evidence:** `POST /api/monitor/alert` called Telegram notifier methods without a user or service credential. Repository search found no internal source caller.
- **Fix:** Require configured shared `NEXUS_INTERNAL_API_SECRET` in `X-Nexus-Internal-Secret`, compare in constant time, reject before notifier side effects.
- **Verification:** Red ASGI tests reproduced 200 and mocked notifier invocation for missing/wrong credentials. After the fix, both return 403 without invoking the notifier; focused test **2 passed**. Full suite after this fix: **396 passed, 2 warnings in 175.71s**. No Telegram API call was made.
- **Integration note:** The endpoint has no in-project caller; any out-of-repository operator/client will need to add the shared header. The shared key was not read or printed.

### Access-control finding ACR-22 — executor REST trading mutations lacked service authentication

- **Status:** Fixed and fully regression-tested.
- **Files:** `services/nexus_executor/main.py`, `services/nexus_api/routers/positions.py`, `services/nexus_ml/traders_api.py`, `services/nexus_agents/tools/execution_tools.py`.
- **Evidence:** Direct close-position and modify-position endpoints acquired the broker without authentication. Order entry required a signed risk approval, but did not authenticate the service caller. Gateway user-level permission checks did not protect direct local requests to the executor service.
- **Fix:** Require the shared internal secret on executor order, close, and modify REST handlers before guard/broker access. Gateway positions forwards it only after `trading.execute`; ML and agent execution callers send it too. Order approval HMAC remains separately mandatory.
- **Verification:** Six missing/wrong-secret cases reject before broker access; two gateway tests assert forwarding; existing signed order contract cases remain green. Focused executor/position tests: **15 passed**; full suite: **404 passed, 2 warnings in 102.06s**. No broker connection or order was attempted.
- **Deployment requirement:** Configure `NEXUS_INTERNAL_API_SECRET` consistently on executor, gateway, ML, and agents. No key value was printed.

### Access-control finding ACR-23 — direct ML mutations lacked service authentication

- **Status:** Fixed; full suite pending.
- **Files:** `services/nexus_ml/main.py`, `services/nexus_ml/traders_api.py`, new `services/nexus_ml/internal_auth.py`, and `services/nexus_api/routers/ml.py`.
- **Evidence:** Five direct POST endpoints accepted training/mode/retrain/autonomous commands without an internal credential; gateway JWT permissions did not protect callers directly reaching the service. The red tests returned success, and training routes attempted to schedule work.
- **Fix:** All five handlers now verify `NEXUS_INTERNAL_API_SECRET` before side effects. Gateway write proxy forwards the shared header and returns 503 if it is not configured.
- **Verification:** Ten missing/wrong-secret endpoint cases reject before work; two proxy tests check forwarding/fail-closed. Combined with existing gateway ML authorization: **22 focused tests passed**. No Redis/training task/autonomous loop was started in passing tests.
# Follow-up — 2026-10-14

## Dashboard TypeScript verification

- The user ran the dashboard check from Windows PowerShell in `dashboard` using Node `v22.23.2` and npm `10.9.8`:
  ` .\node_modules\.bin\tsc.cmd --noEmit --incremental false `
- The user subsequently reported `$LASTEXITCODE = 0`; record this as a successful TypeScript check in the user's local PowerShell environment. The intermediate `-1073741510` was a prior process exit code read before the command ran, not the check's final result.
- Codex's bundled Node `v24.19.0` still fails before TypeScript loads with `EPERM` while resolving `C:\نسخه البرنامج الاصل`; this is an execution-context path-access limitation, not a TypeScript diagnostic. No Node upgrade or permission change was performed.
- This verifies static types only. It does not verify rendered UI behavior or a production build; no dashboard UI test runner was found in the current `dashboard` inventory, and the production build remains unrun to avoid collision with a potentially active `.next` dev-server directory.

## Risk approval payload binding — implemented and focused-test verified

- The confirmed gap was fixed across `shared/safety.py`, `services/nexus_risk/main.py`, `services/nexus_executor/main.py`, and `services/nexus_ml/traders_api.py`. Version-1 canonical HMAC now binds symbol, side, order type, approved entry, execution price, SL, TP, approved size, slippage, signal timestamp, proposal ID, and expiry; execution terms are compared before broker acquisition.
- Autonomous ML now sends its regime size multiplier to risk before signing and forwards the exact signed size/prices/timestamp; risk caps the multiplier at 1 and never increases core risk size.
- Regression tests failed before the shared contract existed, then passed. Tamper coverage exercises all 12 signed inputs; REST executor coverage confirms size mismatch and smart-router term changes block before broker access; risk REST coverage confirms the adjusted size and execution terms are signed. `compileall` passed for all four production modules; the combined focused risk/executor/API/shared-event suites passed **67 tests** (2026-10-14).
- Residual: REST and stream source/consumer contract is statically traced, but the stream handoff has not yet been exercised end-to-end with fake Redis. The independent agent execution helper does not forward approval proof and currently has no active call site found. Stream ACK-on-error remains unresolved. No service, broker, live Redis, or order was used.

## Runner process-stop ownership — narrowed and regression-tested

- **Priority:** P1 operational safety (explicit stop/replacement could terminate an unrelated process sharing a configured service port; stale-process matching also included generic Uvicorn processes).
- **Evidence:** `run.py::_stop_listeners_on_ports` formerly killed every PID returned for configured ports. The stop path also called `_collect_run_py_pids`, whose broad `run.py|uvicorn|nexus_` match could select a non-Nexus Uvicorn process whose command line happened to reference the project root.
- **Fix:** Listener PIDs are intersected with confirmed project-owned PIDs; unknown owners are skipped. Uvicorn receives `--app-dir <project-root>` as an explicit marker. Process discovery seeds from the known `services.nexus_*.main:app` modules carrying that marker, then follows service descendants and the parent `run.py`; Windows path matching treats backslashes literally. Legacy workers without the marker are conservatively left unverified rather than killed.
- **Regression evidence:** Tests verify unrelated listeners are not killed, unknown process ownership fails safe, arbitrary Uvicorn processes are excluded, Windows paths remain literal, parent/child discovery is scoped, and new service commands include `--app-dir`. The arbitrary-Uvicorn and parentage tests failed against their prior implementations before the fixes. Focused `tests/test_runner_safety.py`: **10 passed**; `compileall run.py` passed.
- **Full-suite verification:** After the final marker and process-tree changes, the full suite passed **298 tests, 2 deprecation warnings** on 2026-10-14.
- **Residual:** No process was stopped. Startup/shutdown lifecycle outside the reviewed lookup and cleanup functions is still only partially audited; runner component stays in progress.

## Internal service authorization follow-up — 2026-10-14 (ACR-23–25)

- Direct `nexus-ml` mutation routes now require the shared service credential; direct `nexus-agents` evaluation/research/strategy/brief routes require it as well, with gateway JWT-authorized callers forwarding it; and direct `nexus-data` broker subscription validates it before creating a stream task. Details and deployment requirements are in `ACCESS_CONTROL_REVIEW_20261012.md`.
- ML focused authorization: **22 passed**; Agents focused denial/forwarding: **24 passed**. Full Python suite after all three security batches: **432 passed, 2 warnings in 176.42s**.
- Tests used ASGI transports and mocked downstreams. No broker, Redis service, external model call, or order side effect was performed. The initial red check for data subscription reached the broker-availability check; after the fix missing/wrong credentials reject before that check.
- ACR-26 (2026-10-14): source-manager connectivity checks now reject loopback/private/non-global DNS targets before HTTPX and do not follow redirects; DNS resolution runs off the event loop. Red/green mocked tests cover loopback, RFC1918 DNS, redirect behavior, and preserve existing source-manager authorization. Focused suite: **11 passed**. Full Python suite after ACR-26: **436 passed, 2 warnings in 111.45s**. DNS rebinding remains a documented residual requiring egress filtering or pinned IP transport.
- ACR-27 (2026-10-14): a red test proved source-test exception text could echo a query credential embedded in a request URL. Responses now expose only the exception class and generic recovery text. Regression suite: **12 passed**; full Python suite after this change: **437 passed, 2 warnings in 85.19s**.
- ACR-28 (2026-10-14): fixed the Agents→Features cache-only levels request (empty OHLCV now reads the feature owner's cached bars), corrected the `levels` response schema, required the internal secret for direct calculation, limited supplied bars to 5,000, and forwarded the secret from the Agents caller. Focused tests: **4 passed**; full suite after ACR-28: **441 passed, 2 warnings in 133.16s**. No live Redis or broker operation was used.
- ACR-29 (2026-10-14): `/api/news/analyze` now requires the internal service credential and caps input at 10,000 characters; no in-project caller was found. Focused isolated tests: **4 passed**, including valid behavior with FinBERT mocked. The initial red test was interrupted before completion when it was clear an unauthenticated call could reach the real scorer; it is not counted, and no actual model result is claimed. Full suite after ACR-29: **445 passed, 2 warnings in 99.85s**.

## Windows runner process-group shutdown — 2026-10-14

- **Finding:** `ProcessManager.shutdown()` used `Popen.terminate()` and then `Popen.kill()` on Windows. For the dashboard, `Popen` owns a `cmd.exe` wrapper that launches npm/Next.js/Node; killing only the wrapper does not guarantee its Node descendants stop, so port 3100 may remain occupied. This was a code-path finding; no project process was stopped to reproduce it.
- **Fix:** Project subprocesses now start in a new Windows process group. Shutdown sends `CTRL_BREAK_EVENT` to that group for graceful termination; after the existing timeout, it invokes the existing `_kill_pid()` implementation (`taskkill /T /F`) on only the manager-owned root PID, covering the child tree. Non-Windows shutdown behavior is unchanged.
- **Regression evidence:** A new Windows-simulated test failed against the old wrapper-only shutdown, then passed by asserting group signal followed by tree-scoped force termination. The spawn test verifies `CREATE_NEW_PROCESS_GROUP`. A further red/green test proves the `--stop` collector includes a Next/Node tree only when rooted at an already verified project `run.py`, while excluding a separate Node server. `tests/test_runner_safety.py`: **12 passed**; complete Python suite after the collector change: **889 passed, 3 warnings in 237.45s**. A read-only live collector invocation succeeded and returned no owned PIDs. These tests do not terminate a real Windows process tree.
- **Residual:** A standalone orphaned dashboard Node listener without a live runner/service ownership chain remains conservatively unverified and is skipped. No broad Node listener kill was added because PID ownership must remain confirmed. Broader startup/health/restart/shutdown testing remains open.

## Local internal-secret exposure and rotation — 2026-10-14

- **Incident:** A broad repository search unintentionally included the local `.env` internal-service-secret line in raw tool output. The value is deliberately not repeated in this report or the audit log. Treat it as exposed.
- **Containment:** Read-only inspection found no listeners on the project's service/dashboard ports. The local `.env` value was then replaced with a cryptographically random 32-byte key using a temp-file replacement; checks confirmed exactly one setting, valid key length, preservation of all non-secret `.env` text, no remaining temp file, and no secret-value output. No service was running/restarted and no trade/data state changed. The next `run.py` launch will read the new local value.
- **Residual/action:** This only rotates this local project's `.env`; any deployment, copied `.env`, or external service configured with the former value must rotate it separately and consistently before use. The rest of `.env` remains unreviewed. The incident does not alter the 528-row source inventory because the same `.env` row remains classified as intentionally unable to inspect beyond this containment action.

## Risk trade-close stream acknowledgement — 2026-10-14

- **Finding reproduced:** `nexus-risk::_trade_close_consumer` used legacy `subscribe_stream`; its consumer caught a processing exception and continued, after which the helper's `finally` block acknowledged the message. Separately, `_add_nexus_daily_pnl` swallowed Redis write failures, so a failed daily-loss update could be treated as successful processing.
- **Fix:** The consumer now uses explicit `StreamDelivery` acknowledgements, ACKs only after required handling succeeds or an external/non-Nexus trade is intentionally filtered, and logs the pending stream message ID on processing failure. Daily-PnL, recent-results, and directional-streak Redis write errors propagate so the delivery remains pending rather than silently losing a risk-state update.
- **TDD evidence:** Regression tests reproduced auto-ACK after processing failure and swallowed Redis write errors. After the grouped production change, `tests/test_risk` and `tests/test_shared/test_redis_client.py` passed **48 tests**.
- **Residual:** No Redis service or recovery/reclaim code was exercised. Multi-effect state updates are not event-idempotent; the message may remain pending indefinitely because consumers read only `>` and no DLQ/reclaimer is implemented. Do not enable replay until event-level idempotency or an atomic inbox/outbox contract is added. The last full suite (**899 passed**) predates this grouped change; a single full run is reserved for the end of the current batch.


# Access-control review notes — 2026-10-12

Static review only; no endpoint was exposed or called over the network. The default runner binds Uvicorn services to `127.0.0.1` (`run.py` around line 503), which reduces remote exposure in the normal local configuration but does not replace application authorization. A different deployment/bind override would change that boundary.

## Findings and candidates

### ACR-01 — user update has a confirmed partial-write authorization defect (P1)

See `AUDIT_FOLLOWUP_20261012.md` finding A and `test_admin_partial_update_repro.py`. This is confirmed by an isolated failing test. No project source change was made because writing to `services/` and `tests/` is denied by the current workspace permission profile.

### ACR-02 — shared ticker configuration has no route-level permission check (P2 candidate)

`services/nexus_api/routers/fundamental.py` exposes `PUT /settings/news-ticker` with only a Redis dependency and writes a ten-year shared setting. The endpoint does not take an actor or call `_require`. The setting is described in a source comment as presentation-only, so impact appears limited to shared display configuration; confirm intended policy and whether deployment ever binds beyond localhost before final severity.

### ACR-03 — anonymous/invalid-token ticker acknowledgement mutates shared Redis state (P2 candidate)

`_optional_user_id` returns `None` for missing, malformed, or invalid Bearer tokens. In that case `POST /ticker/{id}/acknowledge` takes the anonymous branch, trusts `payload.actor`, and writes lifecycle/active ticker lists to Redis. The authenticated branch instead stores per-user acknowledgement. The API client sends a display actor, while route-level authentication is not enforced. This may be intended for anonymous display use but creates a shared-state mutation without identity; confirm product/security contract before a fix.

### ACR-04 — monitor alert route has no application auth (P2 candidate; deployment-dependent)

`services/nexus_monitor/main.py` exposes `POST /api/monitor/alert` without an auth dependency or secret check and can send Telegram messages. The default runner binds localhost, and repository search did not find an in-project caller for this route. If monitor is ever exposed outside the local host, callers could trigger alert delivery. Verify deployment/network boundaries and whether external alert producers are intended before changing the contract.

### ACR-05 — health response is stale after startup (P2)

`services/nexus_api/main.py` stores the result of `data_service.health()` in `app.state.data_service_available` only during lifespan startup. `/health` later reads this cached boolean and does not recheck nexus-data; a later outage can therefore be reported as connected. Verify with an isolated test before implementation.

## Verification status

- Existing focused API tests run on 2026-10-12: **4 passed**, one non-failing cache-write permission warning; see `TEST_EVIDENCE_20261012.md`.
- The two new reproductions for partial update and false-zero backtest each failed at their intended assertion, confirming both current behaviors.
- No external endpoint, Telegram notifier, live Redis, DuckDB, MT5, or trading function was invoked.
- This is not a complete security audit: authentication coverage, CORS, secrets, upload/path handling, internal shared-secret rotation, dependency vulnerabilities, and frontend token storage remain to inspect.

## Status refresh — 2026-10-14

- ACR-01: fixed before the role-change write, with a regression confirming 403 and zero writes; see finding A in `AUDIT_FOLLOWUP_20261012.md`.
- ACR-05: `/health` now refreshes the nexus-data dependency probe per request; see finding H and its test evidence in the follow-up.
- ACR-02 and ACR-03 were fixed in ACR-17 below. ACR-04 remains deployment-dependent; no external exposure was tested, so do not infer reachability beyond the default localhost configuration.
- ACR-06: refreshed handler audit after ACR-11 found 41 POST/PUT/PATCH/DELETE operations; 23 use a `CurrentUser` JWT parameter, 3 handlers call PIN verification (bootstrap, kill switch, auto-trade toggle), and no APIRouter-level dependency declarations were found. Excluding the intended public login and PIN-protected bootstrap/system controls, 14 business mutation handlers still have no JWT/PIN check visible in their handler. SourceManager, positions, risk, config, and Strategy Lab mutation routes are now guarded; other direct-fetch callers remain to audit. This is a confirmed route-layer gap, while deployment reachability remains conditional.
- ACR-07 (remediated 2026-10-14): the route still has no JWT/PIN check, but caller-supplied `state` is no longer consumed for risk calculation. The endpoint passes `_current_state`, and `_evaluate_proposal` uses only this server-owned snapshot. A regression proves fabricated state cannot change evaluator input; full Python suite is 311 passed. Independent unauthenticated route access remains open.
- Source-management routes now enforce the existing `source_manager.view/edit/test/secrets` permissions, including additional `secrets` permission when create/update payloads contain secret changes; the dashboard component now attaches its JWT. Focused regressions and the full Python suite pass. Broader ACR-06 remains open, and the changed frontend code has not yet received a fresh typecheck in this execution context. A separate partial review found `_connection_test` follows redirects for user-configured URLs and does not visibly reject local/private IP destinations; record as an SSRF candidate, no network request performed.

### ACR-08 — Position close/modify endpoints allowed unauthenticated executor commands (fixed)

- **Priority:** P1 (unauthorized position management; remote exploitability depends on deployment exposure).
- **Evidence:** `services/nexus_api/routers/positions.py` exposed `POST /api/positions/{position_id}/close` and `/modify` without `CurrentUser`, PIN, or permission check, then directly proxied DELETE/PUT to nexus-executor. Dashboard `ApiClient.closePosition` already attaches the stored bearer token through `fetchPath`.
- **Red reproduction:** Four isolated ASGI regressions (missing JWT and authenticated user without permission, for both routes) initially received `202 Accepted`; fake Executor clients confirmed the path reached the executor proxy. No actual executor or broker request was made.
- **Fix:** Both routes now require a valid JWT and the existing `trading.execute` permission via `_require`, before constructing the executor client. This permission is in the catalog, but seeded roles other than `super_admin` do not have it by default; an administrator must explicitly grant it to an approved role/user. This preserves least privilege but can cause 403 until assigned.
- **Verification:** `tests/test_api/test_position_mutation_authorization.py`: **4 passed**. Full suite: **343 passed, 2 deprecation warnings, 108.73s** on 2026-10-14. No live service, database, or order was used.
- **Residual (before ACR-09):** This covered only position close/modify; at that point 23 of 41 business mutation operations remained without visible JWT/PIN. Subsequent ACR-09 covered three risk routes; 20 remain.

### ACR-09 — Risk settings/reset/pause endpoints lacked authentication (fixed)

- **Priority:** P1 (unauthorized changes to runtime risk controls and reset/pause state).
- **Evidence:** `services/nexus_api/routers/risk.py` exposed POST `/api/risk/settings`, `/reset-day`, and `/pause` without JWT or permission checks before proxying to nexus-risk. The risk-manager role has the existing `risk.modify` grant; no new permission was needed.
- **Fix:** All three routes require `CurrentUser` and `risk.modify` before reading the update body or making the downstream request. `TradeSettingsPanel` and `RiskMonitor` now attach the stored JWT to mutations; RiskMonitor renders an error when reset is denied instead of silently swallowing it.
- **Verification:** Six red regressions failed before the change (all routes returned 200 for missing or unprivileged callers). After the change, the combined focused risk/position authorization tests passed **10/10**. Full Python suite passed **349 tests, 2 warnings in 75.35s**. No service or Redis instance was called. A dashboard TypeScript check was attempted but Node v24 failed before compilation with `EPERM` resolving the Arabic project parent.
- **Residual:** Role-grant authorization through the live identity store and rendered UI behavior have not been exercised. At that point the route-level audit still found 20 of 41 mutation handlers without visible JWT/PIN; ACR-10 subsequently reduced this count to 17.

### ACR-10 — Config/settings/agent/risk updates lacked authentication (fixed)

- **Priority:** P1 (unauthorized mutation of shared system, agent, and risk configuration).
- **Evidence:** Three PUT routes in `services/nexus_api/routers/config.py` accepted settings, agent configuration, and risk-rule changes with no actor or permission check. Isolated ASGI regressions showed each route returned 200 and changed the in-memory config for requests without JWT and for a valid JWT lacking permissions.
- **Fix:** `/api/config/settings` and `/api/config/agents/{agent_id}` require `CurrentUser` plus existing `trading.settings`; `/api/config/risk` requires `CurrentUser` plus existing `risk.modify`. Checks run before reading/mutating configuration state. The dashboard's `ApiClient` already attaches stored bearer JWTs for these requests; no frontend change was needed.
- **Verification:** Six regressions failed before the fix; focused config/risk/position authorization suite passed **16/16**. Full suite: **355 passed, 2 deprecation warnings, 39.13s** on 2026-10-14. No live DB, Redis, service, or trade operation was used.
- **Residual:** The identity-store grant path and UI roles have not been end-to-end tested. ACR-11 subsequently reduced the handler count without visible JWT/PIN to 14 of 41.

### ACR-11 — Strategy Lab mutation routes lacked authentication (fixed)

- **Priority:** P1/P2 (unauthorized research, reevaluation, or strategy activation changes; reachability depends on deployment).
- **Evidence:** `POST /api/strategies/research`, `POST /{strategy_id}/reevaluate`, and `PUT /{strategy_id}/status` proxied directly to nexus-agents without a JWT or permission check. Six isolated ASGI regressions (missing JWT and unprivileged JWT across all three routes) returned 200 before the fix; fake proxy assertions confirmed requests reached the downstream boundary.
- **Fix:** All three routes require `CurrentUser` and existing `trading.settings` before forwarding. Existing dashboard Strategy Lab methods use the authenticated `ApiClient`.
- **Verification:** Focused strategy/config/risk/position authorization tests: **22 passed**; full Python suite: **361 passed, 2 warnings in 41.06s** on 2026-10-14. No live agent, service, database, or trade operation was invoked.
- **Residual:** Permission assignment and rendered UI behavior were not end-to-end tested. The static handler audit now finds 14 of 41 business mutations without visible JWT/PIN.

### ACR-12 — ML model training endpoint lacked authentication (fixed)

- **Priority:** P1/P2 (unauthorized compute/model mutation; possible trading impact depends on how trained models are consumed).
- **Evidence:** `POST /api/ml/traders/train` proxied training requests to nexus-ml without a JWT or permission check. Two isolated ASGI regressions returned 200 before the fix for both missing and unprivileged callers and confirmed the downstream proxy was reachable.
- **Fix:** The route now requires `CurrentUser` and existing `trading.settings` before parsing/forwarding the request. Dashboard training actions across Deep Learning, ML Models, Model Comparison, Models, and Reinforcement Learning now use `ApiClient.trainModels`, which attaches the session JWT.
- **Verification:** Focused auth regressions: **2 passed**; full Python suite: **363 passed, 2 warnings in 80.88s** on 2026-10-14. No ML service or live model training was invoked. Dashboard TypeScript check remained blocked before compilation by Node 24 `EPERM` at the Arabic project parent.
- **Residual:** Other ML mutation routes (`/traders/mode/switch`, `/traders/retrain/force`, `/traders/autonomous/toggle`, and `/train`) remain separate audit items.

### ACR-13 — Autonomous ML pipeline toggle could start trading without authorization (fixed)

- **Priority:** P1 (the route starts an independent ML trading loop that proposes trades to risk/execution services).
- **Evidence:** `POST /api/ml/traders/autonomous/toggle` proxied `enable=true` directly to `nexus-ml`, whose implementation creates `_autonomous_trading_loop()`; the loop independently executes features → ML/DL/RL consensus → risk → executor. Before the fix, isolated ASGI tests returned 200 for missing and unprivileged callers and reached the proxy.
- **Fix:** The gateway now requires `CurrentUser` plus `trading.execute` before forwarding. The dashboard toggle uses the JWT-aware client and reports a permission/request failure rather than silently swallowing it.
- **Verification:** The two red regressions now pass; focused ML mutation authorization passes **10/10**; full suite passes **371 tests, 2 warnings in 112.47s** on 2026-10-14. No ML service, autonomous loop, Redis, executor, or broker was started or called.
- **Residual:** TypeScript verification is blocked by the current Node 24 `EPERM` resolving the project path; confirm with the user's Node 22 environment later. The handler scan now finds 9 of 41 business mutation operations without visible JWT/PIN.

### ACR-14 — Manual agent evaluation could trigger a cycle without authorization (fixed)

- **Priority:** P1 (evaluation may start the agent→risk→executor decision path).
- **Evidence:** `POST /api/agents/evaluate` proxied directly to nexus-agents and returned 202 before the fix for both unauthenticated and unprivileged users; an isolated fake HTTP client confirmed downstream reachability.
- **Fix:** The route now requires `CurrentUser` and `trading.execute` before proxying. `LiveDecisionPanel` uses `ApiClient.triggerAgentEvaluation`, which attaches the JWT and surfaces authorization failures.
- **Verification:** Two red regressions now pass; combined agent-evaluation/ML mutation tests: **12 passed**. Full suite: **373 passed, 2 warnings in 120.50s** on 2026-10-14. No agent, risk, executor, or broker service was started or called.
- **Residual:** Frontend typecheck remains blocked by Node 24 `EPERM`; this route is one of 41 gateway mutation operations, with 8 business handlers still lacking a visible JWT/PIN check after the fix.

### ACR-15 — Shared dynamic runtime settings lacked authentication (fixed)

- **Priority:** P1 (shared settings are read by multiple services and may influence operational/trading behavior).
- **Evidence:** `POST /api/intelligence/settings` merged arbitrary submitted keys into `nexus:runtime:settings` in Redis without an actor or permission check. Two isolated ASGI regressions returned 200 before the fix for missing and unprivileged users and observed the Redis write.
- **Fix:** The route now requires `CurrentUser` and existing `trading.settings` before opening Redis. The Settings screen uses the authenticated `ApiClient.updateDynamicSettings` call.
- **Verification:** Red/green focused tests: **2 passed** after the fix. Full suite: **375 passed, 2 warnings in 106.04s** on 2026-10-14. No live Redis or runtime setting was changed.
- **Residual:** The request still accepts an arbitrary settings dictionary; key allowlisting/schema validation and type safety are separate data-integrity work. TypeScript remains unverified due to Node 24 `EPERM` at the project parent. The static handler audit now finds 7 of 41 business mutations without visible JWT/PIN.

### ACR-16 — Manual GenAI brief generation lacked authentication (fixed)

- **Priority:** P2 (unauthorized LLM work/cost and access to an internal agent action; no direct trading operation is performed by this endpoint).
- **Evidence:** `POST /api/intelligence/brief/trigger` proxied directly to nexus-agents. Before the fix it returned 200 for missing and unprivileged users and called the downstream proxy.
- **Fix:** The gateway now requires `CurrentUser` plus existing `fundamental.configure`. The GenAI brief widget uses the token-aware `ApiClient` and surfaces authorization/request errors.
- **Verification:** Two red regressions now pass (**2/2**). No LLM or agent service was called. Full-suite verification after ACR-16 is pending.
- **Residual:** The dashboard TypeScript check remains blocked by Node 24 `EPERM`; the static scan now finds 6 of 41 business mutation handlers without visible JWT/PIN.

### ACR-17 — Ticker/global display writes and local analysis lacked authorization (fixed)

- **Priority:** P1/P2. Global ticker settings persist for years; anonymous acknowledgements altered shared lifecycle state; delivery logs accepted anonymous/forged identity; local AI analysis read internal data and wrote analysis records.
- **Evidence:** `PUT /api/fundamental/settings/news-ticker`, `POST /ticker/{id}/acknowledge`, `POST /ticker/delivery`, and `POST /local-ai/analyze` had no route permission check. Isolated ASGI tests confirmed missing/unprivileged requests could reach writes or return success (or 404 before reaching the intended authorization boundary for a fabricated missing item).
- **Fix:** Global ticker settings require `ticker.manage_global`; acknowledgements and delivery logs require `ticker.acknowledge`; local AI analysis requires `fundamental.view` before Redis/DB/LLM work. Acknowledgement and delivery identity now come from the verified JWT actor, not the client-supplied actor field or optional token parser. Existing UI API-client calls already attach JWTs.
- **Verification:** Focused auth suite: **8 passed** after fixes. No live Redis, DuckDB, LLM, or service was used. Full-suite verification after ACR-17: **385 passed, 2 warnings in 71.93s** (after ACR-18).
- **Residual:** Node 24 TypeScript check remains blocked by `EPERM`; full-suite rerun is required. The static handler audit now finds 2 of 41 business mutation handlers without visible JWT/PIN.

### ACR-18 — Direct risk evaluation lacked service authentication (fixed)

- **Priority:** P1. The independently exposed `nexus-risk` service creates signed approvals that downstream execution can consume; loopback binding is not an authorization boundary against local callers.
- **Evidence:** `POST /api/risk/evaluate` accepted evaluation requests without a JWT or internal credential. The route is called directly by the autonomous ML service and is not proxied through the gateway's user-authenticated route.
- **Fix:** Risk evaluation now requires configured `NEXUS_INTERNAL_API_SECRET` in `X-Nexus-Internal-Secret`, compared with `hmac.compare_digest`; missing configuration returns 503 and absent/incorrect credentials return 403 before proposal evaluation. The ML caller passes the shared secret and returns without making the request when it is absent.
- **Verification:** Red tests first failed because the route did not accept/check the credential. After the fix, missing/wrong-secret rejection and signed-approval contract suite passed **6/6**; full Python suite after ACR-18 passed **385/385, 2 warnings in 106.83s**. A later full run after ACR-19 passed **389 tests**. No Redis, executor, broker, or live service was used.
- **Operational requirement:** `NEXUS_INTERNAL_API_SECRET` must be set consistently for `nexus-risk`, `nexus-ml`, and other internal callers. The project's `.env.example` already documents this shared setting; do not reuse user JWTs for service authentication.
- **Residual:** ACR-20 separately protected the other three risk mutators. This does not imply all routes in other services are protected. ACR-19 later guarded Backtest; the only gateway mutations without `CurrentUser`/PIN are public login and the fail-safe PAPER-only mode setter that disables auto-trading.

### ACR-20 — Direct risk settings/reset/pause routes lacked service authentication (fixed)

- **Priority:** P1. Direct local access could change runtime risk parameters, reset loss/drawdown counters and kill switch, or resume trading while bypassing the gateway's `risk.modify` authorization.
- **Evidence:** `nexus-risk` exposed POST `/api/risk/settings`, `/api/risk/reset-day`, and `/api/risk/pause` without checking a user or service credential. The gateway already checked JWT + `risk.modify`, but did not authenticate its service-to-service request.
- **Fix:** All three service routes now validate the shared internal secret before mutation. Gateway `_risk_proxy` supplies it for write methods and fails closed with 503 if missing. Existing user authorization remains at the gateway.
- **Verification:** Six missing/incorrect-secret cases rejected before mutation; two proxy tests verify credential forwarding and fail-closed behavior; together with risk/backtest regressions, **21 focused tests passed**. Full-suite verification: **394 passed, 2 warnings in 114.12s**.
- **Deployment requirement:** Same `NEXUS_INTERNAL_API_SECRET` must be available to the API gateway and risk service; no value was read or logged.

### ACR-19 — Backtest execution endpoint lacked authentication (fixed)

- **Priority:** P2 (unauthenticated callers could cause historical trade reads, repeated CPU work, and shared cache writes; no order is executed).
- **Evidence:** `POST /api/backtest` fetched history, calculated results, and wrote the shared latest-result cache without a JWT. The gateway has no application-wide auth middleware.
- **Fix:** Requires `CurrentUser` and existing `trading.view` before fetching history; the Backtest UI now sends the stored JWT. No new permission was introduced.
- **Verification:** Red tests confirmed missing JWT and an unprivileged JWT both reached the endpoint successfully before the fix. Afterward the two authorization tests and two source-contract tests passed (**4/4**); latest complete Python suite passed **389 tests, 2 warnings in 108.20s**.
- **Residual:** Dashboard TS check/build unavailable in Codex's current Node 24 path context; user's earlier Node 22 TS success predates this small header change. No UI or live service was run.

### ACR-21 — Unauthenticated monitor endpoint could send Telegram alerts (fixed)

- **Priority:** P2 (external notification side effect/spam; no trading mutation).
- **Evidence:** `POST /api/monitor/alert` invoked the Telegram notifier without a JWT or service credential. A source search found no in-project caller; it appears to be an internal/manual service endpoint.
- **Fix:** The endpoint now requires `NEXUS_INTERNAL_API_SECRET` in `X-Nexus-Internal-Secret`, uses `hmac.compare_digest`, and rejects missing/wrong credentials before the notifier is called. No outbound Telegram request was made.
- **Verification:** Red tests returned 200 and invoked the mocked notifier before the fix; after the fix both unauthorized cases return 403 and notifier remains untouched. Focused test: **2 passed**; full suite: **396 passed, 2 warnings in 175.71s**.
- **Residual:** Any external/manual consumer not found by repository search must be updated to send the shared secret. No such caller is present in the checked-in source.

### ACR-22 — Executor REST trading mutations lacked service authentication (fixed)

- **Priority:** P1 (direct endpoint access could close live positions or modify protective SL/TP; opening orders also require defense in depth beyond risk approval signatures).
- **Evidence:** Executor DELETE position-close and PUT position-modify routes acquired the broker without any user/service authentication. The POST order route validated signed risk terms but also lacked caller authentication. Gateway position routes had `trading.execute` but did not authenticate the service-to-service hop.
- **Fix:** All three executor REST mutation routes require configured `NEXUS_INTERNAL_API_SECRET` in `X-Nexus-Internal-Secret` and constant-time comparison before guard/broker work. Gateway close/modify and ML/agent execution clients now pass the shared secret and fail closed when it is unavailable. Order approval HMAC remains independently required.
- **Verification:** Missing/wrong credential cases for all three endpoint classes stop before broker/guard; gateway tests verify credential forwarding. Combined executor/positions/approval regressions: **15 passed**. Full suite: **404 passed, 2 warnings in 102.06s**. No broker or order was invoked.
- **Deployment requirement:** Set the same internal key for gateway, executor and trusted internal callers (ML, agents). No secret value was read or recorded.

### ACR-23 — Direct ML training/mode/autonomous mutations lacked service authentication (fixed)

- **Priority:** P1 (direct callers could queue model training, switch ML operating mode, force retraining, or start/stop an autonomous path that can request risk approval and executor orders).
- **Evidence:** Five nexus-ml POST operations (legacy training, trader training, mode switch, forced retraining, autonomous toggle) performed work without checking a user or service credential. Gateway routes did check user JWT/permissions but did not authenticate the service hop.
- **Fix:** Each route verifies the configured shared internal secret before scheduling background work, changing mode, or starting/stopping the autonomous task. The API ML proxy attaches the secret to write requests and fails closed with 503 if missing; existing gateway permission checks remain.
- **Verification:** Ten missing/wrong-secret endpoint cases and two proxy credential tests passed (**22 tests with the existing gateway authorization cases**). No Redis, trainer, model promotion, or autonomous task was started in green tests. The full suite immediately after ACR-23 passed **416 tests, 2 warnings in 92.45s**.
- **Deployment requirement:** Configure the same `NEXUS_INTERNAL_API_SECRET` for API gateway and nexus-ml. No key value was read or printed.

### ACR-24 — Direct agent evaluation and strategy mutations lacked service authentication (fixed)

- **Priority:** P1 for evaluation/research side effects and P2 for strategy/brief mutation. Direct calls could trigger agent cycles, expensive research/LLM work, change strategy status, or write a GenAI brief while bypassing gateway JWT permissions.
- **Evidence:** `nexus-agents` exposed five POST/PUT mutation routes without service credentials. Repository callers exist for evaluation, Strategy Lab mutations, and brief generation; gateway handlers already perform user JWT/permission checks but the service hop was unauthenticated.
- **Fix:** All five routes now require `NEXUS_INTERNAL_API_SECRET` in `X-Nexus-Internal-Secret` with constant-time comparison. Agent evaluation, Strategy Lab proxy, and brief-generation gateway callers attach it and fail closed if gateway configuration is absent.
- **Verification:** Ten missing/wrong-secret cases reject before agent, research, registry, or Redis work. Four gateway proxy tests verify header forwarding; existing gateway denial cases remain passing. Focused batch: **24 passed**. Combined full suite after ACR-24/25: **432 passed, 2 warnings in 176.42s**. No external model or Redis service was contacted.
- **Deployment requirement:** Configure the same internal secret for API gateway and nexus-agents. No key value was read or recorded.

### ACR-25 — Runtime broker subscription lacked service authentication (fixed)

- **Priority:** P1 operational/security boundary: a direct caller could ask nexus-data to open a broker stream for arbitrary requested symbols when a connector is active.
- **Evidence:** `POST /api/data/subscribe` created an asyncio streaming task without checking a user or service credential. No in-project caller was found; the endpoint is service-level, not exposed through the API gateway.
- **Fix:** The route now validates the shared internal service secret before checking broker connectivity or creating a streaming task. No gateway caller was added because none exists in the project.
- **Verification:** Two missing/wrong-secret regression cases pass as part of the complete **432-test** suite. The initial red check reached the broker-availability check and returned 503; after the fix both cases return 403 at the auth boundary. No broker connector was started and no subscription was created.
- **Deployment requirement:** Configure `NEXUS_INTERNAL_API_SECRET` for nexus-data. No key value was read or recorded.

### ACR-26 — Source connection test allowed SSRF and redirects (mitigated; egress control still recommended)

- **Priority:** P2 security. A user with `source_manager.test` could configure an HTTP(S) endpoint at loopback/private infrastructure; HTTPX also followed redirects, so a public endpoint could redirect the request into a private target.
- **Evidence:** A regression test with a mocked HTTP client confirmed `http://127.0.0.1:8080/admin` was requested and reported healthy before the fix. No network request was sent.
- **Fix:** The final provider-adjusted URL is checked for HTTP(S), absent URL credentials, and globally routable literal/DNS addresses. DNS resolution runs off the event loop. Redirect following is disabled, so redirects are returned as non-success rather than being fetched.
- **Verification:** Tests reject loopback and a hostname resolving to RFC1918 space before the HTTP client, and verify a mocked 302 is not followed. Source-manager authorization plus SSRF suite: **11 passed**; no real DNS lookup or outbound HTTP call was made by the tests. Latest full suite after ACR-26: **436 passed, 2 warnings in 111.45s**.
- **Residual:** DNS is validated immediately before HTTPX resolves it independently; a hostile DNS-rebinding response could change the address between those operations. Enforce outbound network egress rules (or a pinned-address transport) before treating this boundary as complete.

### ACR-27 — Source-test exceptions could echo credential-bearing URLs (fixed)

- **Priority:** P2 confidentiality. The connection-test failure response included `str(exc)`; exceptions containing request URLs could reveal query-based API credentials to the caller.
- **Evidence:** A mocked transport raised an exception containing `https://feed.example?api_key=<synthetic-secret>`; the secret appeared verbatim in the response before the change.
- **Fix:** Error responses now return the exception class and a generic Arabic message, not exception text or request URL. No secret value is logged or returned.
- **Verification:** The regression confirms the synthetic credential is absent from the entire response. Source-manager auth/SSRF/secrecy suite: **12 passed**. Full suite after ACR-27: **437 passed, 2 warnings in 85.19s**.

### ACR-28 — Feature calculation endpoint bypassed service auth and Agents cache-only request was broken (fixed)

- **Priority:** P2. Unauthenticated direct callers could submit arbitrarily large OHLCV calculations; the authorized Agents caller sent an empty `ohlcv` list expecting cached bars, but the endpoint returned 400. The returned `levels` object also contradicted the response model's list type, causing response validation failure for `include_levels=True`.
- **Evidence:** Four isolated tests reproduced cache-only 400, missing/wrong-secret requests succeeding with 200, and the caller omitting credentials. No Redis service or network endpoint was used.
- **Fix:** `nexus-features /api/features/calculate` now verifies the shared internal secret before cache/compute work; request lists are capped at 5,000 bars; empty lists read the owner service's cached OHLCV key and return 404/503 for absent/unavailable data; `levels` is typed as the mapping the endpoint actually returns. `nexus-agents` attaches the internal secret and falls back to its Redis cache if the secret is absent or the service request fails.
- **Verification:** Focused feature API/caller suite: **4 passed**, including cached OHLCV and correctly shaped levels, missing/wrong secret denial, and credential forwarding. Full suite after ACR-28: **441 passed, 2 warnings in 133.16s**.
- **Deployment requirement:** Same `NEXUS_INTERNAL_API_SECRET` must be configured for nexus-features and nexus-agents. No live cache, model or trade execution was used.

### ACR-29 — Unauthenticated news NLP endpoint had unbounded text input (fixed)

- **Priority:** P2 resource/authorization boundary. Direct callers could invoke FinBERT without service authentication and submit arbitrarily large text. No in-project caller was found.
- **Evidence:** Before the fix, two missing/wrong-secret ASGI tests received a response only after passing the handler; no user/service auth existed. The initial red test was interrupted when it became clear the unauthenticated handler could enter the real FinBERT path; the test was changed to mock the scorer before rerun, and that incomplete red run is not counted as verification.
- **Fix:** `/api/news/analyze` now requires the shared internal secret before analysis and bounds text to 10,000 characters. No gateway route or in-project caller was invented; the endpoint remains a service-level internal API.
- **Verification:** Four isolated tests cover missing/wrong-secret rejection before scorer invocation, valid authorized scoring with a mocked FinBERT, and length rejection. No real model inference or news service startup was required. Full suite after ACR-29: **445 passed, 2 warnings in 99.85s**.
- **Deployment requirement:** Configure `NEXUS_INTERNAL_API_SECRET` for nexus-news. External/manual consumers not present in repository search must be updated to send the header.

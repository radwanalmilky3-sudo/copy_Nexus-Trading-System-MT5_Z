# CHANGELOG — Golden Fundamental / PAPER Hardening

## Foundation / safety

- Added hard PAPER isolation with `PaperExecutor`; PAPER never selects the MT5/IBKR/CCXT execution adapter for opening orders.
- Added deterministic final executor guard: kill switch, explicit auto-trade, canonical blackout, signal freshness, signed central-risk approval.
- Removed direct A9 execution; A9 now prepares a proposal for central risk.
- Added short-lived HMAC central-risk approval using `NEXUS_INTERNAL_API_SECRET`.
- Unified privileged PIN to `NEXUS_ADMIN_PIN`; removed insecure implicit PIN/JWT defaults.
- API gateway resets auto-trade OFF at startup.
- Added guard audit snapshot + best-effort persistence to `fundamental_guard_decisions`.
- Canonical blackout IDs are deterministic for the same event/window.

## No Docker / local AI only

- Removed root compose + Dockerfiles + `--docker` launcher path.
- Native services default to `127.0.0.1:9000..9008`.
- Local AI factory supports only `local`; Ollama/OpenAI-compatible health endpoint added.
- Removed live cloud-provider selector and cloud API key configuration from the target build.
- Replaced cloud-dollar brain budget with local token/resource budget.

## Fundamental intelligence

- Added 24-table DuckDB schema owned by nexus-data.
- Added canonical five-domain models/contracts.
- Added source registry/adapters, source health, provenance, vintage/revision contracts.
- Added Surprise, Data Quality, Macro, Monetary, Cross-Asset, Geopolitical, Flows, Fusion, Gold Impact, Arabic explanation, Replay, Outcome and Training dataset contracts.
- Added dependency/double-count penalty, horizon separation, missing-data coverage penalty.
- Structural flows are context/structural bias only and cannot become an M5 tactical trigger.

## News / calendar / cross-asset

- Removed NewsFeed live mock fallback.
- Added canonical Redis news/calendar/fundamental state bridge.
- Replaced legacy sentinel safety logic with compatibility facade over canonical blackout.
- Fail-closed calendar degradation for new exposure.
- FinBERT is cached/lazy and treated as sentiment feature only; unavailable is not neutral.
- Cross-asset proxy use is explicitly gated; provenance surfaces REAL/PROXY/UNAVAILABLE.

## Dashboard

- Added Arabic RTL Fundamental Workspace with 8 tabs and top safety/quality metrics.
- Added per-domain detail tables, causal chain, evidence, drivers/counter-drivers, source health, learning levels.
- Removed hardcoded live-news demo fallback.

## Tests

- Fixed invalid baseline Python syntax in `tests/test_features/test_indicators.py`.
- Added Golden contract suite covering core semantics and safety.

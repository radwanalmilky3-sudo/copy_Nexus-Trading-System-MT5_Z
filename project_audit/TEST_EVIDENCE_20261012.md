# Focused test evidence — 2026-10-12

## Existing focused tests

After the authorization-order fix, the following focused command was run from the project root:

```text
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_api/test_admin_update_authorization.py tests/test_api/test_admin_data_service.py tests/test_api/test_data_client.py
```

Result: **5 passed**, exit code 0. This includes the new regression test for denied role changes causing no database writes.

After adding the backtest source-outage and valid-empty-history regressions, the full API test directory was run:

```text
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_api
```

Result: **23 passed**, exit code 0, 5.33 seconds. The shared API fixtures use in-memory/fake dependencies; no live Redis, DuckDB, MT5, or broker was contacted.

Focused data/risk/executor tests:

```text
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_data tests/test_risk tests/test_executor
```

Result: **36 passed**, exit code 0, 90.76 seconds. These include temporary DuckDB files under pytest `tmp_path`; the live `data/nexus.duckdb` and WAL were not opened. One existing warning: FastAPI `Query(regex=...)` is deprecated in favor of `pattern`.

Fundamental contract tests:

```text
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_fundamental/test_golden_contracts.py
```

Result: **22 passed**, exit code 0, 190.57 seconds. This includes the asset-registry seed fail-closed regression. No live integration was used.

Dashboard static type check:

```text
.\node_modules\.bin\tsc.cmd --noEmit --incremental false
```

Initial result: **failed**, exit code 1. `src/components/fundamental/NewsTickerControlPanel.tsx:10` had a `FALLBACK` object missing 13 required `NewsTickerSettingsDTO` properties. Exact API-side defaults were available in `services/nexus_api/routers/fundamental.py:75-87`. The fallback was updated to match those API defaults, then the same TypeScript command completed with **exit code 0**. A production build was not run because the live development server may share `.next` output.

Command executed from the project root:

```text
.venv\Scripts\python.exe -m pytest -q tests/test_api/test_admin_data_service.py tests/test_api/test_data_client.py
```

Result: **4 passed**, exit code 0, 11.44 seconds.

One non-failing `PytestCacheWarning` reported that pytest could not write `.pytest_cache\v\cache\nodeids` due to filesystem permission denied. No live service or database was contacted by these tests.

## Isolated regression reproductions

Two temporary tests in the Codex task workspace were executed against the project's Python environment:

1. `work/test_admin_partial_update_repro.py` — failed at the expected assertion: the route returned 403 but recorded an `app_users` write first.
2. `work/test_backtest_empty_source_repro.py` — failed at the expected assertion: the route returned normal zero-trade metrics with no `source_status` despite simulated failures from both Redis and nexus-data.

The admin reproduction was promoted into `tests/test_api/test_admin_update_authorization.py`; after the fix, it passes. The backtest outage reproduction was promoted into `tests/test_api/test_backtest_sources.py`; outage and genuine empty-history cases both pass. The governance seed regression was added to the existing fundamental contract suite. No live service or database was contacted.

## Follow-up regression tests

- `tests/test_runner_safety.py`: red/green check that unreachable Redis does not print username or password embedded in `REDIS_URL`. Final result: **1 passed**; `PYTHONDONTWRITEBYTECODE=1` and pytest cache disabled.
- `tests/test_health_freshness.py` plus `tests/test_api/test_routers.py`: the health regression first failed because a second, failed data-service probe was not reflected; after the route was changed to re-probe, the combined focused tests returned **9 passed**. These used fakes and did not contact a live service or database.

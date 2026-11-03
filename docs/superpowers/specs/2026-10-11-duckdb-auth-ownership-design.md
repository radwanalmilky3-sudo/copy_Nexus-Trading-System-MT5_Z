# DuckDB Authentication Ownership Design

Date: 2026-10-11

## Goal

Restore API authentication and all gateway DuckDB queries on Windows without
opening `data/nexus.duckdb` from more than one process. Preserve the current
paper-trading configuration, existing account records, password hashes, and
DuckDB's single-writer ownership by `nexus-data`.

## Current failure

`nexus-data` holds the DuckDB read-write connection. `nexus-api` separately
opens the same file read-only during startup. DuckDB on Windows rejects this
concurrent read-only/read-write access. `DuckDBClient.query()` then returns an
empty list when uninitialized, causing login and account routes to interpret
the unavailable store as missing users or records.

## Design

`nexus-data` remains the sole process that opens DuckDB. This matches the
documented storage ownership boundary and existing service-to-service HTTP
pattern (`NEXUS_DATA_URL`, `X-Nexus-Internal-Secret`). `nexus-api` continues
using Redis for live state and calls `nexus-data` for durable DuckDB state.

Inventory every DuckDB consumer in `nexus-api`, not only authentication. The
current consumers include account administration, fundamental intelligence,
agent reasoning, and position history. Replace the local connection with a
shared internal data-service client exposing named, allowlisted query
operations with validated parameters. Never accept caller-supplied SQL.
Provide narrowly scoped mutation operations for account and audit changes;
retain the existing allowlisted record persistence for compatible writes.
Perform any read-modify-write that must be atomic inside `nexus-data`.

All internal endpoints verify `NEXUS_INTERNAL_API_SECRET` using constant-time
comparison. They are service-to-service endpoints; the gateway remains the
public API boundary. `nexus-api` calls these endpoints and no longer constructs
a local DuckDB connection. If the internal store is unavailable, routes return
an explicit service-unavailable error rather than treating it as empty data.

## Scope and compatibility

- Keep existing public routes, request and response shapes, JWT behavior,
  password hashing, and authorization rules.
- Preserve the current service startup order and paper mode.
- Do not alter account credentials or database contents as part of the code
  change.
- Do not remove `NEXUS_ADMIN_PIN`.
- Migrate every `nexus-api` DuckDB consumer discovered by the inventory; do
  not leave routes silently dependent on a local connection.

## Verification

- Add tests proving internal reads reject missing/invalid service credentials
  and return expected data only for registered query operations.
- Add tests proving authentication routes use the data-service client and
  report store unavailability distinctly from invalid credentials.
- Cover migrated account, fundamental, agent-reasoning, and position query
  routes for compatible behavior.
- Search for all `nexus-api` DuckDB uses and verify none opens the database.
- Run the focused tests and the repository test suite; where feasible, verify
  concurrent paper-mode startup with both services and a login request.
- Verify the configured trading mode remains `paper` and no real account or
  order action is triggered by verification.

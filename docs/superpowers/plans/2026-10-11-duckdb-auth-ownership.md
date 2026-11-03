# DuckDB Service Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove every direct DuckDB connection from `nexus-api` and route its durable reads through authenticated, allowlisted operations in `nexus-data`.

**Architecture:** `nexus-data` remains the only process opening DuckDB. Add a named-operation query endpoint protected by the existing internal service secret, backed by a registry of parameterized SQL statements; never accept SQL from callers. Add a shared `nexus-api` HTTP client, migrate all gateway DuckDB consumers to it, and distinguish store failures from empty query results.

**Tech Stack:** Python 3.11+, FastAPI, httpx, DuckDB, pytest.

**Spec:** `docs/superpowers/specs/2026-10-11-duckdb-auth-ownership-design.md`

## Global Constraints

- `nexus-data` is the only service that opens `data/nexus.duckdb`.
- Internal API requests require `NEXUS_INTERNAL_API_SECRET` and constant-time credential comparison.
- No endpoint accepts caller-supplied SQL; query names are allowlisted and values are bound parameters.
- Preserve public route shapes, password hashing, JWT behavior, permissions, and startup order.
- Preserve the configured `paper` mode and do not alter account credentials or live trading state.
- Store unavailability must not be translated into an empty result or invalid credentials.

## Review Focus

- Missing or invalid internal secret returns authorization/configuration errors and performs no query.
- Unknown operation names are rejected; query parameters cannot change SQL structure.
- DuckDB operational errors produce an explicit unavailable response, not an empty result.
- User lookup returns password hash only to the gateway's credential verifier; no public response exposes it.
- Variable-length `IN` filters and optional query parameters retain current endpoint semantics.

## File Map

- `services/nexus_data/fundamental_store.py`: fixed named query registry and execution method.
- `services/nexus_data/main.py`: authenticated internal query route.
- `services/nexus_api/data_client.py`: shared typed HTTP client and errors.
- `services/nexus_api/deps.py`, `main.py`: replace local DuckDB singleton and lifecycle with data-service client.
- `services/nexus_api/routers/admin.py`: migrate all account/role/preference/audit reads and preserve writes.
- `services/nexus_api/routers/agents.py`, `positions.py`, `fundamental.py`: migrate remaining persistent reads.
- `tests/test_data/`: query registry and internal route security/error tests.
- `tests/test_api/`: gateway client and migrated route behavior tests.

---

### Task 1: Add allowlisted read operations to nexus-data

**Files:**
- Modify: `services/nexus_data/fundamental_store.py`
- Modify: `services/nexus_data/main.py`
- Test: `tests/test_data/test_internal_queries.py`

**Interfaces:**
- Produce `FundamentalStore.query_named(operation: str, params: dict[str, Any]) -> list[dict[str, Any]]`.
- Register named operations for all queries currently made by `nexus-api`: account count/by username/by ID/list; active roles/permissions; role list/permissions; role existence; notification preferences; audit list; user ticker overrides/acknowledgements; fundamental event impacts; ticker history/existence; asset lineage/outcomes; knowledge claims; local AI history; agent reasoning; position list/by ID.
- Add `POST /api/data/query` accepting `{ "operation": str, "params": object }`; require `X-Nexus-Internal-Secret` before dispatch.

- [ ] **Step 1: Write tests** for each query family, unknown operation rejection, missing/invalid secret, and bound values containing SQL metacharacters.
- [ ] **Step 2: Run focused tests** and confirm expected failures because the operation registry/route does not exist.
- [ ] **Step 3: Implement** a registry of parameterized SQL templates and per-operation parameter validation. Keep dynamic SQL identifiers and clauses fixed in code; generate placeholder counts only for bounded list inputs.
- [ ] **Step 4: Run focused tests** and confirm authorized operations return expected rows while unauthorized/unknown inputs fail without querying.

### Task 2: Add a shared nexus-api data-service client and remove local connection startup

**Files:**
- Create: `services/nexus_api/data_client.py`
- Modify: `services/nexus_api/deps.py`
- Modify: `services/nexus_api/main.py`
- Test: `tests/test_api/test_data_client.py`

**Interfaces:**
- `NexusDataClient.query(operation: str, **params: Any) -> list[dict[str, Any]]` posts to `{NEXUS_DATA_URL}/api/data/query` with the internal secret.
- Raise typed `DataServiceUnavailable` for connection/timeouts/5xx and `DataServiceRejected` for non-retryable 4xx; never return `[]` for transport or server errors.
- Keep endpoint-level response handling explicit: unavailable data service maps to HTTP 503.

- [ ] **Step 1: Write tests** for successful response decoding, internal headers, timeout/connection failure, 5xx, and rejection responses.
- [ ] **Step 2: Run focused tests** and confirm failures before implementation.
- [ ] **Step 3: Implement** the client and replace `DuckDBClient(read_only=True)` dependency/lifespan handling with this client; update health reporting to check the data service's health endpoint without opening DuckDB.
- [ ] **Step 4: Run focused tests** and confirm expected typed error behavior.

### Task 3: Migrate authentication and account administration

**Files:**
- Modify: `services/nexus_api/routers/admin.py`
- Test: `tests/test_api/test_admin_data_service.py`

**Interfaces:**
- Replace SQL helper functions with operation calls for bootstrap count, login lookup, role IDs, permissions, user details, users list, role checks/lists, preferences, and audit queries.
- Keep `_post_data` for compatible allowlisted writes; where an operation requires an atomic read-modify-write, implement a dedicated `nexus-data` operation rather than composing it in the gateway.

- [ ] **Step 1: Write regression tests** proving valid existing credentials can be looked up through the service, missing service does not become 401, and public login response omits password hash.
- [ ] **Step 2: Run tests** and confirm they fail on the existing direct-DuckDB dependency.
- [ ] **Step 3: Migrate** admin routes and permission helpers to named operations while preserving public request/response contracts and authorization checks.
- [ ] **Step 4: Run admin tests** for login, `/auth/me`, roles, preferences, and service-unavailable behavior.

### Task 4: Migrate all remaining gateway DuckDB consumers

**Files:**
- Modify: `services/nexus_api/routers/agents.py`
- Modify: `services/nexus_api/routers/positions.py`
- Modify: `services/nexus_api/routers/fundamental.py`
- Test: `tests/test_api/test_gateway_data_queries.py`

**Interfaces:**
- Use the shared `NexusDataClient` dependency for every durable query.
- Preserve Redis-first behavior and public response shapes where currently present.

- [ ] **Step 1: Write tests** for agent reasoning, position list/detail fallback, event impacts, ticker, asset lineage/outcomes, knowledge claims, and local AI history.
- [ ] **Step 2: Run tests** and confirm missing-client/operation failures.
- [ ] **Step 3: Migrate** all listed handlers and ensure internal-store outages map to 503 instead of false 404/empty results.
- [ ] **Step 4: Search** all `services/nexus_api` sources for `DuckDBClient`, `duckdb.connect`, and direct `.query()` use; only `NexusDataClient` operations may remain.
- [ ] **Step 5: Run focused gateway tests** and confirm compatible results.

### Task 5: Integration verification and documentation

**Files:**
- Modify: `services/nexus_api/requirements.txt` only if a dependency is genuinely missing (httpx is already used; avoid unnecessary dependency changes).
- Modify: `docs/ARCHITECTURE_AFTER.md`, `docs/DB_SCHEMA.md` only if needed to record the final service query boundary.

- [ ] **Step 1: Run the full Python test suite** and record all failures, including pre-existing ones.
- [ ] **Step 2: Run import/compile checks** for both services.
- [ ] **Step 3: Verify** no code path in `nexus-api` opens DuckDB and every internal query operation is registered and authenticated.
- [ ] **Step 4: If the current services can safely be exercised without affecting account/order state, run a local paper-mode startup and login read-only smoke check; otherwise report why integration verification was not run.**
- [ ] **Step 5: Confirm** `.env` trading mode remains `paper`; do not print secrets or invoke trade/order actions.


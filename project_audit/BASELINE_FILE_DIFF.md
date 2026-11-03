# File-by-file comparison to original ZIP

The user-provided ZIP is the **pre-development original**. It was compared to the developed local project without extracting or executing the ZIP.

## Method and scope

- Archive: `Nexus-Trading-System-MT5-main (2).zip`, 1,474,533 bytes.
- Archive SHA-256: `378373D960432F9FBCF3ED5944E35D72E742C25014524AD506DFE04A60F818E1`.
- SHA-256 was computed for each archive file stream and its corresponding local file. This compares file bytes, not file meaning.
- All **338 regular files** in the archive were compared, including binary documentation/assets by hash only. Nothing in the archive was run.
- Excluded from reading/comparison: local `.env`, DuckDB/WAL, `.git`, `.venv`, `node_modules`, and build output. The ZIP listing contained no `.env` or DuckDB/WAL.

## Result

| Status | Count |
|---|---:|
| Byte-identical between original and local | 252 |
| Present in both, but bytes differ | 74 |
| In original, absent from local | 12 |
| **Original files compared** | **338** |

The audit manifest contains 113 local paths absent from the ZIP. This includes local reports, runtime/database artifacts, configuration, and later project files; it is **not** a count of new source files. The secret-bearing `.env` was not read.

### Difference counts by area

| Area | Identical | Modified | Missing locally |
|---|---:|---:|---:|
| Dashboard | 73 | 19 | 1 |
| Services | 118 | 37 | 9 |
| Shared | 15 | 4 | 1 |
| Tests | 25 | 4 | 0 |
| Config | 4 | 2 | 0 |
| Root launch/config/docs and other | 17 | 8 | 1 |
| **Total** | **252** | **74** | **12** |

### Original files absent from the developed local folder

- `dashboard/Dockerfile`
- `docker-compose.yml`
- `services/nexus_agents/Dockerfile`
- `services/nexus_api/Dockerfile`
- `services/nexus_data/Dockerfile`
- `services/nexus_executor/Dockerfile`
- `services/nexus_features/Dockerfile`
- `services/nexus_ml/Dockerfile`
- `services/nexus_monitor/Dockerfile`
- `services/nexus_news/Dockerfile`
- `services/nexus_risk/Dockerfile`
- `shared/fuelix_client.py`

Missing files are not automatically defects: the Docker files may have been intentionally removed in favor of the local Windows runner, and `fuelix_client.py` may have been retired. Audit references and deployment consumers before deciding.

## Interpretation

The 74 changed files are distributed across dashboard (19), services (37), shared (4), tests (4), configuration (2), and root/docs/other (8). A checksum mismatch means content changed; it does not establish whether the change is beneficial, harmful, or intentional. The high-value next step is reviewing those 74 diffs by risk area—especially data ownership/persistence, authentication/authorization, backtest error reporting, and risk-to-executor gating—then testing concrete findings.

This is a full file-level checksum inventory of the supplied ZIP, but not yet a full semantic review of all 338 files. No source files, live database, services, trading state, or credentials were changed.

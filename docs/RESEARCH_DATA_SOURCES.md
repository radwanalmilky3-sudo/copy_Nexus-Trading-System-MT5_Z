# Account research data sources

The Research Lab data source page provides history, live snapshots, and a unified archive. Account identity is resolved by the database owner using the authenticated website user. The isolated MT5 worker checks login and server before and after reads. It never supplies broker credentials or submits orders.

History requests accept at most 366 days and 50,000 candles. The current forming candle is excluded by comparing its open timestamp with MT5's current bar, rather than assuming the terminal clock is UTC. Live reads are explicit snapshots, refreshed using the on-screen button; they are not a continuous streaming subscription.

`research_account_candles` is separate from execution OHLCV. Its primary key is website owner, broker account, broker symbol, timeframe, and source candle timestamp. Repeated downloads and unified merges use conflict-ignore inserts. Unified mode fetches the last 100 source bars and merges completed bars into the account archive. When direct reading fails, the response retains the archive and has no live quote or capture timestamp.

Validation rejects nonfinite or invalid OHLC/volume rows, removes duplicate timestamps, counts unclassified gaps, and returns a SHA256 fingerprint. This is a basic scan, not a broker-calendar quality certificate or proof of full requested-period coverage. Market closures remain unclassified. The UI labels candle and quote times as source MT5 times; historical UTC conversion has not been established. No research archive is automatically approved for training or trading.

The prior global laboratory archive remains under a separately labeled collapsible section; its contents are not asserted to belong to the selected account.

Endpoint: `POST /api/brokers/accounts/{account_id}/research-market`. History and unified writes require `source_manager.edit`; all requests require `source_manager.view`. The internal data route requires the existing internal secret. The sole DuckDB owner performs all archive reads/writes.

## Download/update ledger

`research_account_runs` persists one operation per timeframe and attempt. `group_id` links sequential multi-timeframe downloads. Records include requested period, UTC start/end, received/new/already-stored/rejected counts, source bar range, quality fingerprint, and completion or failure status. Empty reads and archive-only unified fallbacks are partial. Completion denotes operation success, never certified period coverage. The last 200 operations are exposed through `GET /api/brokers/accounts/{account_id}/research-runs`, with website ownership and view permission enforced. Operations predating the ledger are not fabricated.

The UI shows the latest completed history/merge operation for each symbol/timeframe among these 200 records. Live snapshots are also logged but do not count as a persisted history update. A process interrupted while running leaves its record unfinished; the UI labels an unfinished operation older than two minutes as needing verification. Browser timeout does not assert that server work was rolled back; refresh the ledger before retrying.

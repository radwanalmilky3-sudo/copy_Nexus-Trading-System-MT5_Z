# Account session synchronization

The Settings timing tab and Research Validation/Provenance expose the same
"مزامنة جلسات الأصول من MT5" action. It verifies the open terminal login/server
read-only, then imports the server-configured local export into the authenticated
user's selected account. No credentials, trades or account switching are used.

Only saved asset symbols are imported. The export must be connected, match the
account server, be at most 24 hours old and pass the strict session schema. Each
symbol requires a complete error-free quote week with at least one open window.
Missing/error symbols are reported as skipped and are not silently interpreted
as closed. A successful new snapshot replaces the imported list; legacy singular
observations remain stored for compatibility but cannot override that list.

Each observation retains its symbol, server, capture time, observed offset and
weekly windows. Saving is version-checked, recorded in account events and
idempotent for an identical snapshot. Unsaved Settings edits block synchronization.
All unrelated settings and asset preferences are preserved.

Research selects evidence by exact broker symbol. Current weekly closure matches
are diagnostic candidates, not retrospective certification. Historical UTC and
publication-time checks remain separate. Synchronization is explicit from the UI;
this change does not add a background auto-import scheduler or bulk candle fetch.

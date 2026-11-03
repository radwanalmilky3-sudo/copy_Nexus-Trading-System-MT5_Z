# Batch download and account readiness

No main tabs were added. In Data Sources / Historical, enable the saved-account
all-assets option and select the frames and source-clock date range. The same
range is sent sequentially for each unique asset/frame pair, with a maximum of
64 requests per batch. Only that account's saved symbols are included.

Each request uses the existing authenticated, identity-verified research market
endpoint. Its durable account ledger records the shared group_id, symbol, frame,
request interval and outcome. A failed request does not mark other tasks failed
or successful. Empty results are partial. The on-screen batch table shows counts,
added/existing rows, rejections and unclassified gaps separately from fetch state.

Stop cancels browser waiting and remaining requests; an already accepted server
request may still finish. Check the durable ledger before retrying. The summary
table is session-local and resets on a scope change/reload; ledger rows are not
deleted. No background scheduler, atomic all-or-nothing transaction or historical
coverage guarantee is implied.

Validation includes an account-wide readiness summary for the displayed frame
and period, using the server's saved dataset symbols and checks. Unselected
US10Y is not counted. Missing assets block readiness; unknown evidence remains
review-required. Passing recorded checks is not trading/training certification.
The detailed table remains scoped to the currently opened asset.

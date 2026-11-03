CREATE TABLE IF NOT EXISTS market_session_snapshots (
    snapshot_id VARCHAR PRIMARY KEY,
    content_hash VARCHAR NOT NULL UNIQUE,
    payload_json VARCHAR NOT NULL,
    server VARCHAR NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    status VARCHAR NOT NULL,
    reason VARCHAR NOT NULL
);

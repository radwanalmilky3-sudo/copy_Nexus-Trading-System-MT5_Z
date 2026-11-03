CREATE TABLE IF NOT EXISTS broker_profiles (
    owner_user_id VARCHAR NOT NULL,
    profile_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    broker_name VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    PRIMARY KEY(owner_user_id, profile_id)
);
CREATE TABLE IF NOT EXISTS broker_accounts (
    owner_user_id VARCHAR NOT NULL,
    account_id VARCHAR NOT NULL,
    profile_id VARCHAR NOT NULL,
    label VARCHAR NOT NULL,
    server VARCHAR NOT NULL,
    login VARCHAR NOT NULL,
    account_kind VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    PRIMARY KEY(owner_user_id, account_id),
    UNIQUE(owner_user_id, profile_id, server, login),
    FOREIGN KEY(owner_user_id, profile_id) REFERENCES broker_profiles(owner_user_id, profile_id)
);
CREATE TABLE IF NOT EXISTS broker_account_settings (
    owner_user_id VARCHAR NOT NULL,
    account_id VARCHAR NOT NULL,
    version INTEGER NOT NULL,
    settings_json VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    PRIMARY KEY(owner_user_id, account_id),
    FOREIGN KEY(owner_user_id, account_id) REFERENCES broker_accounts(owner_user_id, account_id)
);
CREATE TABLE IF NOT EXISTS broker_account_events (
    event_id VARCHAR PRIMARY KEY,
    owner_user_id VARCHAR NOT NULL,
    profile_id VARCHAR NOT NULL,
    account_id VARCHAR,
    action VARCHAR NOT NULL,
    version INTEGER NOT NULL,
    payload_json VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL
);

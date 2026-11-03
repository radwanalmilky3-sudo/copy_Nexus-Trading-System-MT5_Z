-- Research data foundation: datasets, imports, quality, quarantine, lineage,
-- and research artifacts. JSON-like values are VARCHAR for DuckDB portability.

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id VARCHAR PRIMARY KEY,
    dataset_name VARCHAR NOT NULL UNIQUE,
    description VARCHAR,
    owner VARCHAR,
    source_system VARCHAR,
    storage_uri VARCHAR,
    schema_version INTEGER NOT NULL DEFAULT 1,
    grain VARCHAR,
    sensitivity VARCHAR NOT NULL DEFAULT 'internal',
    status VARCHAR NOT NULL DEFAULT 'active',
    metadata_json VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS import_jobs (
    import_job_id VARCHAR PRIMARY KEY,
    dataset_id VARCHAR NOT NULL REFERENCES datasets(dataset_id),
    source_uri VARCHAR,
    source_checksum VARCHAR,
    requested_by VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'queued',
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    rows_seen BIGINT NOT NULL DEFAULT 0,
    rows_loaded BIGINT NOT NULL DEFAULT 0,
    rows_rejected BIGINT NOT NULL DEFAULT 0,
    error_message VARCHAR,
    parameters_json VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS quality_runs (
    quality_run_id VARCHAR PRIMARY KEY,
    dataset_id VARCHAR NOT NULL REFERENCES datasets(dataset_id),
    import_job_id VARCHAR REFERENCES import_jobs(import_job_id),
    contract_version VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'running',
    score DOUBLE,
    checks_total INTEGER NOT NULL DEFAULT 0,
    checks_passed INTEGER NOT NULL DEFAULT 0,
    checks_failed INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    summary_json VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS quarantine (
    quarantine_id VARCHAR PRIMARY KEY,
    dataset_id VARCHAR NOT NULL REFERENCES datasets(dataset_id),
    import_job_id VARCHAR REFERENCES import_jobs(import_job_id),
    quality_run_id VARCHAR REFERENCES quality_runs(quality_run_id),
    record_key VARCHAR,
    reason_code VARCHAR NOT NULL,
    reason_detail VARCHAR,
    payload_json VARCHAR NOT NULL,
    resolution_status VARCHAR NOT NULL DEFAULT 'open',
    resolved_by VARCHAR,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS lineage (
    lineage_id VARCHAR PRIMARY KEY,
    upstream_dataset_id VARCHAR NOT NULL REFERENCES datasets(dataset_id),
    downstream_dataset_id VARCHAR NOT NULL REFERENCES datasets(dataset_id),
    import_job_id VARCHAR REFERENCES import_jobs(import_job_id),
    transformation_name VARCHAR NOT NULL,
    transformation_version VARCHAR,
    column_mapping_json VARCHAR,
    run_started_at TIMESTAMPTZ,
    run_finished_at TIMESTAMPTZ,
    metadata_json VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (upstream_dataset_id <> downstream_dataset_id)
);
CREATE TABLE IF NOT EXISTS research_artifacts (
    artifact_id VARCHAR PRIMARY KEY,
    dataset_id VARCHAR REFERENCES datasets(dataset_id),
    quality_run_id VARCHAR REFERENCES quality_runs(quality_run_id),
    artifact_type VARCHAR NOT NULL,
    artifact_name VARCHAR NOT NULL,
    artifact_uri VARCHAR,
    content_checksum VARCHAR,
    version VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'draft',
    produced_by VARCHAR,
    parameters_json VARCHAR,
    metadata_json VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_import_jobs_dataset ON import_jobs(dataset_id);
CREATE INDEX IF NOT EXISTS idx_quality_runs_dataset ON quality_runs(dataset_id);
CREATE INDEX IF NOT EXISTS idx_quarantine_dataset_status ON quarantine(dataset_id, resolution_status);
CREATE INDEX IF NOT EXISTS idx_lineage_upstream ON lineage(upstream_dataset_id);
CREATE INDEX IF NOT EXISTS idx_lineage_downstream ON lineage(downstream_dataset_id);
CREATE INDEX IF NOT EXISTS idx_research_artifacts_dataset ON research_artifacts(dataset_id);
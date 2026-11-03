-- Nexus Fundamental Intelligence — canonical DuckDB schema v1
-- Timestamps are UTC. JSON-like payloads use VARCHAR for broad DuckDB compatibility.

CREATE TABLE IF NOT EXISTS fund_sources (
    source_id VARCHAR PRIMARY KEY,
    name_ar VARCHAR NOT NULL,
    name_en VARCHAR NOT NULL,
    organization VARCHAR,
    category VARCHAR NOT NULL,
    transport VARCHAR NOT NULL,
    base_endpoint VARCHAR,
    documentation_url VARCHAR,
    auth_type VARCHAR NOT NULL DEFAULT 'none',
    api_key_env VARCHAR,
    polling_interval_sec INTEGER,
    freshness_limit_sec INTEGER,
    rate_limit_per_min INTEGER,
    provider_priority INTEGER NOT NULL DEFAULT 100,
    fallback_group VARCHAR,
    trust_score DOUBLE NOT NULL DEFAULT 50,
    license_name VARCHAR,
    storage_allowed BOOLEAN NOT NULL DEFAULT TRUE,
    redistribution_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    commercial_use_notes VARCHAR,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    health_state VARCHAR NOT NULL DEFAULT 'unknown',
    last_success_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    last_latency_ms DOUBLE,
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_fetch_runs (
    fetch_run_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL REFERENCES fund_sources(source_id),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    http_status INTEGER,
    success BOOLEAN NOT NULL DEFAULT FALSE,
    records_received INTEGER NOT NULL DEFAULT 0,
    records_accepted INTEGER NOT NULL DEFAULT 0,
    records_rejected INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    latency_ms DOUBLE,
    rate_limit_remaining INTEGER,
    error_code VARCHAR,
    error_message VARCHAR,
    payload_hash VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_health_history (
    health_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL REFERENCES fund_sources(source_id),
    observed_at TIMESTAMPTZ NOT NULL,
    health_state VARCHAR NOT NULL,
    freshness_state VARCHAR NOT NULL,
    latency_ms DOUBLE,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    status_code INTEGER,
    description_ar VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fund_events (
    event_id VARCHAR PRIMARY KEY,
    source_id VARCHAR REFERENCES fund_sources(source_id),
    category VARCHAR NOT NULL,
    subcategory VARCHAR,
    event_type VARCHAR NOT NULL,
    event_code VARCHAR NOT NULL,
    title_en VARCHAR,
    title_ar VARCHAR,
    country VARCHAR,
    currency VARCHAR,
    source_timestamp TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ,
    declared_impact VARCHAR,
    gold_relevance DOUBLE,
    novelty_score DOUBLE,
    freshness_state VARCHAR,
    data_quality_score DOUBLE,
    raw_hash VARCHAR,
    dedup_group_id VARCHAR,
    causal_group_id VARCHAR,
    independence_group VARCHAR,
    source_latency_ms DOUBLE,
    ingestion_latency_ms DOUBLE,
    processing_latency_ms DOUBLE,
    timing_quality VARCHAR,
    authority VARCHAR,
    release_tzid VARCHAR,
    decision_date_local DATE,
    scheduled_status VARCHAR,
    supersedes_event_id VARCHAR,
    cancelled BOOLEAN,
    source_sha256 VARCHAR,
    retrieved_at_utc TIMESTAMPTZ,
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS event_expectations (
    expectation_id VARCHAR PRIMARY KEY,
    event_id VARCHAR NOT NULL REFERENCES fund_events(event_id),
    provider_source_id VARCHAR NOT NULL REFERENCES fund_sources(source_id),
    forecast_value DOUBLE,
    consensus_median DOUBLE,
    consensus_mean DOUBLE,
    consensus_low DOUBLE,
    consensus_high DOUBLE,
    respondent_count INTEGER,
    unit VARCHAR,
    period VARCHAR,
    observed_at TIMESTAMPTZ NOT NULL,
    known_at TIMESTAMPTZ NOT NULL,
    freshness_score DOUBLE,
    quality_score DOUBLE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_vintages (
    vintage_id VARCHAR PRIMARY KEY,
    event_id VARCHAR NOT NULL REFERENCES fund_events(event_id),
    source_id VARCHAR NOT NULL REFERENCES fund_sources(source_id),
    field_name VARCHAR NOT NULL,
    value_numeric DOUBLE,
    value_text VARCHAR,
    valid_for_period VARCHAR,
    source_published_at TIMESTAMPTZ NOT NULL,
    known_at TIMESTAMPTZ NOT NULL,
    revision_number INTEGER NOT NULL DEFAULT 0,
    supersedes_vintage_id VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS macro_releases (
    event_id VARCHAR PRIMARY KEY REFERENCES fund_events(event_id),
    indicator_code VARCHAR NOT NULL,
    indicator_name_en VARCHAR,
    indicator_name_ar VARCHAR,
    frequency VARCHAR,
    unit VARCHAR,
    actual DOUBLE,
    forecast DOUBLE,
    previous DOUBLE,
    first_release_value DOUBLE,
    revised_previous DOUBLE,
    latest_value DOUBLE,
    consensus_low DOUBLE,
    consensus_high DOUBLE,
    surprise_absolute DOUBLE,
    surprise_percent DOUBLE,
    surprise_zscore DOUBLE,
    revision_effect_score DOUBLE,
    historical_importance DOUBLE,
    gold_relevance DOUBLE,
    rate_implication_score DOUBLE,
    usd_implication_score DOUBLE,
    yield_implication_score DOUBLE,
    gold_implication_score DOUBLE,
    release_timestamp TIMESTAMPTZ,
    revision_timestamp TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS central_bank_events (
    event_id VARCHAR PRIMARY KEY REFERENCES fund_events(event_id),
    institution VARCHAR NOT NULL,
    event_kind VARCHAR NOT NULL,
    rate_before DOUBLE,
    rate_expected DOUBLE,
    rate_after DOUBLE,
    rate_surprise_bps DOUBLE,
    tone_score DOUBLE,
    previous_tone_score DOUBLE,
    policy_delta DOUBLE,
    forward_guidance_score DOUBLE,
    dot_plot_shift DOUBLE,
    qe_qt_score DOUBLE,
    balance_sheet_score DOUBLE,
    hawkish_probability DOUBLE,
    dovish_probability DOUBLE,
    speaker VARCHAR,
    statement_hash VARCHAR,
    statement_version VARCHAR,
    gold_implication_score DOUBLE,
    confidence DOUBLE
);

CREATE TABLE IF NOT EXISTS news_articles (
    article_id VARCHAR PRIMARY KEY,
    event_id VARCHAR REFERENCES fund_events(event_id),
    source_id VARCHAR NOT NULL REFERENCES fund_sources(source_id),
    headline VARCHAR NOT NULL,
    summary VARCHAR,
    body_excerpt VARCHAR,
    url VARCHAR,
    language VARCHAR,
    published_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    dedup_hash VARCHAR,
    story_cluster_id VARCHAR,
    original_source_id VARCHAR,
    is_reprint BOOLEAN NOT NULL DEFAULT FALSE,
    provider VARCHAR,
    source_trust DOUBLE,
    freshness_state VARCHAR,
    data_quality_score DOUBLE
);

CREATE TABLE IF NOT EXISTS news_nlp_analysis (
    analysis_id VARCHAR PRIMARY KEY,
    article_id VARCHAR NOT NULL REFERENCES news_articles(article_id),
    finbert_label VARCHAR,
    finbert_score DOUBLE,
    gold_relevance DOUBLE,
    topic VARCHAR,
    event_type VARCHAR,
    economic_relevance DOUBLE,
    geopolitical_severity DOUBLE,
    safe_haven_score DOUBLE,
    novelty_score DOUBLE,
    surprise_language_score DOUBLE,
    model_name VARCHAR,
    model_version VARCHAR,
    analyzed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS market_series_observations (
    observation_id VARCHAR PRIMARY KEY,
    series_code VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL REFERENCES fund_sources(source_id),
    timestamp TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    value DOUBLE NOT NULL,
    unit VARCHAR,
    frequency VARCHAR,
    native_horizon VARCHAR,
    origin VARCHAR NOT NULL,
    freshness_score DOUBLE,
    quality_score DOUBLE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS geopolitical_events (
    event_id VARCHAR PRIMARY KEY REFERENCES fund_events(event_id),
    region VARCHAR,
    countries_json VARCHAR,
    event_class VARCHAR,
    severity_score DOUBLE,
    escalation_score DOUBLE,
    deescalation_score DOUBLE,
    persistence_score DOUBLE,
    global_relevance DOUBLE,
    safe_haven_score DOUBLE,
    energy_risk_score DOUBLE,
    currency_risk_score DOUBLE,
    source_consensus_score DOUBLE,
    independent_source_count INTEGER,
    story_cluster_id VARCHAR,
    gold_implication_score DOUBLE,
    confidence DOUBLE
);

CREATE TABLE IF NOT EXISTS flow_observations (
    observation_id VARCHAR PRIMARY KEY,
    flow_type VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL REFERENCES fund_sources(source_id),
    timestamp TIMESTAMPTZ NOT NULL,
    known_at TIMESTAMPTZ NOT NULL,
    value DOUBLE,
    unit VARCHAR,
    frequency VARCHAR,
    native_horizon VARCHAR,
    flow_direction VARCHAR,
    strength_score DOUBLE,
    crowding_score DOUBLE,
    confirmation_score DOUBLE,
    divergence_score DOUBLE,
    origin VARCHAR NOT NULL,
    freshness_score DOUBLE,
    quality_score DOUBLE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental_factor_scores (
    score_id VARCHAR PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR NOT NULL,
    event_id VARCHAR REFERENCES fund_events(event_id),
    domain VARCHAR NOT NULL,
    native_score DOUBLE NOT NULL,
    gold_impact_score DOUBLE NOT NULL,
    direction VARCHAR NOT NULL,
    strength DOUBLE NOT NULL,
    confidence DOUBLE NOT NULL,
    coverage_score DOUBLE NOT NULL,
    freshness_score DOUBLE NOT NULL,
    data_quality_score DOUBLE NOT NULL,
    reliability_score DOUBLE NOT NULL,
    horizon_class VARCHAR NOT NULL,
    primary_drivers_json VARCHAR,
    counter_drivers_json VARCHAR,
    source_count INTEGER,
    engine_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental_fusion_results (
    fusion_id VARCHAR PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR NOT NULL,
    event_id VARCHAR REFERENCES fund_events(event_id),
    net_score DOUBLE NOT NULL,
    direction VARCHAR NOT NULL,
    strength DOUBLE NOT NULL,
    confidence DOUBLE NOT NULL,
    coverage_score DOUBLE NOT NULL,
    macro_score DOUBLE,
    monetary_score DOUBLE,
    cross_asset_score DOUBLE,
    geopolitical_score DOUBLE,
    flows_score DOUBLE,
    macro_weight DOUBLE,
    monetary_weight DOUBLE,
    cross_asset_weight DOUBLE,
    geopolitical_weight DOUBLE,
    flows_weight DOUBLE,
    agreement_score DOUBLE,
    conflict_score DOUBLE,
    freshness_score DOUBLE,
    data_quality_score DOUBLE,
    dominant_cluster VARCHAR,
    minority_cluster VARCHAR,
    weight_reasons_json VARCHAR,
    fusion_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gold_impact_predictions (
    prediction_id VARCHAR PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR NOT NULL DEFAULT 'XAUUSD',
    event_id VARCHAR REFERENCES fund_events(event_id),
    fusion_id VARCHAR REFERENCES fundamental_fusion_results(fusion_id),
    prediction_stage VARCHAR NOT NULL,
    direction VARCHAR NOT NULL,
    strength DOUBLE NOT NULL,
    confidence DOUBLE NOT NULL,
    confidence_validation VARCHAR NOT NULL,
    coverage_score DOUBLE NOT NULL,
    bullish_probability_5m DOUBLE,
    bearish_probability_5m DOUBLE,
    neutral_probability_5m DOUBLE,
    bullish_probability_15m DOUBLE,
    bearish_probability_15m DOUBLE,
    neutral_probability_15m DOUBLE,
    bullish_probability_60m DOUBLE,
    bearish_probability_60m DOUBLE,
    neutral_probability_60m DOUBLE,
    bullish_probability_4h DOUBLE,
    bearish_probability_4h DOUBLE,
    neutral_probability_4h DOUBLE,
    structural_bias VARCHAR,
    conflict_score DOUBLE,
    freshness_score DOUBLE,
    data_quality_score DOUBLE,
    primary_drivers_json VARCHAR,
    counter_drivers_json VARCHAR,
    confirmations_json VARCHAR,
    contradictions_json VARCHAR,
    weakening_factors_json VARCHAR,
    invalidation_conditions_json VARCHAR,
    transmission_chain_json VARCHAR,
    blackout_active BOOLEAN NOT NULL DEFAULT FALSE,
    blackout_reason VARCHAR,
    model_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prediction_reasoning_steps (
    step_id VARCHAR PRIMARY KEY,
    prediction_id VARCHAR NOT NULL REFERENCES gold_impact_predictions(prediction_id),
    sequence_no INTEGER NOT NULL,
    from_factor VARCHAR,
    to_factor VARCHAR,
    relationship VARCHAR,
    direction VARCHAR,
    strength DOUBLE,
    confidence DOUBLE,
    confirmed BOOLEAN,
    historical_support DOUBLE,
    explanation_ar VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental_explanations (
    explanation_id VARCHAR PRIMARY KEY,
    prediction_id VARCHAR NOT NULL REFERENCES gold_impact_predictions(prediction_id),
    headline_ar VARCHAR,
    what_happened_ar VARCHAR,
    why_it_matters_ar VARCHAR,
    economic_meaning_ar VARCHAR,
    transmission_to_gold_ar VARCHAR,
    gold_effect_ar VARCHAR,
    confirmations_ar VARCHAR,
    contradictions_ar VARCHAR,
    weakening_factors_ar VARCHAR,
    why_confidence_changed_ar VARCHAR,
    invalidation_ar VARCHAR,
    expected_horizon_ar VARCHAR,
    actual_outcome_ar VARCHAR,
    lesson_ar VARCHAR,
    simple_summary_ar VARCHAR,
    advanced_summary_ar VARCHAR,
    explanation_version VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental_blackout_windows (
    blackout_id VARCHAR PRIMARY KEY,
    event_id VARCHAR REFERENCES fund_events(event_id),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    impact VARCHAR NOT NULL,
    affected_assets_json VARCHAR,
    policy_version VARCHAR NOT NULL,
    state VARCHAR NOT NULL,
    reason_code VARCHAR NOT NULL,
    reason_ar VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental_guard_decisions (
    decision_id VARCHAR PRIMARY KEY,
    signal_id VARCHAR,
    prediction_id VARCHAR REFERENCES gold_impact_predictions(prediction_id),
    blackout_id VARCHAR REFERENCES fundamental_blackout_windows(blackout_id),
    requested_action VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    reason_code VARCHAR NOT NULL,
    reason_ar VARCHAR NOT NULL,
    risk_version VARCHAR,
    executor_guard_version VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental_event_outcomes (
    outcome_id VARCHAR PRIMARY KEY,
    prediction_id VARCHAR NOT NULL REFERENCES gold_impact_predictions(prediction_id),
    price_at_event DOUBLE,
    return_1m DOUBLE,
    return_5m DOUBLE,
    return_15m DOUBLE,
    return_60m DOUBLE,
    return_4h DOUBLE,
    mfe_5m DOUBLE,
    mae_5m DOUBLE,
    mfe_60m DOUBLE,
    mae_60m DOUBLE,
    actual_direction_5m VARCHAR,
    actual_direction_15m VARCHAR,
    actual_direction_60m VARCHAR,
    actual_direction_4h VARCHAR,
    correct_5m BOOLEAN,
    correct_15m BOOLEAN,
    correct_60m BOOLEAN,
    correct_4h BOOLEAN,
    dominant_driver VARCHAR,
    unexpected_driver VARCHAR,
    lesson_ar VARCHAR,
    evaluated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS fundamental_training_features (
    feature_row_id VARCHAR PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    event_id VARCHAR REFERENCES fund_events(event_id),
    prediction_id VARCHAR REFERENCES gold_impact_predictions(prediction_id),
    symbol VARCHAR NOT NULL,
    event_type VARCHAR,
    declared_impact VARCHAR,
    actual DOUBLE,
    forecast DOUBLE,
    previous DOUBLE,
    surprise_zscore DOUBLE,
    finbert_score DOUBLE,
    gold_relevance DOUBLE,
    policy_score DOUBLE,
    dxy DOUBLE,
    us2y DOUBLE,
    us10y DOUBLE,
    real_yield DOUBLE,
    vix DOUBLE,
    spx DOUBLE,
    oil DOUBLE,
    geopolitical_score DOUBLE,
    flows_score DOUBLE,
    technical_regime VARCHAR,
    volatility_regime VARCHAR,
    session VARCHAR,
    target_return_5m DOUBLE,
    target_return_15m DOUBLE,
    target_return_60m DOUBLE,
    target_return_4h DOUBLE,
    dataset_split VARCHAR,
    leakage_guard_version VARCHAR NOT NULL,
    feature_version VARCHAR NOT NULL,
    known_at_cutoff TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_evaluations (
    evaluation_id VARCHAR PRIMARY KEY,
    model_name VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL,
    dataset_start TIMESTAMPTZ,
    dataset_end TIMESTAMPTZ,
    sample_count INTEGER,
    brier_score DOUBLE,
    accuracy DOUBLE,
    precision_score DOUBLE,
    recall_score DOUBLE,
    calibration_error DOUBLE,
    notes VARCHAR,
    passed BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS fundamental_audit_log (
    audit_id VARCHAR PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    actor VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    entity_type VARCHAR,
    entity_id VARCHAR,
    before_json VARCHAR,
    after_json VARCHAR,
    correlation_id VARCHAR,
    reason VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);



-- ── Institutional V5/V6 extensions ──────────────────────────────────────────
-- These tables extend (rather than replace) the 24-table Golden contract.
-- JSON-like payloads remain VARCHAR for broad DuckDB compatibility.

CREATE TABLE IF NOT EXISTS economic_indicator_catalog (
    indicator_id VARCHAR PRIMARY KEY,
    indicator_code VARCHAR UNIQUE NOT NULL,
    name_ar VARCHAR NOT NULL,
    name_en VARCHAR NOT NULL,
    domain VARCHAR NOT NULL,
    country VARCHAR,
    currency VARCHAR,
    frequency VARCHAR,
    unit VARCHAR,
    release_schedule VARCHAR,
    source_id VARCHAR REFERENCES fund_sources(source_id),
    importance_default DOUBLE,
    structural_vs_tactical VARCHAR,
    default_horizons_json VARCHAR,
    freshness_limit_seconds BIGINT,
    revision_policy VARCHAR,
    catalog_version VARCHAR NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS economic_indicator_observations (
    observation_id VARCHAR PRIMARY KEY,
    indicator_code VARCHAR NOT NULL REFERENCES economic_indicator_catalog(indicator_code),
    source_id VARCHAR NOT NULL REFERENCES fund_sources(source_id),
    source_series_id VARCHAR,
    period VARCHAR,
    observed_at TIMESTAMPTZ,
    source_timestamp TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    known_at TIMESTAMPTZ NOT NULL,
    value DOUBLE NOT NULL,
    unit VARCHAR,
    origin VARCHAR NOT NULL DEFAULT 'real',
    freshness_score DOUBLE,
    quality_score DOUBLE,
    revision_number INTEGER NOT NULL DEFAULT 0,
    metadata_json VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental_knowledge_sources (
    knowledge_source_id VARCHAR PRIMARY KEY,
    provider_name VARCHAR NOT NULL,
    source_type VARCHAR NOT NULL,
    url_or_doc_ref VARCHAR,
    publisher VARCHAR,
    retrieved_at TIMESTAMPTZ,
    license_notes VARCHAR,
    version VARCHAR,
    trust_tier INTEGER,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fundamental_knowledge_claims (
    claim_id VARCHAR PRIMARY KEY,
    knowledge_source_id VARCHAR REFERENCES fundamental_knowledge_sources(knowledge_source_id),
    domain VARCHAR NOT NULL,
    concept VARCHAR NOT NULL,
    statement_ar VARCHAR NOT NULL,
    statement_en VARCHAR,
    conditions_json VARCHAR,
    counter_conditions_json VARCHAR,
    default_relationship_json VARCHAR,
    asset_scope_json VARCHAR,
    required_confirmations_json VARCHAR,
    exceptions_json VARCHAR,
    horizon_json VARCHAR,
    allowed_for_explanation BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_for_scoring BOOLEAN NOT NULL DEFAULT FALSE,
    review_status VARCHAR NOT NULL DEFAULT 'reviewed_for_explanation',
    version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS asset_registry (
    asset_id VARCHAR PRIMARY KEY,
    symbol VARCHAR UNIQUE NOT NULL,
    asset_class VARCHAR NOT NULL,
    quote_currency VARCHAR,
    country_or_region VARCHAR,
    timezone VARCHAR,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    paper_supported BOOLEAN NOT NULL DEFAULT TRUE,
    live_supported BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS asset_factor_profiles (
    profile_id VARCHAR PRIMARY KEY,
    asset_id VARCHAR NOT NULL REFERENCES asset_registry(asset_id),
    factor_code VARCHAR NOT NULL,
    domain VARCHAR NOT NULL,
    default_sign VARCHAR,
    relationship_type VARCHAR NOT NULL DEFAULT 'conditional',
    conditions_json VARCHAR,
    counter_conditions_json VARCHAR,
    allowed_horizons_json VARCHAR,
    structural_only BOOLEAN NOT NULL DEFAULT FALSE,
    version VARCHAR NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(asset_id, factor_code, version)
);

CREATE TABLE IF NOT EXISTS event_asset_impacts (
    impact_id VARCHAR PRIMARY KEY,
    event_id VARCHAR REFERENCES fund_events(event_id),
    asset_id VARCHAR NOT NULL REFERENCES asset_registry(asset_id),
    prediction_id VARCHAR REFERENCES gold_impact_predictions(prediction_id),
    event_stage VARCHAR,
    relevance_score DOUBLE,
    direction VARCHAR NOT NULL,
    impact_score DOUBLE,
    confidence DOUBLE,
    coverage DOUBLE,
    quality DOUBLE,
    freshness DOUBLE,
    agreement DOUBLE,
    conflict DOUBLE,
    horizon VARCHAR NOT NULL,
    transmission_path_json VARCHAR,
    drivers_json VARCHAR,
    counter_drivers_json VARCHAR,
    confirmations_json VARCHAR,
    contradictions_json VARCHAR,
    invalidation_json VARCHAR,
    source_ids_json VARCHAR,
    claim_ids_json VARCHAR,
    engine_version VARCHAR NOT NULL,
    feature_schema_version VARCHAR NOT NULL,
    known_at TIMESTAMPTZ NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS asset_event_outcomes (
    outcome_id VARCHAR PRIMARY KEY,
    impact_id VARCHAR NOT NULL REFERENCES event_asset_impacts(impact_id),
    asset_id VARCHAR NOT NULL REFERENCES asset_registry(asset_id),
    event_id VARCHAR REFERENCES fund_events(event_id),
    market_timestamp TIMESTAMPTZ NOT NULL,
    price_at_prediction DOUBLE,
    price_5m DOUBLE,
    price_15m DOUBLE,
    price_60m DOUBLE,
    price_4h DOUBLE,
    return_5m DOUBLE,
    return_15m DOUBLE,
    return_60m DOUBLE,
    return_4h DOUBLE,
    mfe DOUBLE,
    mae DOUBLE,
    actual_direction_5m VARCHAR,
    actual_direction_15m VARCHAR,
    actual_direction_60m VARCHAR,
    actual_direction_4h VARCHAR,
    quality VARCHAR,
    captured_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS news_story_clusters (
    story_cluster_id VARCHAR PRIMARY KEY,
    canonical_headline VARCHAR,
    canonical_summary VARCHAR,
    primary_source_id VARCHAR REFERENCES fund_sources(source_id),
    topic VARCHAR,
    event_type VARCHAR,
    entity_keys_json VARCHAR,
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    novelty_score DOUBLE,
    source_count INTEGER NOT NULL DEFAULT 1,
    independent_source_count INTEGER NOT NULL DEFAULT 1,
    status VARCHAR NOT NULL DEFAULT 'active',
    fingerprint VARCHAR UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS news_ticker_items (
    ticker_item_id VARCHAR PRIMARY KEY,
    story_cluster_id VARCHAR REFERENCES news_story_clusters(story_cluster_id),
    event_id VARCHAR REFERENCES fund_events(event_id),
    impact_id VARCHAR REFERENCES event_asset_impacts(impact_id),
    asset_id VARCHAR REFERENCES asset_registry(asset_id),
    topic VARCHAR,
    asset_relevance DOUBLE,
    independent_source_count INTEGER,
    severity VARCHAR NOT NULL,
    headline_ar VARCHAR NOT NULL,
    summary_ar VARCHAR,
    source_label VARCHAR,
    source_id VARCHAR REFERENCES fund_sources(source_id),
    published_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ,
    starts_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    freshness_state VARCHAR,
    actual_value VARCHAR,
    forecast_value VARCHAR,
    previous_value VARCHAR,
    revision_value VARCHAR,
    surprise_value VARCHAR,
    direction VARCHAR,
    confidence DOUBLE,
    data_quality DOUBLE,
    blackout_state VARCHAR,
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by VARCHAR,
    acknowledge_note VARCHAR,
    supersedes_id VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- V6.1 additive migration: CREATE TABLE IF NOT EXISTS does not add columns to an
-- existing table, so keep these statements idempotent.
ALTER TABLE news_ticker_items ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ;
ALTER TABLE news_ticker_items ADD COLUMN IF NOT EXISTS acknowledged_by VARCHAR;
ALTER TABLE news_ticker_items ADD COLUMN IF NOT EXISTS acknowledge_note VARCHAR;

-- Phase 4 (event timing integrity) additive migration: CREATE TABLE IF NOT
-- EXISTS does not add columns to an existing table, so keep these idempotent.
-- All columns are nullable; legacy rows stay NULL and are never rewritten.
-- timing_quality reference values (5): verified_actual_publication,
-- official_event_scheduled_time, official_rule_derived, official_date_only,
-- unverified_external.
-- scheduled_status reference values: scheduled, unscheduled, cancelled,
-- superseded, unknown (unknown is the legacy default for new writers only;
-- legacy rows keep NULL).
-- release_tzid holds an IANA timezone id; decision_date_local is the calendar
-- date of the event in that zone.  Cancellation/supersession is append-only:
-- mark_event_cancelled() inserts a new row instead of rewriting history.
ALTER TABLE fund_events ADD COLUMN IF NOT EXISTS timing_quality VARCHAR;
ALTER TABLE fund_events ADD COLUMN IF NOT EXISTS authority VARCHAR;
ALTER TABLE fund_events ADD COLUMN IF NOT EXISTS release_tzid VARCHAR;
ALTER TABLE fund_events ADD COLUMN IF NOT EXISTS decision_date_local DATE;
ALTER TABLE fund_events ADD COLUMN IF NOT EXISTS scheduled_status VARCHAR;
ALTER TABLE fund_events ADD COLUMN IF NOT EXISTS supersedes_event_id VARCHAR;
ALTER TABLE fund_events ADD COLUMN IF NOT EXISTS cancelled BOOLEAN;
ALTER TABLE fund_events ADD COLUMN IF NOT EXISTS source_sha256 VARCHAR;
ALTER TABLE fund_events ADD COLUMN IF NOT EXISTS retrieved_at_utc TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS alert_delivery_log (
    delivery_id VARCHAR PRIMARY KEY,
    ticker_item_id VARCHAR NOT NULL,
    channel VARCHAR NOT NULL,
    reason VARCHAR,
    language VARCHAR,
    voice_id VARCHAR,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    duration_ms BIGINT,
    repeat_index INTEGER NOT NULL DEFAULT 0,
    acknowledged_before_send BOOLEAN NOT NULL DEFAULT FALSE,
    result VARCHAR,
    error VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS local_ai_analysis_runs (
    analysis_id VARCHAR PRIMARY KEY,
    asset_id VARCHAR REFERENCES asset_registry(asset_id),
    event_id VARCHAR REFERENCES fund_events(event_id),
    impact_id VARCHAR REFERENCES event_asset_impacts(impact_id),
    question VARCHAR,
    input_snapshot_hash VARCHAR NOT NULL,
    structured_input_json VARCHAR NOT NULL,
    claims_used_json VARCHAR,
    source_ids_json VARCHAR,
    model_name VARCHAR NOT NULL,
    model_version VARCHAR,
    prompt_version VARCHAR,
    response_json VARCHAR,
    hallucination_flags_json VARCHAR,
    schema_valid BOOLEAN NOT NULL DEFAULT FALSE,
    latency_ms BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_indicator_catalog_domain ON economic_indicator_catalog (domain, indicator_code);
CREATE INDEX IF NOT EXISTS idx_econ_obs_code_known ON economic_indicator_observations (indicator_code, known_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_claim_domain ON fundamental_knowledge_claims (domain, concept);
CREATE INDEX IF NOT EXISTS idx_asset_impact_asset_time ON event_asset_impacts (asset_id, calculated_at DESC);
CREATE INDEX IF NOT EXISTS idx_asset_impact_event ON event_asset_impacts (event_id, asset_id, horizon);
CREATE INDEX IF NOT EXISTS idx_asset_outcome_impact ON asset_event_outcomes (impact_id);
CREATE INDEX IF NOT EXISTS idx_story_cluster_last_seen ON news_story_clusters (last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_ticker_status_expires ON news_ticker_items (status, expires_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_runs_asset_time ON local_ai_analysis_runs (asset_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_fund_events_time ON fund_events (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_fund_events_code_time ON fund_events (event_code, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_series_code_ts ON market_series_observations (series_code, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_flow_type_ts ON flow_observations (flow_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_factor_symbol_ts ON fundamental_factor_scores (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_fusion_symbol_ts ON fundamental_fusion_results (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_gold_pred_symbol_ts ON gold_impact_predictions (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_outcome_prediction ON fundamental_event_outcomes (prediction_id);
CREATE INDEX IF NOT EXISTS idx_training_symbol_ts ON fundamental_training_features (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_source_health_source_ts ON source_health_history (source_id, observed_at DESC);

-- R4 Users & Alerts Center ----------------------------------------------------
CREATE TABLE IF NOT EXISTS app_users (
    user_id VARCHAR PRIMARY KEY,
    username VARCHAR UNIQUE NOT NULL,
    full_name VARCHAR NOT NULL,
    email VARCHAR,
    password_hash VARCHAR NOT NULL,
    avatar_path VARCHAR,
    language VARCHAR NOT NULL DEFAULT 'ar',
    timezone VARCHAR NOT NULL DEFAULT 'Asia/Aden',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS app_roles (
    role_id VARCHAR PRIMARY KEY,
    name_ar VARCHAR NOT NULL,
    name_en VARCHAR NOT NULL,
    description_ar VARCHAR,
    protected BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_role_permissions (
    role_id VARCHAR NOT NULL,
    permission_code VARCHAR NOT NULL,
    allowed BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (role_id, permission_code)
);

CREATE TABLE IF NOT EXISTS app_user_roles (
    user_id VARCHAR NOT NULL,
    role_id VARCHAR NOT NULL,
    primary_role BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS user_notification_preferences (
    user_id VARCHAR PRIMARY KEY,
    ticker_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    assets_json VARCHAR NOT NULL DEFAULT '["XAUUSD","BTCUSD"]',
    domains_json VARCHAR NOT NULL DEFAULT '["macro","monetary","cross_asset","geopolitical","flows","news"]',
    minimum_severity VARCHAR NOT NULL DEFAULT 'medium',
    critical_ttl_seconds INTEGER NOT NULL DEFAULT 0,
    high_ttl_seconds INTEGER NOT NULL DEFAULT 600,
    medium_ttl_seconds INTEGER NOT NULL DEFAULT 300,
    low_ttl_seconds INTEGER NOT NULL DEFAULT 120,
    hide_after_ack BOOLEAN NOT NULL DEFAULT TRUE,
    show_acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    show_scheduled BOOLEAN NOT NULL DEFAULT TRUE,
    show_breaking BOOLEAN NOT NULL DEFAULT TRUE,
    show_source_outage BOOLEAN NOT NULL DEFAULT TRUE,
    critical_display_mode VARCHAR NOT NULL DEFAULT 'ticker_banner_tts',
    high_display_mode VARCHAR NOT NULL DEFAULT 'ticker_toast_sound',
    medium_display_mode VARCHAR NOT NULL DEFAULT 'ticker_toast',
    low_display_mode VARCHAR NOT NULL DEFAULT 'ticker',
    tts_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    tts_language VARCHAR NOT NULL DEFAULT 'ar',
    tts_voice VARCHAR NOT NULL DEFAULT 'system_arabic',
    tts_volume DOUBLE NOT NULL DEFAULT 0.85,
    tts_rate DOUBLE NOT NULL DEFAULT 1.0,
    tts_levels_json VARCHAR NOT NULL DEFAULT '["critical","high"]',
    tts_repeat_critical BOOLEAN NOT NULL DEFAULT TRUE,
    tts_repeat_interval_seconds INTEGER NOT NULL DEFAULT 25,
    require_ack_critical BOOLEAN NOT NULL DEFAULT TRUE,
    mute_until TIMESTAMPTZ,
    quiet_hours_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    quiet_hours_start VARCHAR NOT NULL DEFAULT '23:00',
    quiet_hours_end VARCHAR NOT NULL DEFAULT '07:00',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_ticker_acknowledgements (
    user_id VARCHAR NOT NULL,
    ticker_item_id VARCHAR NOT NULL,
    acknowledged BOOLEAN NOT NULL DEFAULT TRUE,
    acknowledged_at TIMESTAMPTZ,
    acknowledge_note VARCHAR,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, ticker_item_id)
);

ALTER TABLE alert_delivery_log ADD COLUMN IF NOT EXISTS user_id VARCHAR;

CREATE TABLE IF NOT EXISTS user_audit_log (
    audit_id VARCHAR PRIMARY KEY,
    actor_user_id VARCHAR,
    action VARCHAR NOT NULL,
    target_type VARCHAR,
    target_id VARCHAR,
    details_json VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_app_users_username ON app_users(username);
CREATE INDEX IF NOT EXISTS idx_user_audit_created ON user_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_roles_user ON app_user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_ticker_ack_user ON user_ticker_acknowledgements(user_id, acknowledged_at DESC);

INSERT OR IGNORE INTO app_roles(role_id,name_ar,name_en,description_ar,protected) VALUES
('super_admin','مدير أعلى','Super Administrator','صلاحية كاملة لكل وحدات الإدارة والإعدادات.',TRUE),
('system_admin','مدير النظام','System Administrator','إدارة النظام والمصادر والمستخدمين والتنبيهات.',TRUE),
('trading_admin','مدير التداول','Trading Administrator','إعدادات التداول التشغيلية دون إدارة المستخدمين الحساسة.',TRUE),
('fundamental_analyst','محلل أساسي','Fundamental Analyst','التحليل الأساسي والمصادر والأخبار.',TRUE),
('risk_manager','مدير المخاطر','Risk Manager','عرض وإدارة حدود المخاطر المصرح بها.',TRUE),
('operator','مشغّل','Operator','التشغيل والمراقبة اليومية.',TRUE),
('viewer','مشاهد','Viewer','قراءة فقط.',TRUE);

INSERT OR IGNORE INTO app_role_permissions(role_id,permission_code,allowed) VALUES
('super_admin','*',TRUE),
('system_admin','users.view',TRUE),('system_admin','users.create',TRUE),('system_admin','users.edit',TRUE),('system_admin','users.disable',TRUE),('system_admin','roles.view',TRUE),('system_admin','roles.manage',TRUE),('system_admin','alerts.manage_global',TRUE),('system_admin','ticker.manage_global',TRUE),('system_admin','audit.view',TRUE),('system_admin','source_manager.view',TRUE),('system_admin','source_manager.edit',TRUE),('system_admin','source_manager.test',TRUE),
('trading_admin','ticker.view',TRUE),('trading_admin','ticker.acknowledge',TRUE),('trading_admin','alerts.configure_self',TRUE),('trading_admin','tts.configure_self',TRUE),('trading_admin','trading.settings',TRUE),
('fundamental_analyst','ticker.view',TRUE),('fundamental_analyst','ticker.acknowledge',TRUE),('fundamental_analyst','alerts.configure_self',TRUE),('fundamental_analyst','tts.configure_self',TRUE),('fundamental_analyst','fundamental.view',TRUE),('fundamental_analyst','source_manager.view',TRUE),('fundamental_analyst','source_manager.test',TRUE),
('risk_manager','ticker.view',TRUE),('risk_manager','ticker.acknowledge',TRUE),('risk_manager','alerts.configure_self',TRUE),('risk_manager','risk.view',TRUE),('risk_manager','risk.modify',TRUE),
('operator','ticker.view',TRUE),('operator','ticker.acknowledge',TRUE),('operator','alerts.configure_self',TRUE),('operator','tts.configure_self',TRUE),
('viewer','ticker.view',TRUE),('viewer','fundamental.view',TRUE);

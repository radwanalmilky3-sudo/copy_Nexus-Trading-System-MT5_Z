# DB_SCHEMA — Fundamental Intelligence V1

- Generated: 2026-10-10
- Core contract tables: **24**
- Storage owner: **nexus-data** (single controlled DuckDB writer)
- Live state: Redis; historical/audit truth: DuckDB
- Internal writes require `X-Nexus-Internal-Secret`.

## 01. `fund_sources`

| Field | Type / constraints |
|---|---|
| `source_id` | `VARCHAR PRIMARY KEY` |
| `name_ar` | `VARCHAR NOT NULL` |
| `name_en` | `VARCHAR NOT NULL` |
| `organization` | `VARCHAR` |
| `category` | `VARCHAR NOT NULL` |
| `transport` | `VARCHAR NOT NULL` |
| `base_endpoint` | `VARCHAR` |
| `documentation_url` | `VARCHAR` |
| `auth_type` | `VARCHAR NOT NULL DEFAULT 'none'` |
| `api_key_env` | `VARCHAR` |
| `polling_interval_sec` | `INTEGER` |
| `freshness_limit_sec` | `INTEGER` |
| `rate_limit_per_min` | `INTEGER` |
| `provider_priority` | `INTEGER NOT NULL DEFAULT 100` |
| `fallback_group` | `VARCHAR` |
| `trust_score` | `DOUBLE NOT NULL DEFAULT 50` |
| `license_name` | `VARCHAR` |
| `storage_allowed` | `BOOLEAN NOT NULL DEFAULT TRUE` |
| `redistribution_allowed` | `BOOLEAN NOT NULL DEFAULT FALSE` |
| `commercial_use_notes` | `VARCHAR` |
| `enabled` | `BOOLEAN NOT NULL DEFAULT TRUE` |
| `health_state` | `VARCHAR NOT NULL DEFAULT 'unknown'` |
| `last_success_at` | `TIMESTAMPTZ` |
| `last_failure_at` | `TIMESTAMPTZ` |
| `last_latency_ms` | `DOUBLE` |
| `schema_version` | `INTEGER NOT NULL DEFAULT 1` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 02. `source_fetch_runs`

| Field | Type / constraints |
|---|---|
| `fetch_run_id` | `VARCHAR PRIMARY KEY` |
| `source_id` | `VARCHAR NOT NULL REFERENCES fund_sources(source_id)` |
| `started_at` | `TIMESTAMPTZ NOT NULL` |
| `finished_at` | `TIMESTAMPTZ` |
| `http_status` | `INTEGER` |
| `success` | `BOOLEAN NOT NULL DEFAULT FALSE` |
| `records_received` | `INTEGER NOT NULL DEFAULT 0` |
| `records_accepted` | `INTEGER NOT NULL DEFAULT 0` |
| `records_rejected` | `INTEGER NOT NULL DEFAULT 0` |
| `duplicates` | `INTEGER NOT NULL DEFAULT 0` |
| `latency_ms` | `DOUBLE` |
| `rate_limit_remaining` | `INTEGER` |
| `error_code` | `VARCHAR` |
| `error_message` | `VARCHAR` |
| `payload_hash` | `VARCHAR` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 03. `source_health_history`

| Field | Type / constraints |
|---|---|
| `health_id` | `VARCHAR PRIMARY KEY` |
| `source_id` | `VARCHAR NOT NULL REFERENCES fund_sources(source_id)` |
| `observed_at` | `TIMESTAMPTZ NOT NULL` |
| `health_state` | `VARCHAR NOT NULL` |
| `freshness_state` | `VARCHAR NOT NULL` |
| `latency_ms` | `DOUBLE` |
| `consecutive_failures` | `INTEGER NOT NULL DEFAULT 0` |
| `status_code` | `INTEGER` |
| `description_ar` | `VARCHAR` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 04. `fund_events`

| Field | Type / constraints |
|---|---|
| `event_id` | `VARCHAR PRIMARY KEY` |
| `source_id` | `VARCHAR REFERENCES fund_sources(source_id)` |
| `category` | `VARCHAR NOT NULL` |
| `subcategory` | `VARCHAR` |
| `event_type` | `VARCHAR NOT NULL` |
| `event_code` | `VARCHAR NOT NULL` |
| `title_en` | `VARCHAR` |
| `title_ar` | `VARCHAR` |
| `country` | `VARCHAR` |
| `currency` | `VARCHAR` |
| `source_timestamp` | `TIMESTAMPTZ` |
| `published_at` | `TIMESTAMPTZ` |
| `received_at` | `TIMESTAMPTZ NOT NULL` |
| `processed_at` | `TIMESTAMPTZ` |
| `declared_impact` | `VARCHAR` |
| `gold_relevance` | `DOUBLE` |
| `novelty_score` | `DOUBLE` |
| `freshness_state` | `VARCHAR` |
| `data_quality_score` | `DOUBLE` |
| `raw_hash` | `VARCHAR` |
| `dedup_group_id` | `VARCHAR` |
| `causal_group_id` | `VARCHAR` |
| `independence_group` | `VARCHAR` |
| `source_latency_ms` | `DOUBLE` |
| `ingestion_latency_ms` | `DOUBLE` |
| `processing_latency_ms` | `DOUBLE` |
| `schema_version` | `INTEGER NOT NULL DEFAULT 1` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 05. `event_expectations`

| Field | Type / constraints |
|---|---|
| `expectation_id` | `VARCHAR PRIMARY KEY` |
| `event_id` | `VARCHAR NOT NULL REFERENCES fund_events(event_id)` |
| `provider_source_id` | `VARCHAR NOT NULL REFERENCES fund_sources(source_id)` |
| `forecast_value` | `DOUBLE` |
| `consensus_median` | `DOUBLE` |
| `consensus_mean` | `DOUBLE` |
| `consensus_low` | `DOUBLE` |
| `consensus_high` | `DOUBLE` |
| `respondent_count` | `INTEGER` |
| `unit` | `VARCHAR` |
| `period` | `VARCHAR` |
| `observed_at` | `TIMESTAMPTZ NOT NULL` |
| `known_at` | `TIMESTAMPTZ NOT NULL` |
| `freshness_score` | `DOUBLE` |
| `quality_score` | `DOUBLE` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 06. `data_vintages`

| Field | Type / constraints |
|---|---|
| `vintage_id` | `VARCHAR PRIMARY KEY` |
| `event_id` | `VARCHAR NOT NULL REFERENCES fund_events(event_id)` |
| `source_id` | `VARCHAR NOT NULL REFERENCES fund_sources(source_id)` |
| `field_name` | `VARCHAR NOT NULL` |
| `value_numeric` | `DOUBLE` |
| `value_text` | `VARCHAR` |
| `valid_for_period` | `VARCHAR` |
| `source_published_at` | `TIMESTAMPTZ NOT NULL` |
| `known_at` | `TIMESTAMPTZ NOT NULL` |
| `revision_number` | `INTEGER NOT NULL DEFAULT 0` |
| `supersedes_vintage_id` | `VARCHAR` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 07. `macro_releases`

| Field | Type / constraints |
|---|---|
| `event_id` | `VARCHAR PRIMARY KEY REFERENCES fund_events(event_id)` |
| `indicator_code` | `VARCHAR NOT NULL` |
| `indicator_name_en` | `VARCHAR` |
| `indicator_name_ar` | `VARCHAR` |
| `frequency` | `VARCHAR` |
| `unit` | `VARCHAR` |
| `actual` | `DOUBLE` |
| `forecast` | `DOUBLE` |
| `previous` | `DOUBLE` |
| `first_release_value` | `DOUBLE` |
| `revised_previous` | `DOUBLE` |
| `latest_value` | `DOUBLE` |
| `consensus_low` | `DOUBLE` |
| `consensus_high` | `DOUBLE` |
| `surprise_absolute` | `DOUBLE` |
| `surprise_percent` | `DOUBLE` |
| `surprise_zscore` | `DOUBLE` |
| `revision_effect_score` | `DOUBLE` |
| `historical_importance` | `DOUBLE` |
| `gold_relevance` | `DOUBLE` |
| `rate_implication_score` | `DOUBLE` |
| `usd_implication_score` | `DOUBLE` |
| `yield_implication_score` | `DOUBLE` |
| `gold_implication_score` | `DOUBLE` |
| `release_timestamp` | `TIMESTAMPTZ` |
| `revision_timestamp` | `TIMESTAMPTZ` |

## 08. `central_bank_events`

| Field | Type / constraints |
|---|---|
| `event_id` | `VARCHAR PRIMARY KEY REFERENCES fund_events(event_id)` |
| `institution` | `VARCHAR NOT NULL` |
| `event_kind` | `VARCHAR NOT NULL` |
| `rate_before` | `DOUBLE` |
| `rate_expected` | `DOUBLE` |
| `rate_after` | `DOUBLE` |
| `rate_surprise_bps` | `DOUBLE` |
| `tone_score` | `DOUBLE` |
| `previous_tone_score` | `DOUBLE` |
| `policy_delta` | `DOUBLE` |
| `forward_guidance_score` | `DOUBLE` |
| `dot_plot_shift` | `DOUBLE` |
| `qe_qt_score` | `DOUBLE` |
| `balance_sheet_score` | `DOUBLE` |
| `hawkish_probability` | `DOUBLE` |
| `dovish_probability` | `DOUBLE` |
| `speaker` | `VARCHAR` |
| `statement_hash` | `VARCHAR` |
| `statement_version` | `VARCHAR` |
| `gold_implication_score` | `DOUBLE` |
| `confidence` | `DOUBLE` |

## 09. `news_articles`

| Field | Type / constraints |
|---|---|
| `article_id` | `VARCHAR PRIMARY KEY` |
| `event_id` | `VARCHAR REFERENCES fund_events(event_id)` |
| `source_id` | `VARCHAR NOT NULL REFERENCES fund_sources(source_id)` |
| `headline` | `VARCHAR NOT NULL` |
| `summary` | `VARCHAR` |
| `body_excerpt` | `VARCHAR` |
| `url` | `VARCHAR` |
| `language` | `VARCHAR` |
| `published_at` | `TIMESTAMPTZ` |
| `received_at` | `TIMESTAMPTZ NOT NULL` |
| `dedup_hash` | `VARCHAR` |
| `story_cluster_id` | `VARCHAR` |
| `original_source_id` | `VARCHAR` |
| `is_reprint` | `BOOLEAN NOT NULL DEFAULT FALSE` |
| `provider` | `VARCHAR` |
| `source_trust` | `DOUBLE` |
| `freshness_state` | `VARCHAR` |
| `data_quality_score` | `DOUBLE` |

## 10. `news_nlp_analysis`

| Field | Type / constraints |
|---|---|
| `analysis_id` | `VARCHAR PRIMARY KEY` |
| `article_id` | `VARCHAR NOT NULL REFERENCES news_articles(article_id)` |
| `finbert_label` | `VARCHAR` |
| `finbert_score` | `DOUBLE` |
| `gold_relevance` | `DOUBLE` |
| `topic` | `VARCHAR` |
| `event_type` | `VARCHAR` |
| `economic_relevance` | `DOUBLE` |
| `geopolitical_severity` | `DOUBLE` |
| `safe_haven_score` | `DOUBLE` |
| `novelty_score` | `DOUBLE` |
| `surprise_language_score` | `DOUBLE` |
| `model_name` | `VARCHAR` |
| `model_version` | `VARCHAR` |
| `analyzed_at` | `TIMESTAMPTZ NOT NULL` |

## 11. `market_series_observations`

| Field | Type / constraints |
|---|---|
| `observation_id` | `VARCHAR PRIMARY KEY` |
| `series_code` | `VARCHAR NOT NULL` |
| `source_id` | `VARCHAR NOT NULL REFERENCES fund_sources(source_id)` |
| `timestamp` | `TIMESTAMPTZ NOT NULL` |
| `received_at` | `TIMESTAMPTZ NOT NULL` |
| `value` | `DOUBLE NOT NULL` |
| `unit` | `VARCHAR` |
| `frequency` | `VARCHAR` |
| `native_horizon` | `VARCHAR` |
| `origin` | `VARCHAR NOT NULL` |
| `freshness_score` | `DOUBLE` |
| `quality_score` | `DOUBLE` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 12. `geopolitical_events`

| Field | Type / constraints |
|---|---|
| `event_id` | `VARCHAR PRIMARY KEY REFERENCES fund_events(event_id)` |
| `region` | `VARCHAR` |
| `countries_json` | `VARCHAR` |
| `event_class` | `VARCHAR` |
| `severity_score` | `DOUBLE` |
| `escalation_score` | `DOUBLE` |
| `deescalation_score` | `DOUBLE` |
| `persistence_score` | `DOUBLE` |
| `global_relevance` | `DOUBLE` |
| `safe_haven_score` | `DOUBLE` |
| `energy_risk_score` | `DOUBLE` |
| `currency_risk_score` | `DOUBLE` |
| `source_consensus_score` | `DOUBLE` |
| `independent_source_count` | `INTEGER` |
| `story_cluster_id` | `VARCHAR` |
| `gold_implication_score` | `DOUBLE` |
| `confidence` | `DOUBLE` |

## 13. `flow_observations`

| Field | Type / constraints |
|---|---|
| `observation_id` | `VARCHAR PRIMARY KEY` |
| `flow_type` | `VARCHAR NOT NULL` |
| `source_id` | `VARCHAR NOT NULL REFERENCES fund_sources(source_id)` |
| `timestamp` | `TIMESTAMPTZ NOT NULL` |
| `known_at` | `TIMESTAMPTZ NOT NULL` |
| `value` | `DOUBLE` |
| `unit` | `VARCHAR` |
| `frequency` | `VARCHAR` |
| `native_horizon` | `VARCHAR` |
| `flow_direction` | `VARCHAR` |
| `strength_score` | `DOUBLE` |
| `crowding_score` | `DOUBLE` |
| `confirmation_score` | `DOUBLE` |
| `divergence_score` | `DOUBLE` |
| `origin` | `VARCHAR NOT NULL` |
| `freshness_score` | `DOUBLE` |
| `quality_score` | `DOUBLE` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 14. `fundamental_factor_scores`

| Field | Type / constraints |
|---|---|
| `score_id` | `VARCHAR PRIMARY KEY` |
| `timestamp` | `TIMESTAMPTZ NOT NULL` |
| `symbol` | `VARCHAR NOT NULL` |
| `event_id` | `VARCHAR REFERENCES fund_events(event_id)` |
| `domain` | `VARCHAR NOT NULL` |
| `native_score` | `DOUBLE NOT NULL` |
| `gold_impact_score` | `DOUBLE NOT NULL` |
| `direction` | `VARCHAR NOT NULL` |
| `strength` | `DOUBLE NOT NULL` |
| `confidence` | `DOUBLE NOT NULL` |
| `coverage_score` | `DOUBLE NOT NULL` |
| `freshness_score` | `DOUBLE NOT NULL` |
| `data_quality_score` | `DOUBLE NOT NULL` |
| `reliability_score` | `DOUBLE NOT NULL` |
| `horizon_class` | `VARCHAR NOT NULL` |
| `primary_drivers_json` | `VARCHAR` |
| `counter_drivers_json` | `VARCHAR` |
| `source_count` | `INTEGER` |
| `engine_version` | `VARCHAR NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 15. `fundamental_fusion_results`

| Field | Type / constraints |
|---|---|
| `fusion_id` | `VARCHAR PRIMARY KEY` |
| `timestamp` | `TIMESTAMPTZ NOT NULL` |
| `symbol` | `VARCHAR NOT NULL` |
| `event_id` | `VARCHAR REFERENCES fund_events(event_id)` |
| `net_score` | `DOUBLE NOT NULL` |
| `direction` | `VARCHAR NOT NULL` |
| `strength` | `DOUBLE NOT NULL` |
| `confidence` | `DOUBLE NOT NULL` |
| `coverage_score` | `DOUBLE NOT NULL` |
| `macro_score` | `DOUBLE` |
| `monetary_score` | `DOUBLE` |
| `cross_asset_score` | `DOUBLE` |
| `geopolitical_score` | `DOUBLE` |
| `flows_score` | `DOUBLE` |
| `macro_weight` | `DOUBLE` |
| `monetary_weight` | `DOUBLE` |
| `cross_asset_weight` | `DOUBLE` |
| `geopolitical_weight` | `DOUBLE` |
| `flows_weight` | `DOUBLE` |
| `agreement_score` | `DOUBLE` |
| `conflict_score` | `DOUBLE` |
| `freshness_score` | `DOUBLE` |
| `data_quality_score` | `DOUBLE` |
| `dominant_cluster` | `VARCHAR` |
| `minority_cluster` | `VARCHAR` |
| `weight_reasons_json` | `VARCHAR` |
| `fusion_version` | `VARCHAR NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 16. `gold_impact_predictions`

| Field | Type / constraints |
|---|---|
| `prediction_id` | `VARCHAR PRIMARY KEY` |
| `timestamp` | `TIMESTAMPTZ NOT NULL` |
| `symbol` | `VARCHAR NOT NULL DEFAULT 'XAUUSD'` |
| `event_id` | `VARCHAR REFERENCES fund_events(event_id)` |
| `fusion_id` | `VARCHAR REFERENCES fundamental_fusion_results(fusion_id)` |
| `prediction_stage` | `VARCHAR NOT NULL` |
| `direction` | `VARCHAR NOT NULL` |
| `strength` | `DOUBLE NOT NULL` |
| `confidence` | `DOUBLE NOT NULL` |
| `confidence_validation` | `VARCHAR NOT NULL` |
| `coverage_score` | `DOUBLE NOT NULL` |
| `bullish_probability_5m` | `DOUBLE` |
| `bearish_probability_5m` | `DOUBLE` |
| `neutral_probability_5m` | `DOUBLE` |
| `bullish_probability_15m` | `DOUBLE` |
| `bearish_probability_15m` | `DOUBLE` |
| `neutral_probability_15m` | `DOUBLE` |
| `bullish_probability_60m` | `DOUBLE` |
| `bearish_probability_60m` | `DOUBLE` |
| `neutral_probability_60m` | `DOUBLE` |
| `bullish_probability_4h` | `DOUBLE` |
| `bearish_probability_4h` | `DOUBLE` |
| `neutral_probability_4h` | `DOUBLE` |
| `structural_bias` | `VARCHAR` |
| `conflict_score` | `DOUBLE` |
| `freshness_score` | `DOUBLE` |
| `data_quality_score` | `DOUBLE` |
| `primary_drivers_json` | `VARCHAR` |
| `counter_drivers_json` | `VARCHAR` |
| `confirmations_json` | `VARCHAR` |
| `contradictions_json` | `VARCHAR` |
| `weakening_factors_json` | `VARCHAR` |
| `invalidation_conditions_json` | `VARCHAR` |
| `transmission_chain_json` | `VARCHAR` |
| `blackout_active` | `BOOLEAN NOT NULL DEFAULT FALSE` |
| `blackout_reason` | `VARCHAR` |
| `model_version` | `VARCHAR NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 17. `prediction_reasoning_steps`

| Field | Type / constraints |
|---|---|
| `step_id` | `VARCHAR PRIMARY KEY` |
| `prediction_id` | `VARCHAR NOT NULL REFERENCES gold_impact_predictions(prediction_id)` |
| `sequence_no` | `INTEGER NOT NULL` |
| `from_factor` | `VARCHAR` |
| `to_factor` | `VARCHAR` |
| `relationship` | `VARCHAR` |
| `direction` | `VARCHAR` |
| `strength` | `DOUBLE` |
| `confidence` | `DOUBLE` |
| `confirmed` | `BOOLEAN` |
| `historical_support` | `DOUBLE` |
| `explanation_ar` | `VARCHAR` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 18. `fundamental_explanations`

| Field | Type / constraints |
|---|---|
| `explanation_id` | `VARCHAR PRIMARY KEY` |
| `prediction_id` | `VARCHAR NOT NULL REFERENCES gold_impact_predictions(prediction_id)` |
| `headline_ar` | `VARCHAR` |
| `what_happened_ar` | `VARCHAR` |
| `why_it_matters_ar` | `VARCHAR` |
| `economic_meaning_ar` | `VARCHAR` |
| `transmission_to_gold_ar` | `VARCHAR` |
| `gold_effect_ar` | `VARCHAR` |
| `confirmations_ar` | `VARCHAR` |
| `contradictions_ar` | `VARCHAR` |
| `weakening_factors_ar` | `VARCHAR` |
| `why_confidence_changed_ar` | `VARCHAR` |
| `invalidation_ar` | `VARCHAR` |
| `expected_horizon_ar` | `VARCHAR` |
| `actual_outcome_ar` | `VARCHAR` |
| `lesson_ar` | `VARCHAR` |
| `simple_summary_ar` | `VARCHAR` |
| `advanced_summary_ar` | `VARCHAR` |
| `explanation_version` | `VARCHAR` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 19. `fundamental_blackout_windows`

| Field | Type / constraints |
|---|---|
| `blackout_id` | `VARCHAR PRIMARY KEY` |
| `event_id` | `VARCHAR REFERENCES fund_events(event_id)` |
| `starts_at` | `TIMESTAMPTZ NOT NULL` |
| `ends_at` | `TIMESTAMPTZ NOT NULL` |
| `impact` | `VARCHAR NOT NULL` |
| `affected_assets_json` | `VARCHAR` |
| `policy_version` | `VARCHAR NOT NULL` |
| `state` | `VARCHAR NOT NULL` |
| `reason_code` | `VARCHAR NOT NULL` |
| `reason_ar` | `VARCHAR NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 20. `fundamental_guard_decisions`

| Field | Type / constraints |
|---|---|
| `decision_id` | `VARCHAR PRIMARY KEY` |
| `signal_id` | `VARCHAR` |
| `prediction_id` | `VARCHAR REFERENCES gold_impact_predictions(prediction_id)` |
| `blackout_id` | `VARCHAR REFERENCES fundamental_blackout_windows(blackout_id)` |
| `requested_action` | `VARCHAR NOT NULL` |
| `decision` | `VARCHAR NOT NULL` |
| `reason_code` | `VARCHAR NOT NULL` |
| `reason_ar` | `VARCHAR NOT NULL` |
| `risk_version` | `VARCHAR` |
| `executor_guard_version` | `VARCHAR` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 21. `fundamental_event_outcomes`

| Field | Type / constraints |
|---|---|
| `outcome_id` | `VARCHAR PRIMARY KEY` |
| `prediction_id` | `VARCHAR NOT NULL REFERENCES gold_impact_predictions(prediction_id)` |
| `price_at_event` | `DOUBLE` |
| `return_1m` | `DOUBLE` |
| `return_5m` | `DOUBLE` |
| `return_15m` | `DOUBLE` |
| `return_60m` | `DOUBLE` |
| `return_4h` | `DOUBLE` |
| `mfe_5m` | `DOUBLE` |
| `mae_5m` | `DOUBLE` |
| `mfe_60m` | `DOUBLE` |
| `mae_60m` | `DOUBLE` |
| `actual_direction_5m` | `VARCHAR` |
| `actual_direction_15m` | `VARCHAR` |
| `actual_direction_60m` | `VARCHAR` |
| `actual_direction_4h` | `VARCHAR` |
| `correct_5m` | `BOOLEAN` |
| `correct_15m` | `BOOLEAN` |
| `correct_60m` | `BOOLEAN` |
| `correct_4h` | `BOOLEAN` |
| `dominant_driver` | `VARCHAR` |
| `unexpected_driver` | `VARCHAR` |
| `lesson_ar` | `VARCHAR` |
| `evaluated_at` | `TIMESTAMPTZ NOT NULL` |

## 22. `fundamental_training_features`

| Field | Type / constraints |
|---|---|
| `feature_row_id` | `VARCHAR PRIMARY KEY` |
| `timestamp` | `TIMESTAMPTZ NOT NULL` |
| `event_id` | `VARCHAR REFERENCES fund_events(event_id)` |
| `prediction_id` | `VARCHAR REFERENCES gold_impact_predictions(prediction_id)` |
| `symbol` | `VARCHAR NOT NULL` |
| `event_type` | `VARCHAR` |
| `declared_impact` | `VARCHAR` |
| `actual` | `DOUBLE` |
| `forecast` | `DOUBLE` |
| `previous` | `DOUBLE` |
| `surprise_zscore` | `DOUBLE` |
| `finbert_score` | `DOUBLE` |
| `gold_relevance` | `DOUBLE` |
| `policy_score` | `DOUBLE` |
| `dxy` | `DOUBLE` |
| `us2y` | `DOUBLE` |
| `us10y` | `DOUBLE` |
| `real_yield` | `DOUBLE` |
| `vix` | `DOUBLE` |
| `spx` | `DOUBLE` |
| `oil` | `DOUBLE` |
| `geopolitical_score` | `DOUBLE` |
| `flows_score` | `DOUBLE` |
| `technical_regime` | `VARCHAR` |
| `volatility_regime` | `VARCHAR` |
| `session` | `VARCHAR` |
| `target_return_5m` | `DOUBLE` |
| `target_return_15m` | `DOUBLE` |
| `target_return_60m` | `DOUBLE` |
| `target_return_4h` | `DOUBLE` |
| `dataset_split` | `VARCHAR` |
| `leakage_guard_version` | `VARCHAR NOT NULL` |
| `feature_version` | `VARCHAR NOT NULL` |
| `known_at_cutoff` | `TIMESTAMPTZ NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

## 23. `model_evaluations`

| Field | Type / constraints |
|---|---|
| `evaluation_id` | `VARCHAR PRIMARY KEY` |
| `model_name` | `VARCHAR NOT NULL` |
| `model_version` | `VARCHAR NOT NULL` |
| `evaluated_at` | `TIMESTAMPTZ NOT NULL` |
| `dataset_start` | `TIMESTAMPTZ` |
| `dataset_end` | `TIMESTAMPTZ` |
| `sample_count` | `INTEGER` |
| `brier_score` | `DOUBLE` |
| `accuracy` | `DOUBLE` |
| `precision_score` | `DOUBLE` |
| `recall_score` | `DOUBLE` |
| `calibration_error` | `DOUBLE` |
| `notes` | `VARCHAR` |
| `passed` | `BOOLEAN NOT NULL DEFAULT FALSE` |

## 24. `fundamental_audit_log`

| Field | Type / constraints |
|---|---|
| `audit_id` | `VARCHAR PRIMARY KEY` |
| `timestamp` | `TIMESTAMPTZ NOT NULL` |
| `actor` | `VARCHAR NOT NULL` |
| `action` | `VARCHAR NOT NULL` |
| `entity_type` | `VARCHAR` |
| `entity_id` | `VARCHAR` |
| `before_json` | `VARCHAR` |
| `after_json` | `VARCHAR` |
| `correlation_id` | `VARCHAR` |
| `reason` | `VARCHAR` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP` |

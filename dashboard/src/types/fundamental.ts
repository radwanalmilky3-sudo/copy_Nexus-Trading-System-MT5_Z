export type GoldDirection = 'bullish' | 'bearish' | 'neutral' | 'conflicted';
// unknown ≠ neutral: the backend reports unknown/None for missing/undecidable
// state and the UI must render it as such, never as a fabricated neutral.
export type GoldDirectionOrUnknown = GoldDirection | 'unknown';
export type FundamentalDomain = 'macro' | 'monetary' | 'cross_asset' | 'geopolitical' | 'flows';

export interface EvidenceDTO {
  source_id: string;
  source_name: string;
  source_name_ar?: string;
  source_url?: string | null;
  source_timestamp?: string | null;
  origin: 'real' | 'proxy' | 'synthetic' | 'test' | 'unknown';
  freshness: string;
  trust_score: number;
  quality_score: number;
  causal_group_id?: string | null;
  independence_group?: string | null;
}

export interface DriverDTO {
  code: string;
  label_ar: string;
  label_en: string;
  native_score: number;
  gold_impact_score: number;
  strength: number;
  confidence: number;
  explanation_ar: string;
  horizon_class: string;
  sources: EvidenceDTO[];
}

export interface DomainDTO {
  state?: string;
  reason_ar?: string | null;
  score_state?: ScoreState;
  evidence_state?: EvidenceState;
  evidence_count?: number;
  domain_state?: DomainState;
  domain: FundamentalDomain;
  domain_ar?: string;
  // Null score = unknown/missing, never a fabricated 0.
  native_score: number | null;
  gold_impact_score: number | null;
  direction: GoldDirectionOrUnknown;
  strength: number | null;
  confidence: number | null;
  coverage_score: number | null;
  freshness_score: number | null;
  data_quality_score: number | null;
  reliability_score: number | null;
  horizon_class: string;
  primary_drivers: DriverDTO[];
  counter_drivers: DriverDTO[];
  details?: Array<Record<string, unknown>>;
  generated_at?: string;
  metadata?: Record<string, unknown>;
}

export interface BlackoutDTO {
  active?: boolean;
  state: string;
  reason_code?: string;
  reason?: string;
  reason_ar?: string;
  starts_at?: string;
  ends_at?: string;
  checked_at?: string;
}

export interface ArabicExplanationDTO {
  headline_ar: string;
  what_happened_ar: string;
  why_it_matters_ar: string;
  transmission_to_gold_ar: string;
  gold_effect_ar: string;
  confirmations_ar: string[];
  contradictions_ar: string[];
  weakening_factors_ar: string[];
  invalidation_ar: string[];
  confidence_reason_ar: string;
  horizon_ar: string;
  actual_outcome_ar: string;
  lesson_ar: string;
  simple_summary_ar: string;
  advanced_summary_ar: string;
}

export interface HorizonDTO {
  bullish: number;
  bearish: number;
  neutral: number;
}

export interface GoldOverviewDTO {
  state: string;
  message_ar?: string | null;
  reason_ar?: string | null;
  result_origin?: string;
  symbol?: string | null;
  direction?: GoldDirectionOrUnknown;
  direction_ar?: string;
  // Null score = unknown/missing, never a fabricated 0.
  strength?: number | null;
  confidence?: number | null;
  confidence_validation?: string | null;
  coverage_score?: number | null;
  data_quality_score?: number | null;
  freshness_score?: number | null;
  conflict_score?: number | null;
  prediction_stage?: string | null;
  market_confirmation?: string | null;
  blackout: BlackoutDTO;
  horizons?: {
    m5?: HorizonDTO;
    m15?: HorizonDTO;
    h1?: HorizonDTO;
    h4?: HorizonDTO;
    structural_bias?: GoldDirectionOrUnknown;
  };
  domains: DomainDTO[];
  weights?: Array<Record<string, unknown>>;
  primary_drivers?: DriverDTO[];
  counter_drivers?: DriverDTO[];
  transmission_chain_ar?: string[];
  explanation?: ArabicExplanationDTO | null;
  generated_at?: string;
}

export interface SourceHealthDTO {
  source_id: string;
  name_ar: string;
  name_en: string;
  health: string;
  health_description_ar: string;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  latency_ms?: number | null;
  freshness: string;
  origin: string;
  records_received: number;
  records_accepted: number;
}

export interface FundamentalNewsSourceTruthDTO {
  source_id: string;
  name_ar?: string | null;
  configuration_status?: string | null;
  configuration_reason_ar?: string | null;
  connectivity?: string | null;
  last_success_at?: string | null;
  health_description_ar?: string | null;
}

export interface FundamentalNewsDTO {
  news: Array<Record<string, unknown>>;
  calendar: Array<Record<string, unknown>>;
  ticker?: NewsTickerItemDTO[];
  blackout: BlackoutDTO;
  // Additive truth envelope (Task 5): never fabricate ready for missing state.
  state?: string | null;
  item_count?: number | null;
  last_update_at?: string | null;
  first_available_at?: string | null;
  freshness?: { stale?: boolean | null; age_sec?: number | null; limit_sec?: number | null } | null;
  reason_ar?: string | null;
  sources?: FundamentalNewsSourceTruthDTO[] | null;
}

export type DomainState = 'DATA_AVAILABLE' | 'DEGRADED' | 'UNAVAILABLE';
export type ScoreState = 'AVAILABLE' | 'UNAVAILABLE';
export type EvidenceState = 'PRESENT' | 'NONE';

export interface AssetImpactDTO {
  impact_id: string;
  event_id?: string | null;
  asset_id: string;
  prediction_id?: string | null;
  event_stage?: string | null;
  relevance_score: number;
  direction: GoldDirection | 'unknown';
  impact_score: number;
  confidence: number;
  coverage: number;
  quality: number;
  freshness: number;
  agreement: number;
  conflict: number;
  horizon: '5m' | '15m' | '60m' | '4h' | string;
  transmission_path_json?: string[];
  drivers_json?: Array<Record<string, unknown>>;
  counter_drivers_json?: Array<Record<string, unknown>>;
  confirmations_json?: string[];
  contradictions_json?: string[];
  invalidation_json?: string[];
  source_ids_json?: string[];
  claim_ids_json?: string[];
  known_at?: string;
  calculated_at?: string;
  engine_version?: string;
  feature_schema_version?: string;
}

export interface AssetImpactSnapshotDTO {
  state: 'ready' | 'degraded' | 'unavailable' | string;
  asset_id: string;
  event_id?: string | null;
  event_type?: string | null;
  impacts: AssetImpactDTO[];
  generated_at?: string;
}

export type TickerSeverity = 'low' | 'medium' | 'high' | 'critical';
export interface NewsTickerItemDTO {
  ticker_item_id: string;
  story_cluster_id?: string | null;
  event_id?: string | null;
  impact_id?: string | null;
  asset_id?: string | null;
  topic?: string | null;
  asset_relevance?: number | null;
  independent_source_count?: number | null;
  severity: TickerSeverity;
  headline_ar: string;
  summary_ar?: string | null;
  source_label?: string | null;
  source_id?: string | null;
  published_at?: string | null;
  received_at?: string | null;
  starts_at?: string | null;
  expires_at?: string | null;
  status: string;
  freshness_state?: string;
  actual_value?: string | number | null;
  forecast_value?: string | number | null;
  previous_value?: string | number | null;
  revision_value?: string | number | null;
  surprise_value?: string | number | null;
  direction?: GoldDirection | 'unknown' | string;
  confidence?: number | null;
  data_quality?: number | null;
  blackout_state?: string | null;
  acknowledged?: boolean;
  acknowledged_at?: string | null;
  acknowledged_by?: string | null;
  acknowledge_note?: string | null;
  supersedes_id?: string | null;
}

export interface NewsTickerSettingsDTO {
  enabled: boolean;
  position: 'top' | 'bottom';
  speed: 'slow' | 'medium' | 'fast';
  pause_on_hover: boolean;
  assets: string[];
  domains: string[];
  minimum_severity: TickerSeverity;
  minimum_relevance: number;
  minimum_source_quality: number;
  max_news_age_minutes: number;
  audio_enabled: boolean;
  critical_audio: boolean;
  high_audio: boolean;
  medium_audio: boolean;
  language: 'ar' | 'en';
  voice: string;
  volume: number;
  speech_rate: number;
  critical_repeat_count: number;
  high_repeat_count: number;
  repeat_delay_seconds: number;
  cooldown_seconds: number;
  quiet_hours_enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  blackout_alerts: boolean;
  source_outage_alerts: boolean;
  verified_source_only_voice: boolean;
  two_source_geopolitical_voice: boolean;
  critical_ttl_seconds: number;
  high_ttl_seconds: number;
  medium_ttl_seconds: number;
  low_ttl_seconds: number;
  hide_after_ack: boolean;
  show_acknowledged: boolean;
  show_scheduled: boolean;
  show_breaking: boolean;
  critical_display_mode: string;
  high_display_mode: string;
  medium_display_mode: string;
  low_display_mode: string;
  require_ack_critical: boolean;
  mute_until?: string | null;
}

export interface LocalAIAnswerDTO {
  summary_ar: string;
  what_happened: string;
  why_it_matters: string;
  transmission: string[];
  asset_comparison: string[];
  confirmations: string[];
  contradictions: string[];
  missing_evidence: string[];
  sources: string[];
  claims_used: string[];
  data_quality_note: string;
  uncertainty_note: string;
}

export interface LocalAIAnalysisDTO {
  state: 'ready' | 'rejected' | 'unavailable' | string;
  answer?: LocalAIAnswerDTO | null;
  model_name?: string;
  model_version?: string;
  endpoint?: string;
  available_models?: string[];
  evidence_ids?: { sources: string[]; claims: string[] };
  latency_ms?: number | null;
  schema_valid?: boolean;
  hallucination_flags?: string[];
  reason?: string;
  error?: string;
  analysis_id?: string;
  asset?: string;
}


export interface AssetOutcomeDTO {
  outcome_id: string;
  impact_id: string;
  asset_id: string;
  event_id?: string | null;
  market_timestamp: string;
  price_at_prediction?: number | null;
  price_5m?: number | null;
  price_15m?: number | null;
  price_60m?: number | null;
  price_4h?: number | null;
  return_5m?: number | null;
  return_15m?: number | null;
  return_60m?: number | null;
  return_4h?: number | null;
  actual_direction_5m?: string | null;
  actual_direction_15m?: string | null;
  actual_direction_60m?: string | null;
  actual_direction_4h?: string | null;
  quality?: string | null;
  captured_at: string;
}

export interface DataLineageEdgeDTO { from: string; to: string; relation: string; }
export interface AssetLineageDTO {
  state: string;
  asset_id: string;
  event_id?: string | null;
  impact?: AssetImpactDTO | null;
  sources: Array<Record<string, unknown>>;
  edges: DataLineageEdgeDTO[];
  outcomes: AssetOutcomeDTO[];
  collector?: Record<string, unknown>;
  lineage_version?: string;
}

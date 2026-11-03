export type ResearchTabId =
  | 'data-import'
  | 'cleaning'
  | 'validation'
  | 'provenance'
  | 'strategies'
  | 'backtests'
  | 'news'
  | 'artifacts';

export type ResearchViewState = 'loading' | 'error' | 'empty' | 'readonly' | 'unavailable' | 'degraded';

export interface ResearchResult<T> {
  readonly rows: ReadonlyArray<T>;
  readonly status: 'available' | 'unavailable' | 'degraded';
  readonly source: string;
  readonly total: number;
}

export interface ResearchSource<T> {
  readonly key: ResearchTabId;
  readonly label: string;
  readonly readOnly: true;
  readonly load: (signal?: AbortSignal) => Promise<ResearchResult<T>>;
}

export interface ResearchRow { readonly id: string; }

export interface DataImportRow extends ResearchRow { readonly source: string; readonly format: string; readonly rows: number; readonly receivedAt: string; readonly status: 'queued' | 'ready' | 'blocked' | 'stored'; readonly qualityStatus?: 'passed' | 'warning' | 'failed' | 'stale' | 'not_checked'; readonly qualityDetails?: string; readonly qualityCheckedAt?: string; readonly qualityVerifiedAt?: string; readonly qualityExpiresAt?: string; readonly historicalSlice?: boolean; readonly calendarState?: string; readonly calendarDetails?: string; readonly calendarCapturedAt?: string; readonly calendarImportedAt?: string; readonly calendarExpiresAt?: string; readonly calendarSnapshotId?: string; readonly gapDetails?: string; }
export interface CleaningRow extends ResearchRow { readonly dataset: string; readonly rule: string; readonly affectedRows: number; readonly status: 'pending' | 'review' | 'complete'; readonly updatedAt: string; }
export interface ValidationRow extends ResearchRow { readonly dataset: string; readonly check: string; readonly result: 'pass' | 'warning' | 'fail'; readonly score: string; readonly checkedAt: string; readonly details?: string; readonly fingerprint?: string; }
export interface ProvenanceRow extends ResearchRow { readonly asset: string; readonly origin: string; readonly owner: string; readonly capturedAt: string; readonly hash: string; }
export interface StrategyRow extends ResearchRow { readonly name: string; readonly family: string; readonly timeframe: string; readonly status: 'draft' | 'candidate' | 'validated' | 'archived'; readonly confidence: string; readonly lastRun: string; }
export interface BacktestRow extends ResearchRow { readonly strategy: string; readonly period: string; readonly market: string; readonly returnPct: string; readonly maxDrawdownPct: string; readonly status: 'queued' | 'running' | 'complete' | 'blocked'; }
export interface NewsRow extends ResearchRow { readonly headline: string; readonly source: string; readonly sentiment: 'positive' | 'neutral' | 'negative' | 'unknown'; readonly publishedAt: string; readonly relevance: string; }
export interface ArtifactRow extends ResearchRow { readonly name: string; readonly kind: string; readonly version: string; readonly size: string; readonly state: 'available' | 'pending' | 'restricted'; }

export type ResearchRowByTab = {
  'data-import': DataImportRow;
  cleaning: CleaningRow;
  validation: ValidationRow;
  provenance: ProvenanceRow;
  strategies: StrategyRow;
  backtests: BacktestRow;
  news: NewsRow;
  artifacts: ArtifactRow;
};

export interface ResearchTabDefinition<T extends ResearchRow> {
  readonly id: ResearchTabId;
  readonly arabicLabel: string;
  readonly englishLabel: string;
  readonly description: string;
  readonly icon: string;
  readonly source: ResearchSource<T>;
}

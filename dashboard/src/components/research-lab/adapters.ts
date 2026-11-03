import type { ArtifactRow, BacktestRow, CleaningRow, DataImportRow, NewsRow, ProvenanceRow, ResearchResult, ResearchSource, StrategyRow, ValidationRow } from './types';
import { withRequestTimeout } from '@/lib/request-timeout';

const API = process.env.NEXT_PUBLIC_API_URL || '';

type ResearchItem = Record<string, unknown>;
type ResearchCollection = { items?: unknown; status?: unknown; source?: unknown; total?: unknown };

const unavailable = <T,>(): Promise<ResearchResult<T>> => Promise.resolve({ rows: [], status: 'unavailable', source: 'not-connected', total: 0 });

const asItem = (value: unknown): ResearchItem => (typeof value === 'object' && value !== null ? value : {}) as ResearchItem;
const text = (value: unknown, fallback = '—'): string => value == null || value === '' ? fallback : String(value);
const number = (value: unknown, fallback = 0): number => typeof value === 'number' && Number.isFinite(value) ? value : fallback;
const date = (...values: unknown[]): string => text(values.find((value) => value != null && value !== ''));

const authHeaders = (): HeadersInit => {
  if (typeof window === 'undefined') return {};
  const token = window.localStorage.getItem('nexus-token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

async function loadRows<T>(resource: string, project: (item: ResearchItem) => T, signal?: AbortSignal): Promise<ResearchResult<T>> {
  return withRequestTimeout(async (requestSignal) => {
    const response = await fetch(`${API}/api/research-lab/${resource}`, { cache: 'no-store', headers: authHeaders(), signal: requestSignal });
    if (response.status === 401 && typeof window !== 'undefined') {
      window.localStorage.removeItem('nexus-token');
      window.location.href = '/login';
    }
    if (!response.ok) throw new Error(`Research Lab request failed: HTTP ${response.status}`);
    const payload = await response.json() as ResearchCollection;
    if (!payload || !Array.isArray(payload.items) || !['available', 'unavailable', 'degraded'].includes(String(payload.status))) {
      throw new Error('Invalid Research Lab response');
    }
    return { rows: payload.items.map(asItem).map(project), status: payload.status as ResearchResult<T>['status'],
      source: text(payload.source), total: number(payload.total, payload.items.length) };
  }, signal);
}

const importStatus = (value: unknown): DataImportRow['status'] => {
  const status = String(value ?? '').toLowerCase();
  if (['complete', 'completed', 'ready', 'success', 'succeeded'].includes(status)) return 'ready';
  if (['blocked', 'failed', 'error'].includes(status)) return 'blocked';
  return 'queued';
};

const validationResult = (item: ResearchItem): ValidationRow['result'] => {
  const checks = item.checks && typeof item.checks === 'object' ? Object.values(item.checks as Record<string, unknown>) : [];
  const status = String(item.status ?? '').toLowerCase();
  if (['failed', 'error'].includes(status) || (Array.isArray(item.issues) && item.issues.length > 0)) return 'fail';
  if (status === 'warning') return 'warning';
  if (checks.some((value) => value === false)) return 'fail';
  const score = typeof item.score === 'number' ? item.score : null;
  if (checks.length === 0 && score === null) return 'warning';
  if (score !== null && score < 0.5) return 'fail';
  if (['warning', 'pending', 'running', 'unknown'].includes(status) || (score !== null && score < 0.8)) return 'warning';
  return 'pass';
};

const strategyStatus = (value: unknown): StrategyRow['status'] => {
  const status = String(value ?? '').toLowerCase();
  if (['validated', 'approved', 'active'].includes(status)) return 'validated';
  if (['candidate', 'review', 'testing'].includes(status)) return 'candidate';
  if (['archived', 'retired'].includes(status)) return 'archived';
  return 'draft';
};

const backtestStatus = (value: unknown): BacktestRow['status'] => {
  const status = String(value ?? '').toLowerCase();
  if (['complete', 'completed', 'success', 'succeeded'].includes(status)) return 'complete';
  if (['blocked', 'failed', 'error'].includes(status)) return 'blocked';
  if (['running', 'in_progress'].includes(status)) return 'running';
  return 'queued';
};

const newsSentiment = (value: unknown): NewsRow['sentiment'] => {
  if (value == null || value === '') return 'unknown';
  const score = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(score)) return 'unknown';
  if (Math.abs(score) <= 0.2) return 'neutral';
  return score > 0 ? 'positive' : 'negative';
};

const artifactState = (value: unknown): ArtifactRow['state'] => {
  const status = String(value ?? '').toLowerCase();
  if (['available', 'ready', 'complete', 'completed'].includes(status)) return 'available';
  if (['restricted', 'blocked', 'denied'].includes(status)) return 'restricted';
  return 'pending';
};

const loadDataImports = (signal?: AbortSignal) => loadRows<DataImportRow>('datasets', (item) => {
  const quality = asItem(item.quality_summary);
  const calendar = asItem(quality.calendar_summary);
  const gaps = asItem(quality.gap_summary);
  const checked = ['passed', 'warning', 'failed'].includes(String(quality.status));
  return ({
  id: text(item.dataset_id),
  source: `${text(item.name)} · ${text(item.source)}`,
  format: 'OHLCV',
  rows: number(item.row_count),
  receivedAt: date(item.updated_at),
  status: item.status === 'stored' ? 'stored' : importStatus(item.status),
  qualityStatus: !checked ? 'not_checked' : quality.snapshot_current !== true || quality.expired === true ? 'stale' : quality.status as 'passed' | 'warning' | 'failed',
  qualityDetails: [...(Array.isArray(quality.issues) ? quality.issues : []), ...(Array.isArray(quality.warnings) ? quality.warnings : [])].map(String).join(' · '),
  qualityCheckedAt: date(quality.checked_at),
  qualityVerifiedAt: date(quality.snapshot_verified_at),
  qualityExpiresAt: date(quality.expires_at),
  historicalSlice: item.source === 'mt5_backfill',
  calendarState: typeof calendar.state === 'string' ? calendar.state : 'not_configured',
  calendarDetails: typeof calendar.reason === 'string' ? calendar.reason : '',
  calendarCapturedAt: date(calendar.captured_at),
  calendarImportedAt: date(calendar.imported_at),
  calendarExpiresAt: date(calendar.expires_at),
  calendarSnapshotId: typeof calendar.snapshot_id === 'string' ? calendar.snapshot_id : '',
  gapDetails: Object.keys(gaps).length ? `إغلاق موثّق: ${number(gaps.confirmed_closed)} · مغطاة بمسار آخر: ${number(gaps.covered_elsewhere)} · أثناء جلسات أسعار: ${number(gaps.expected_quote_missing)} · غير مؤكدة: ${number(gaps.unknown)}` : '',
}); }, signal);

const loadValidations = (signal?: AbortSignal) => loadRows<ValidationRow>('quality-runs', (item) => ({
  id: text(item.quality_run_id),
  dataset: text(item.dataset_id),
  check: item.checks && typeof item.checks === 'object' ? Object.keys(item.checks as Record<string, unknown>).join(', ') || '—' : '—',
  result: validationResult(item),
  score: typeof item.score === 'number' ? `${(item.score * 100).toFixed(1)}%` : '—',
  checkedAt: date(item.completed_at, item.started_at),
  details: [...(Array.isArray(item.issues) ? item.issues : []), ...(Array.isArray(item.warnings) ? item.warnings : [])].map(String).join(' · '),
  fingerprint: text(item.content_hash),
}), signal);

const loadStrategies = (signal?: AbortSignal) => loadRows<StrategyRow>('strategies', (item) => ({
  id: text(item.strategy_id),
  name: text(item.name),
  family: Array.isArray(item.tags) ? item.tags.map(String).join(', ') || '—' : '—',
  timeframe: Array.isArray(item.timeframes) ? item.timeframes.map(String).join(', ') || '—' : '—',
  status: strategyStatus(item.status),
  confidence: '—',
  lastRun: '—',
}), signal);

const loadBacktests = (signal?: AbortSignal) => loadRows<BacktestRow>('backtests', (item) => {
  const metrics = item.metrics && typeof item.metrics === 'object' ? item.metrics as ResearchItem : {};
  return {
    id: text(item.backtest_id),
    strategy: text(item.strategy_id),
    period: date(item.started_at) === '—' && date(item.completed_at) === '—' ? '—' : `${date(item.started_at)} → ${date(item.completed_at)}`,
    market: text(item.dataset_id),
    returnPct: text(item.return_pct ?? item.returnPct ?? metrics.return_pct ?? metrics.returnPct),
    maxDrawdownPct: text(item.max_drawdown_pct ?? item.maxDrawdownPct ?? metrics.max_drawdown_pct ?? metrics.maxDrawdownPct ?? metrics.max_drawdown),
    status: backtestStatus(item.status),
  };
}, signal);

const loadNews = (signal?: AbortSignal) => loadRows<NewsRow>('news', (item) => ({
  id: text(item.news_id),
  headline: text(item.headline),
  source: text(item.source),
  sentiment: newsSentiment(item.sentiment),
  publishedAt: date(item.published_at),
  relevance: text(Array.isArray(item.symbols) ? item.symbols.map(String).join(', ') : item.impact),
}), signal);

const loadArtifacts = (signal?: AbortSignal) => loadRows<ArtifactRow>('artifacts', (item) => {
  const metadata = item.metadata && typeof item.metadata === 'object' ? item.metadata as ResearchItem : {};
  return {
    id: text(item.artifact_id),
    name: text(item.name),
    kind: text(item.artifact_type),
    version: text(item.version ?? metadata.version),
    size: text(item.size ?? metadata.size),
    state: artifactState(item.status),
  };
}, signal);

const loadProvenance = (signal?: AbortSignal) => loadRows<ProvenanceRow>('datasets', (item) => ({
  id: text(item.dataset_id), asset: text(item.name), origin: text(item.source), owner: 'nexus-data',
  capturedAt: date(item.updated_at), hash: text(item.content_hash, 'البصمة غير متاحة'),
}), signal);

export const researchSources = {
  'data-import': { key: 'data-import', label: 'استيراد البيانات', readOnly: true, load: loadDataImports } satisfies ResearchSource<DataImportRow>,
  cleaning: { key: 'cleaning', label: 'التنظيف', readOnly: true, load: () => unavailable<CleaningRow>() } satisfies ResearchSource<CleaningRow>,
  validation: { key: 'validation', label: 'التحقق', readOnly: true, load: loadValidations } satisfies ResearchSource<ValidationRow>,
  provenance: { key: 'provenance', label: 'التتبّع', readOnly: true, load: loadProvenance } satisfies ResearchSource<ProvenanceRow>,
  strategies: { key: 'strategies', label: 'الاستراتيجيات', readOnly: true, load: loadStrategies } satisfies ResearchSource<StrategyRow>,
  backtests: { key: 'backtests', label: 'الاختبارات التاريخية', readOnly: true, load: loadBacktests } satisfies ResearchSource<BacktestRow>,
  news: { key: 'news', label: 'الأخبار', readOnly: true, load: loadNews } satisfies ResearchSource<NewsRow>,
  artifacts: { key: 'artifacts', label: 'المخرجات', readOnly: true, load: loadArtifacts } satisfies ResearchSource<ArtifactRow>,
} as const;

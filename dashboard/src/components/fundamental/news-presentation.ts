// Pure presentation helpers for the news feed / news intelligence panels.
// Truth contract: unknown ≠ 0 ≠ ready. A missing pipeline state never renders
// as "no news"; it renders with its reason. Stale snapshots stay visible but
// labelled. Filters never invent data.

export type NewsFeedViewState = 'loading' | 'ready' | 'stale' | 'empty' | 'unavailable' | 'offline';

export type ImpactFilter = 'ALL' | 'HIGH' | 'MEDIUM' | 'LOW';
export type PeriodFilter = 'ALL' | '1H' | '24H' | '7D';

export interface NewsSourceTruth {
  source_id: string;
  name_ar?: string | null;
  configuration_status?: string | null;
  configuration_reason_ar?: string | null;
  connectivity?: string | null;
  last_success_at?: string | null;
}

export interface NewsFeedEnvelope {
  state?: string | null;
  last_update_at?: string | null;
  first_available_at?: string | null;
  freshness?: { stale?: boolean | null; age_sec?: number | null; limit_sec?: number | null } | null;
  reason_ar?: string | null;
  sources?: NewsSourceTruth[] | null;
}

export interface NewsRow {
  headline?: string | null;
  impact?: string | null;
  timestamp?: string | null;
  affected_currencies?: string[] | null;
  source?: string | null;
}

export function impactValue(v: string | null | undefined): 'HIGH' | 'MEDIUM' | 'LOW' {
  const x = String(v ?? '').toUpperCase();
  return x === 'HIGH' || x === 'MEDIUM' ? x : 'LOW';
}

export function newsFeedViewState(payload: NewsFeedEnvelope | null, fetchFailed: boolean): NewsFeedViewState {
  if (fetchFailed) return 'offline';
  if (!payload) return 'loading';
  const state = String(payload.state ?? '').toLowerCase();
  if (state === 'ready' || state === 'stale' || state === 'empty' || state === 'unavailable') return state;
  // A payload without an explicit state claim is not ready.
  return 'unavailable';
}

export function periodMinutes(period: PeriodFilter): number | null {
  switch (period) {
    case '1H': return 60;
    case '24H': return 60 * 24;
    case '7D': return 60 * 24 * 7;
    default: return null;
  }
}

export function symbolCodes(symbol: string): Set<string> {
  const s = String(symbol ?? '').toUpperCase().replace('/', '');
  if (s.length >= 6) return new Set([s, s.slice(0, 3), s.slice(3, 6)]);
  return s ? new Set([s]) : new Set();
}

export function matchesImpact(item: NewsRow, filter: ImpactFilter): boolean {
  return filter === 'ALL' || impactValue(item.impact) === filter;
}

export function matchesSymbol(item: NewsRow, symbol: string, filter: 'ALL' | string): boolean {
  if (filter === 'ALL') return true;
  const codes = symbolCodes(symbol);
  const itemCodes = new Set((item.affected_currencies ?? []).map((c) => String(c).toUpperCase()));
  for (const code of codes) if (itemCodes.has(code)) return true;
  return false;
}

export function matchesPeriod(item: NewsRow, period: PeriodFilter, now: number): boolean {
  const minutes = periodMinutes(period);
  if (minutes == null) return true;
  const ts = new Date(String(item.timestamp ?? '')).getTime();
  // Rows without a verifiable timestamp cannot be placed inside a time window.
  if (!Number.isFinite(ts)) return false;
  return now - ts <= minutes * 60_000;
}

export function matchesSource(item: NewsRow, filter: string): boolean {
  if (!filter || filter === 'ALL') return true;
  return String(item.source ?? '') === filter;
}

export function newsSourceOptions(items: NewsRow[]): string[] {
  return [...new Set(items.map((i) => String(i.source ?? '')).filter(Boolean))].sort();
}

export function filterNewsItems<T extends NewsRow>(
  items: T[],
  opts: { impact?: ImpactFilter; symbol?: string; symbolFilter?: 'ALL' | string; period?: PeriodFilter; source?: string; now: number },
): T[] {
  const impact = opts.impact ?? 'ALL';
  const period = opts.period ?? 'ALL';
  const symbol = opts.symbol ?? '';
  const symbolFilter = opts.symbolFilter ?? 'ALL';
  const source = opts.source ?? 'ALL';
  return items.filter(
    (item) =>
      matchesImpact(item, impact) &&
      matchesSymbol(item, symbol, symbolFilter) &&
      matchesPeriod(item, period, opts.now) &&
      matchesSource(item, source),
  );
}

export interface NewsFeedBanners {
  lastUpdateLabel: string | null;
  firstAvailableLabel: string | null;
  staleWarning: string | null;
  reasonAr: string | null;
  sourceIssues: string[];
}

function fmt(value: string | null | undefined): string | null {
  if (!value) return null;
  const d = new Date(String(value));
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString('ar');
}

export function newsFeedBanners(payload: NewsFeedEnvelope | null, viewState: NewsFeedViewState): NewsFeedBanners {
  const lastUpdateLabel = fmt(payload?.last_update_at);
  const firstAvailableLabel = fmt(payload?.first_available_at);
  const stale = payload?.freshness?.stale === true || viewState === 'stale';
  const staleWarning = stale
    ? `تنبيه حداثة: اللقطة المخزنة أقدم من الحد المقبول${
        typeof payload?.freshness?.limit_sec === 'number' ? ` (${payload.freshness.limit_sec} ثانية)` : ''
      }. تُعرض كبيانات مخزنة وليست حية.`
    : null;
  const reasonAr = payload?.reason_ar ?? null;
  const sourceIssues = (payload?.sources ?? [])
    .filter((s) => {
      const status = String(s.configuration_status ?? '').toLowerCase();
      const connectivity = String(s.connectivity ?? '').toLowerCase();
      return status !== 'configured' || connectivity === 'degraded' || connectivity === 'offline' || connectivity === 'config_required';
    })
    .map((s) => `${s.name_ar ?? s.source_id}: ${s.configuration_reason_ar ?? 'حالة غير مطابقة للتحليل.'}`);
  return { lastUpdateLabel, firstAvailableLabel, staleWarning, reasonAr, sourceIssues };
}

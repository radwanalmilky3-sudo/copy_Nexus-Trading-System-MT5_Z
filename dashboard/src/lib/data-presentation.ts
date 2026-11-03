export function positionPresentation(status: { received: boolean; stale: boolean; liveConnected: boolean; count: number }) {
  const confirmed = status.received && !status.stale && status.liveConnected;
  return {
    confirmed,
    emptyMessage: confirmed
      ? 'No open positions in the verified live snapshot.'
      : status.received && status.stale
        ? 'Position snapshot is stale. Current positions and P&L cannot be confirmed.'
        : 'Position data unavailable or awaiting verification. Cannot confirm whether positions are open.',
  };
}

export function backtestHasObservations(count: unknown): boolean {
  return typeof count === 'number' && Number.isInteger(count) && count > 0;
}

export function gatewayTiltStatus(tilt: unknown, risk: unknown, stale: boolean): string {
  if (stale) return 'UNKNOWN';
  const status = tilt ?? risk;
  return status === 'NORMAL' || status === 'WARNING' || status === 'TILT' ? status : 'UNKNOWN';
}

export interface SessionPerformance {
  session: string; trades: number; win_rate: number; net_pnl: number | null; kelly: number | null;
}

export async function fetchSessionPerformance(api: string, headers: HeadersInit): Promise<SessionPerformance[]> {
  const response = await fetch(`${api}/api/intelligence/trade-memory`, { headers });
  if (!response.ok) throw new Error(`Trade memory unavailable (HTTP ${response.status})`);
  const snapshot = await response.json();
  const metrics = snapshot?.metrics;
  if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) throw new Error('Invalid trade memory snapshot');
  const sessions = metrics.by_session ?? {};
  if (typeof sessions !== 'object' || sessions === null || Array.isArray(sessions)) throw new Error('Invalid session metrics');
  const rows: SessionPerformance[] = [];
  for (const [session, value] of Object.entries(sessions)) {
    if (!value || typeof value !== 'object') continue;
    const s = value as Record<string, unknown>;
    const n = s.trades ?? s.total_trades, wr = s.win_rate, avgW = s.avg_win_pips, rawLoss = s.avg_loss_pips, pnl = s.net_pnl_usd;
    if (typeof n !== 'number' || !Number.isInteger(n) || n < 3 || typeof wr !== 'number' || !Number.isFinite(wr) || wr < 0 || wr > 1) continue;
    const kelly = typeof avgW === 'number' && Number.isFinite(avgW) && avgW > 0 && typeof rawLoss === 'number' && Number.isFinite(rawLoss) && Math.abs(rawLoss) > 0
      ? wr - (1 - wr) / (avgW / Math.abs(rawLoss)) : null;
    rows.push({ session, trades: n, win_rate: wr, net_pnl: typeof pnl === 'number' && Number.isFinite(pnl) ? pnl : null, kelly });
  }
  return rows;
}

// ── Cross-Asset presentation (UI-04 guard) ────────────────────────────────────

export interface CrossAssetPayloadLike {
  dxy?: { level?: number | null } | null;
  us10y?: { level?: number | null } | null;
  gold_yield_regime?: unknown;
  cross_asset_signal_pts?: unknown;
  gold_dxy_divergence?: unknown;
  updated_at?: unknown;
}

export interface CrossAssetPresentation {
  available: boolean;
  regime: string;
  pts: number | null;
  divergence: number | null;
  updatedAt: string | null;
}

const KNOWN_REGIMES = new Set(['risk_off', 'risk_on', 'high_rates', 'neutral', 'unknown', 'unavailable']);

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/**
 * Display-boundary guard for the cross-asset panel. Missing price inputs must
 * never produce a trading grade: with no DXY/US10Y levels there is no regime
 * and no signal points, regardless of what a (possibly stale or regressed)
 * payload claims. Closes UI-04 at the presentation layer.
 */
export function crossAssetPresentation(p: CrossAssetPayloadLike | null | undefined): CrossAssetPresentation {
  const hasAnyPrice =
    (p?.dxy != null && isFiniteNumber(p.dxy.level)) ||
    (p?.us10y != null && isFiniteNumber(p.us10y.level));
  if (!p || !hasAnyPrice) {
    return { available: false, regime: 'unknown', pts: null, divergence: null, updatedAt: null };
  }
  const rawRegime = typeof p.gold_yield_regime === 'string' ? p.gold_yield_regime : 'unknown';
  const pts = isFiniteNumber(p.cross_asset_signal_pts) && p.cross_asset_signal_pts >= 0 && p.cross_asset_signal_pts <= 5
    ? p.cross_asset_signal_pts
    : null;
  const divergence = p.gold_dxy_divergence === 1 || p.gold_dxy_divergence === -1 || p.gold_dxy_divergence === 0
    ? p.gold_dxy_divergence
    : null;
  return {
    available: true,
    regime: KNOWN_REGIMES.has(rawRegime) ? rawRegime : 'unknown',
    pts,
    divergence,
    updatedAt: typeof p.updated_at === 'string' ? p.updated_at : null,
  };
}

// ── Trade-memory presentation (UI-05 guard) ───────────────────────────────────

export interface TradeMemoryPresentation {
  hasMetrics: boolean;
  totalTrades: number | null;
  totalWins: number | null;
  totalLosses: number | null;
  winRate: number | null;
  avgPnlPips: number | null;
  zeroTrades: boolean;
}

function finiteInt(v: unknown, min = 0): number | null {
  return isFiniteNumber(v) && Number.isInteger(v) && v >= min ? v : null;
}

function finiteRate(v: unknown): number | null {
  return isFiniteNumber(v) && v >= 0 && v <= 1 ? v : null;
}

/**
 * Never leak `undefined`/`NaN` into the trade-memory header or summary strip.
 * A missing total_trades stays unknown (null) — it is NOT silently coerced to
 * 0, because "zero trades" and "metrics incomplete" are different states.
 */
export function tradeMemoryPresentation(metrics: unknown): TradeMemoryPresentation {
  if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) {
    return { hasMetrics: false, totalTrades: null, totalWins: null, totalLosses: null, winRate: null, avgPnlPips: null, zeroTrades: false };
  }
  const m = metrics as Record<string, unknown>;
  const totalTrades = finiteInt(m.total_trades);
  return {
    hasMetrics: true,
    totalTrades,
    totalWins: finiteInt(m.total_wins),
    totalLosses: finiteInt(m.total_losses),
    winRate: finiteRate(m.overall_win_rate),
    avgPnlPips: isFiniteNumber(m.avg_pnl_pips) ? m.avg_pnl_pips : null,
    zeroTrades: totalTrades === 0,
  };
}

export interface GroupStatRow {
  key: string;
  trades: number | null;
  winRate: number | null;
  avgPnl: number | null;
}

/**
 * Sanitize a by_session/by_direction/... breakdown record: only numeric,
 * finite values survive; anything else becomes null so the table renders an
 * em dash instead of `NaN%` or `undefinedt`.
 */
export function sanitizeGroupStats(raw: unknown): GroupStatRow[] {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return [];
  return Object.entries(raw as Record<string, unknown>)
    .filter((entry): entry is [string, Record<string, unknown>] =>
      Boolean(entry[1]) && typeof entry[1] === 'object' && !Array.isArray(entry[1]))
    .map(([key, s]) => ({
      key,
      trades: finiteInt(s.trades ?? s.total_trades),
      winRate: finiteRate(s.win_rate),
      avgPnl: isFiniteNumber(s.avg_pnl) ? s.avg_pnl : isFiniteNumber(s.avg_pnl_usd) ? s.avg_pnl_usd : null,
    }));
}

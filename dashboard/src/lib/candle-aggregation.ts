/**
 * M2 — pure candle math for the in-house price chart (lightweight-charts v5).
 *
 * This module is deliberately free of React and lightweight-charts imports:
 * plain structs only, so the node test-suite can import it directly and the
 * honesty contracts stay testable without a browser.
 *
 * Data honesty rules enforced here:
 * - a tick never rewrites an older bucket (no back-filling history),
 * - non-finite / non-positive prices are dropped, never coerced,
 * - an empty candle store produces an EMPTY chart, never synthetic bars.
 */

export type ChartTimeframe = 'M1' | 'M5' | 'M15' | 'H1' | 'H4';

export const TF_SECONDS: Record<ChartTimeframe, number> = {
  M1: 60,
  M5: 300,
  M15: 900,
  H1: 3600,
  H4: 14400,
};

/** Bar struct consumed by lightweight-charts (time = UTCTimestamp seconds). */
export interface ChartBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Row shape returned by the data service (OHLCV). */
export interface CandleRow {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Parse an ISO string / epoch (s or ms) into whole UTC seconds. */
export function safeEpochSeconds(ts: string | number | null | undefined): number | null {
  if (ts == null) return null;
  if (typeof ts === 'number') {
    if (!Number.isFinite(ts) || ts <= 0) return null;
    return Math.floor(ts > 1e12 ? ts / 1000 : ts);
  }
  if (typeof ts !== 'string' || ts.trim() === '') return null;
  const ms = Date.parse(ts);
  return Number.isFinite(ms) && ms > 0 ? Math.floor(ms / 1000) : null;
}

/** Start (seconds) of the bucket containing `epoch` for the timeframe. */
export function bucketStart(epoch: number, tf: ChartTimeframe): number {
  const step = TF_SECONDS[tf] ?? 900;
  return Math.floor(epoch / step) * step;
}

/** Mid price of a bid/ask pair; falls back to the single finite side. */
export function tickPrice(
  bid: number | undefined | null,
  ask: number | undefined | null,
): number | null {
  const b = typeof bid === 'number' && Number.isFinite(bid) && bid > 0 ? bid : null;
  const a = typeof ask === 'number' && Number.isFinite(ask) && ask > 0 ? ask : null;
  if (b != null && a != null) return (b + a) / 2;
  return b ?? a;
}

/**
 * Merge one tick into the in-progress bar. Opens a new bucket when the tick
 * belongs to a later one; returns null for unusable prices and for LATE ticks
 * (older than the current bar — history is never rewritten from ticks).
 */
export function applyTick(
  bar: ChartBar | null,
  epoch: number,
  price: number,
  tf: ChartTimeframe,
): { bar: ChartBar; isNew: boolean } | null {
  if (!Number.isFinite(epoch) || epoch <= 0) return null;
  if (!Number.isFinite(price) || price <= 0) return null;
  const bucket = bucketStart(epoch, tf);
  if (bar && bucket < bar.time) return null;
  if (bar && bucket === bar.time) {
    return {
      bar: {
        ...bar,
        high: Math.max(bar.high, price),
        low: Math.min(bar.low, price),
        close: price,
        volume: bar.volume + 1,
      },
      isNew: false,
    };
  }
  return {
    bar: { time: bucket, open: price, high: price, low: price, close: price, volume: 1 },
    isNew: true,
  };
}

/** Authoritative OHLCV rows → sorted, de-duplicated chart bars. */
export function candleRowsToBars(
  rows: CandleRow[] | null | undefined,
  tf: ChartTimeframe,
): ChartBar[] {
  if (!Array.isArray(rows)) return [];
  const byTime = new Map<number, ChartBar>();
  for (const row of rows) {
    const t = safeEpochSeconds(row?.timestamp);
    if (t == null) continue;
    const o = Number(row.open);
    const h = Number(row.high);
    const l = Number(row.low);
    const c = Number(row.close);
    const v = Number(row.volume ?? 0);
    if (![o, h, l, c].every(Number.isFinite)) continue;
    if (o <= 0 || h <= 0 || l <= 0 || c <= 0) continue;
    const time = bucketStart(t, tf);
    byTime.set(time, {
      time,
      open: o,
      high: Math.max(h, o, c),
      low: Math.min(l, o, c),
      close: c,
      volume: Number.isFinite(v) && v >= 0 ? v : 0,
    });
  }
  return [...byTime.values()].sort((a, b) => a.time - b.time);
}

// ── Markers (trades) & price lines (open positions) ─────────────────────────

export const CHART_MARKER_COLORS = {
  buy: '#39ff14',
  sell: '#ff3b5c',
  exitWin: '#39ff14',
  exitLoss: '#ff3b5c',
} as const;

export const PRICE_LINE_COLORS = {
  entry: '#eab308',
  sl: '#ff3b5c',
  tp: '#00d4ff',
} as const;

export interface TradeLike {
  symbol?: string;
  side?: string;
  opened_at?: string;
  closed_at?: string;
  pnl_usd?: number;
}

export interface ChartMarker {
  time: number;
  position: 'aboveBar' | 'belowBar' | 'inBar';
  shape: 'arrowUp' | 'arrowDown' | 'circle';
  color: string;
  text?: string;
  size?: number;
}

/**
 * Entry arrows + exit circles for one symbol, snapped to timeframe buckets
 * and clipped to the loaded bar range. Most recent `max` events win so an
 * old account cannot flood the chart.
 */
export function tradeMarkers(
  trades: TradeLike[] | null | undefined,
  symbol: string,
  tf: ChartTimeframe,
  range: { from: number; to: number } | null,
  max = 80,
): ChartMarker[] {
  if (!Array.isArray(trades) || !symbol) return [];
  const sym = symbol.toUpperCase();
  const raw: ChartMarker[] = [];
  for (const t of trades) {
    if (!t || String(t.symbol ?? '').toUpperCase() !== sym) continue;
    const side = String(t.side ?? '').toUpperCase();
    const isBuy = side === 'BUY' || side === 'LONG';
    const isSell = side === 'SELL' || side === 'SHORT';
    if (!isBuy && !isSell) continue;
    const openT = safeEpochSeconds(t.opened_at);
    if (openT != null) {
      raw.push({
        time: bucketStart(openT, tf),
        position: isBuy ? 'belowBar' : 'aboveBar',
        shape: isBuy ? 'arrowUp' : 'arrowDown',
        color: isBuy ? CHART_MARKER_COLORS.buy : CHART_MARKER_COLORS.sell,
        text: isBuy ? 'B' : 'S',
        size: 1,
      });
    }
    const closeT = safeEpochSeconds(t.closed_at);
    if (closeT != null) {
      const pnl = Number(t.pnl_usd);
      const win = Number.isFinite(pnl) && pnl >= 0;
      raw.push({
        time: bucketStart(closeT, tf),
        position: isBuy ? 'aboveBar' : 'belowBar',
        shape: 'circle',
        color: win ? CHART_MARKER_COLORS.exitWin : CHART_MARKER_COLORS.exitLoss,
        text: Number.isFinite(pnl) ? `${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}` : 'x',
        size: 0.8,
      });
    }
  }
  raw.sort((a, b) => a.time - b.time);
  const clipped = range
    ? raw.filter((m) => m.time >= range.from && m.time <= range.to)
    : raw;
  return clipped.slice(Math.max(0, clipped.length - max));
}

export interface PositionLike {
  symbol?: string;
  entry_price?: number;
  sl?: number;
  tp1?: number;
  tp?: number;
}

export interface PriceLineSpec {
  price: number;
  color: string;
  title: string;
}

/** Entry / SL / TP lines for the open positions of one symbol. */
export function positionPriceLines(
  positions: PositionLike[] | null | undefined,
  symbol: string,
): PriceLineSpec[] {
  if (!Array.isArray(positions) || !symbol) return [];
  const sym = symbol.toUpperCase();
  const specs: PriceLineSpec[] = [];
  for (const p of positions) {
    if (!p || String(p.symbol ?? '').toUpperCase() !== sym) continue;
    const entry = Number(p.entry_price);
    const sl = Number(p.sl);
    const tp = Number(p.tp1 ?? p.tp);
    if (Number.isFinite(entry) && entry > 0) {
      specs.push({ price: entry, color: PRICE_LINE_COLORS.entry, title: 'ENTRY' });
    }
    if (Number.isFinite(sl) && sl > 0) {
      specs.push({ price: sl, color: PRICE_LINE_COLORS.sl, title: 'SL' });
    }
    if (Number.isFinite(tp) && tp > 0) {
      specs.push({ price: tp, color: PRICE_LINE_COLORS.tp, title: 'TP' });
    }
    if (specs.length >= 12) break;
  }
  return specs.slice(0, 12);
}

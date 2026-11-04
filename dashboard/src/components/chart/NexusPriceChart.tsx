'use client';

/**
 * M2 — in-house candlestick chart on lightweight-charts v5 (canvas, no iframe).
 *
 * Replaces the TradingView embed as the DEFAULT LiveChart body (the embed
 * stays available behind the manual TV toggle — D2 regression guard).
 *
 * Data honesty:
 * - candles come only from the MT5 bridge store via /api/v2/market/candles,
 * - live ticks (ws /ws/ticks) update ONLY the current bucket via
 *   series.update(), throttled to ~10 Hz (plan §5), and never rewrite history,
 * - no bridge data → honest empty state, never synthetic bars.
 *
 * Overlays: ENTRY/SL/TP price lines for open positions of the symbol and
 * B/S arrows + exit circles for recent trades of the symbol.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type IPriceLine,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
  type MouseEventParams,
} from 'lightweight-charts';
import { apiClient, getAuthHeaders } from '@/lib/api-client';
import { wsClient } from '@/lib/ws-client';
import {
  createChartOptions,
  CANDLESTICK_OPTIONS,
  VOLUME_OPTIONS,
  VOLUME_SCALE_OPTIONS,
  VOLUME_UP_COLOR,
  VOLUME_DOWN_COLOR,
} from '@/lib/chart-config';
import {
  applyTick,
  candleRowsToBars,
  positionPriceLines,
  safeEpochSeconds,
  tickPrice,
  tradeMarkers,
  type CandleRow,
  type ChartBar,
  type ChartMarker,
  type ChartTimeframe,
  type PositionLike,
  type TradeLike,
} from '@/lib/candle-aggregation';

const API = process.env.NEXT_PUBLIC_API_URL || '';

type ChartStatus = 'loading' | 'ready' | 'empty' | 'error';

const FLUSH_INTERVAL_MS = 100; // ~10 Hz per plan §5
const REFETCH_INTERVAL_MS = 60_000; // authoritative safety-net refetch
const OVERLAY_REFRESH_MS = 30_000;

const EMPTY_STATUS_LABEL: Record<ChartStatus, string> = {
  loading: '…',
  ready: '',
  empty: 'لا توجد شموع من جسر MT5 لهذا الرمز/الإطار بعد',
  error: 'تعذر تحميل الشموع',
};

function formatLegend(b: ChartBar): string {
  const p = (v: number) => (Number.isFinite(v) ? v.toFixed(2) : '—');
  return `O ${p(b.open)}  H ${p(b.high)}  L ${p(b.low)}  C ${p(b.close)}  V ${Math.round(b.volume)}`;
}

function toCandle(b: ChartBar) {
  return { time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close };
}

export default function NexusPriceChart({
  symbol,
  timeframe,
}: {
  symbol: string;
  timeframe: ChartTimeframe;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const legendRef = useRef<HTMLSpanElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const barsRef = useRef<ChartBar[]>([]);
  const pendingRef = useRef<ChartBar | null>(null);
  const requestSeqRef = useRef(0);
  const statusRef = useRef<ChartStatus>('loading');
  const lastTickAtRef = useRef(0);

  const [status, setStatus] = useState<ChartStatus>('loading');
  const [statusDetail, setStatusDetail] = useState<string>('');
  const [liveNow, setLiveNow] = useState(false);

  const setStatusSafe = useCallback((next: ChartStatus) => {
    statusRef.current = next;
    setStatus(next);
  }, []);

  const clearOverlays = useCallback(() => {
    const candles = candleRef.current;
    if (candles) {
      for (const line of priceLinesRef.current) {
        try { candles.removePriceLine(line); } catch { /* series already gone */ }
      }
    }
    priceLinesRef.current = [];
    markersRef.current?.setMarkers([]);
  }, []);

  /** Overlays: price lines from open positions + markers from trade history. */
  const loadOverlays = useCallback(async (sym: string, tf: ChartTimeframe) => {
    const candles = candleRef.current;
    if (!candles || statusRef.current !== 'ready') return;
    try {
      const res = await apiClient.getPositions();
      const rows = (res?.data ?? []) as unknown as PositionLike[];
      const specs = positionPriceLines(rows, sym);
      for (const line of priceLinesRef.current) {
        try { candles.removePriceLine(line); } catch { /* already removed */ }
      }
      priceLinesRef.current = specs.map((spec) =>
        candles.createPriceLine({
          price: spec.price,
          color: spec.color,
          lineWidth: 1,
          lineStyle: 2, // dashed
          axisLabelVisible: true,
          title: spec.title,
        }),
      );
    } catch {
      // Positions overlay is best-effort — the chart itself must not fail.
    }
    try {
      const res = await fetch(`${API}/api/trades?symbol=${encodeURIComponent(sym)}&page_size=40`, {
        headers: getAuthHeaders(),
      });
      if (!res.ok) return;
      const body = (await res.json()) as { trades?: TradeLike[] };
      const bars = barsRef.current;
      const range = bars.length ? { from: bars[0].time, to: bars[bars.length - 1].time } : null;
      const markers: SeriesMarker<Time>[] = tradeMarkers(body.trades, sym, tf, range).map((m: ChartMarker) => ({
        time: m.time as UTCTimestamp,
        position: m.position,
        shape: m.shape,
        color: m.color,
        text: m.text,
        size: m.size,
      }));
      markersRef.current?.setMarkers(markers);
    } catch {
      // Trade markers are best-effort as well.
    }
  }, []);

  /** Authoritative candle load (initial, symbol/timeframe change, 60s net). */
  const loadBars = useCallback(async (sym: string, tf: ChartTimeframe, opts?: { silent?: boolean }) => {
    const candles = candleRef.current;
    const volume = volumeRef.current;
    if (!candles || !volume) return;
    const seq = ++requestSeqRef.current;
    if (!opts?.silent) {
      setStatusSafe('loading');
      setStatusDetail('');
      barsRef.current = [];
      pendingRef.current = null;
      clearOverlays();
    }
    try {
      const res = await apiClient.getCandles(sym, tf, 500);
      if (seq !== requestSeqRef.current) return; // superseded
      const bars = candleRowsToBars((res?.data ?? []) as CandleRow[], tf);
      if (!bars.length) {
        if (!opts?.silent) setStatusSafe('empty');
        return;
      }
      barsRef.current = bars;
      pendingRef.current = null;
      candles.setData(bars.map(toCandle));
      volume.setData(
        bars.map((b) => ({
          time: b.time as UTCTimestamp,
          value: b.volume,
          color: b.close >= b.open ? VOLUME_UP_COLOR : VOLUME_DOWN_COLOR,
        })),
      );
      chartRef.current?.timeScale().fitContent();
      setStatusSafe('ready');
      const last = bars[bars.length - 1];
      if (legendRef.current) legendRef.current.textContent = formatLegend(last);
      void loadOverlays(sym, tf);
    } catch (e) {
      if (seq !== requestSeqRef.current) return;
      if (!opts?.silent) {
        setStatusSafe('error');
        setStatusDetail(e instanceof Error ? e.message : '');
      }
    }
  }, [clearOverlays, loadOverlays, setStatusSafe]);

  // Chart lifecycle — created once.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = createChart(container, { ...createChartOptions(), autoSize: true });
    const candles = chart.addSeries(CandlestickSeries, CANDLESTICK_OPTIONS);
    const volume = chart.addSeries(HistogramSeries, VOLUME_OPTIONS);
    chart.priceScale('').applyOptions(VOLUME_SCALE_OPTIONS);
    const markers = createSeriesMarkers(candles, []);
    markersRef.current = markers;
    candleRef.current = candles;
    volumeRef.current = volume;
    chartRef.current = chart;

    const onCrosshair = (param: MouseEventParams) => {
      if (!legendRef.current) return;
      const t = typeof param.time === 'number' ? param.time : null;
      const bars = barsRef.current;
      const bar = t != null ? bars.find((b) => b.time === t) : bars[bars.length - 1] ?? null;
      legendRef.current.textContent = bar ? formatLegend(bar) : '';
    };
    chart.subscribeCrosshairMove(onCrosshair);

    return () => {
      chart.unsubscribeCrosshairMove(onCrosshair);
      priceLinesRef.current = [];
      markersRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      chartRef.current = null;
      chart.remove();
    };
  }, []);

  // Data load on symbol / timeframe change.
  useEffect(() => {
    void loadBars(symbol, timeframe);
  }, [symbol, timeframe, loadBars]);

  // Authoritative 60s safety-net refetch (silent — never flips to loading).
  useEffect(() => {
    const id = setInterval(() => void loadBars(symbol, timeframe, { silent: true }), REFETCH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [symbol, timeframe, loadBars]);

  // Live ticks → pending bar (aggregated, never rewriting history).
  useEffect(() => {
    const onTick = (msg: unknown) => {
      const payload = msg as { symbol?: string; bid?: number; ask?: number; timestamp?: string | number };
      if (!payload || String(payload.symbol ?? '').toUpperCase() !== symbol.toUpperCase()) return;
      const price = tickPrice(payload.bid, payload.ask);
      if (price == null) return;
      const epoch = safeEpochSeconds(payload.timestamp) ?? Math.floor(Date.now() / 1000);
      const current = pendingRef.current ?? barsRef.current[barsRef.current.length - 1] ?? null;
      const merged = applyTick(current, epoch, price, timeframe);
      if (!merged) return;
      pendingRef.current = merged.bar;
      lastTickAtRef.current = Date.now();
    };
    const off = wsClient.on('ticks', onTick);
    wsClient.subscribe('ticks', { symbols: symbol });
    return () => {
      off();
      // wsClient is a singleton; today this window is the only ticks consumer.
      wsClient.unsubscribe('ticks');
    };
  }, [symbol, timeframe]);

  // Throttled flush — the ONLY path that calls series.update() (~10 Hz).
  useEffect(() => {
    const id = setInterval(() => {
      const pending = pendingRef.current;
      if (!pending) return;
      pendingRef.current = null;
      const candles = candleRef.current;
      const volume = volumeRef.current;
      if (!candles || !volume) return;
      candles.update(toCandle(pending));
      volume.update({
        time: pending.time as UTCTimestamp,
        value: pending.volume,
        color: pending.close >= pending.open ? VOLUME_UP_COLOR : VOLUME_DOWN_COLOR,
      });
      const bars = barsRef.current;
      if (bars.length && bars[bars.length - 1].time === pending.time) {
        bars[bars.length - 1] = pending;
      } else {
        bars.push(pending);
      }
      if (statusRef.current === 'empty') setStatusSafe('ready');
      if (legendRef.current) legendRef.current.textContent = formatLegend(pending);
    }, FLUSH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [setStatusSafe]);

  // LIVE chip — reflects real tick recency, decays when the bridge goes quiet.
  useEffect(() => {
    const id = setInterval(() => {
      setLiveNow(Date.now() - lastTickAtRef.current < 10_000);
    }, 2_500);
    return () => clearInterval(id);
  }, []);

  // Overlay refresh — positions/trades change over time.
  useEffect(() => {
    const id = setInterval(() => void loadOverlays(symbol, timeframe), OVERLAY_REFRESH_MS);
    return () => clearInterval(id);
  }, [symbol, timeframe, loadOverlays]);

  return (
    <div className="relative h-full min-h-0 w-full">
      <div ref={containerRef} className="absolute inset-0 h-full w-full" />
      <span
        ref={legendRef}
        dir="ltr"
        className="pointer-events-none absolute start-2 top-1 z-10 hidden text-[9px] font-mono text-text-muted sm:block"
      />
      <div className="pointer-events-none absolute end-2 top-1 z-10 flex items-center gap-1.5">
        <span
          className={`rounded px-1.5 py-0.5 text-[8px] font-mono font-bold ${
            liveNow ? 'bg-neon-green/15 text-neon-green' : 'bg-bg-tertiary text-text-muted'
          }`}
          title={liveNow ? 'تيكات حية من جسر MT5' : 'لا تيكات حية حاليًا'}
        >
          {liveNow ? 'LIVE' : 'BRIDGE IDLE'}
        </span>
      </div>
      {status !== 'ready' && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-bg-primary/80 text-center">
          {status === 'loading' && (
            <>
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-neon-cyan/30 border-t-neon-cyan" />
              <p className="text-xs font-mono text-text-muted">جارٍ تحميل شموع {symbol} · {timeframe}…</p>
            </>
          )}
          {status === 'empty' && (
            <>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-text-muted/50">
                <path d="M3 3v18h18" /><path d="M7 15l4-6 4 3 4-8" />
              </svg>
              <p className="max-w-[85%] text-xs font-mono text-text-muted">{EMPTY_STATUS_LABEL.empty}</p>
              <p className="max-w-[85%] text-[10px] font-mono text-text-muted/70">
                اتصِل بطرف MT5 عبر جسر NexusBridge؛ سيبدأ الرسم تلقائيًا مع أول شمعة حية.
              </p>
            </>
          )}
          {status === 'error' && (
            <p className="max-w-[85%] text-xs font-mono text-neon-red" role="alert">
              {EMPTY_STATUS_LABEL.error}{statusDetail ? ` — ${statusDetail}` : ''}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

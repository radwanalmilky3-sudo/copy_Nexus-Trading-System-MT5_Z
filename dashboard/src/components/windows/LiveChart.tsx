'use client';

import { useEffect, useRef, useState } from 'react';
import NeonCard from '../shared/NeonCard';
import NexusPriceChart from '../chart/NexusPriceChart';
import type { Timeframe } from '../../types';
import { useDashboardStore } from '@/stores/dashboardStore';

const TIMEFRAMES: Timeframe[] = ['M1', 'M5', 'M15', 'H1', 'H4'];

// D2 fix — history: the heavy external TradingView widget stalled the
// dashboard tab in memory-constrained environments (2 vCPU / ~150MB free),
// so the embed was made (a) opt-in per browser via localStorage with default
// OFF, (b) mounted on a short delay, (c) fully unmounted when OFF.
// M2: the DEFAULT chart body is now the in-house lightweight-charts v5
// canvas (NexusPriceChart — light, MT5-bridge pricing). The TradingView
// embed remains available as a manual toggle with the same D2 guards.
const TV_ENABLED_KEY = 'nexus_tv_chart_enabled';
const TV_MOUNT_DELAY_MS = 2500;

function readTvEnabled(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(TV_ENABLED_KEY) === '1';
  } catch {
    return false;
  }
}

function toTVSymbol(sym: string): string {
  const MAP: Record<string, string> = {
    XAUUSD: 'OANDA:XAUUSD',
    BTCUSD: 'BITSTAMP:BTCUSD',
  };
  return MAP[sym.toUpperCase()] ?? `FX:${sym}`;
}

function toTVInterval(tf: Timeframe): string {
  const MAP: Record<Timeframe, string> = {
    M1: '1', M5: '5', M15: '15', H1: '60', H4: '240',
  };
  return MAP[tf] ?? '15';
}

const SYMBOLS = ['XAUUSD', 'BTCUSD', 'EURUSD'];

export default function LiveChart() {
  const selectedSymbol = useDashboardStore((s) => s.symbol);
  const activeTimeframe = useDashboardStore((s) => s.timeframe);
  const setSymbol = useDashboardStore((s) => s.setSymbol);
  const setTimeframe = useDashboardStore((s) => s.setTimeframe);

  const [showSymbolPicker, setShowSymbolPicker] = useState(false);
  // Hydration-safe: start with the placeholder, then adopt the stored
  // preference and honor the mount delay once we are on the client.
  const [tvEnabled, setTvEnabled] = useState(false);
  const [tvMounted, setTvMounted] = useState(false);
  const mountTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const enabled = readTvEnabled();
    setTvEnabled(enabled);
    if (enabled) {
      mountTimer.current = setTimeout(() => setTvMounted(true), TV_MOUNT_DELAY_MS);
    }
    return () => {
      if (mountTimer.current) clearTimeout(mountTimer.current);
    };
  }, []);

  const toggleTv = () => {
    const next = !tvEnabled;
    setTvEnabled(next);
    try {
      window.localStorage.setItem(TV_ENABLED_KEY, next ? '1' : '0');
    } catch {
      /* storage unavailable — session-only toggle */
    }
    if (mountTimer.current) clearTimeout(mountTimer.current);
    if (next) {
      mountTimer.current = setTimeout(() => setTvMounted(true), TV_MOUNT_DELAY_MS);
    } else {
      setTvMounted(false);
    }
  };

  return (
    <NeonCard
      title="Market Chart"
      glow="cyan"
      noPadding
      icon={
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 3v18h18" />
          <path d="M7 16l4-8 4 4 4-12" />
        </svg>
      }
      headerRight={
        <div className="flex items-center gap-3">
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowSymbolPicker(!showSymbolPicker)}
              className="flex items-center gap-1 rounded bg-bg-secondary px-2 py-1 text-xs font-mono text-neon-cyan hover:bg-bg-tertiary transition-colors"
            >
              {selectedSymbol}
              <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z" /></svg>
            </button>
            {showSymbolPicker && (
              <div className="absolute left-0 top-full z-50 mt-1 rounded border border-border-primary/20 bg-bg-primary shadow-lg">
                {SYMBOLS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => {
                      setSymbol(s);
                      setShowSymbolPicker(false);
                    }}
                    className={`block w-full px-3 py-1.5 text-left text-xs font-mono hover:bg-bg-tertiary transition-colors ${
                      s === selectedSymbol ? 'text-neon-cyan' : 'text-text-secondary'
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      }
      className="h-full min-h-0 flex flex-col"
    >
      <div className="flex items-center gap-1 border-b border-border-primary/10 px-3 py-1 shrink-0">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            type="button"
            onClick={() => setTimeframe(tf)}
            className={`rounded px-2.5 py-1 text-[11px] font-mono font-semibold transition-all ${
              tf === activeTimeframe
                ? 'bg-neon-purple/15 text-neon-purple'
                : 'text-text-muted hover:text-text-secondary hover:bg-bg-tertiary'
            }`}
          >
            {tf}
          </button>
        ))}
        <span className="ml-auto text-[8px] font-mono text-text-muted">
          {tvEnabled
            ? 'TradingView external · not MT5 execution pricing'
            : 'Nexus v5 canvas · MT5 bridge pricing'}
        </span>
        <button
          type="button"
          onClick={toggleTv}
          title={tvEnabled ? 'Disable external TradingView chart (frees resources)' : 'Enable external TradingView chart'}
          className={`rounded px-2 py-0.5 text-[10px] font-mono font-bold transition-all ${
            tvEnabled
              ? 'bg-neon-cyan/15 text-neon-cyan hover:bg-neon-cyan/25'
              : 'text-text-muted hover:text-text-secondary hover:bg-bg-tertiary'
          }`}
        >
          TV {tvEnabled ? 'ON' : 'OFF'}
        </button>
      </div>

      <div className="relative flex-1 min-h-0 w-full">
        {tvEnabled && tvMounted ? (
          <iframe
            key={`${selectedSymbol}-${activeTimeframe}`}
            src={`https://www.tradingview.com/widgetembed/?frameElementId=tv_chart&symbol=${encodeURIComponent(toTVSymbol(selectedSymbol))}&interval=${toTVInterval(activeTimeframe)}&theme=dark&style=1&locale=en&toolbar_bg=%230a0a0f&enable_publishing=0&hide_side_toolbar=1&allow_symbol_change=0&save_image=0&studies=RSI%40tv-basicstudies&studies=MACD%40tv-basicstudies`}
            className="absolute inset-0 w-full h-full border-0 block"
            title={`TradingView external chart for ${selectedSymbol}; not the MT5 execution quote`}
            allow="clipboard-write"
            loading="lazy"
          />
        ) : tvEnabled ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center">
            <p className="text-xs font-mono text-text-muted">
              External chart loading… {selectedSymbol} · {activeTimeframe}
            </p>
            <p className="text-[10px] font-mono text-text-muted/70 max-w-[80%]">
              Mounting the TradingView embed shortly to keep the dashboard responsive.
            </p>
          </div>
        ) : (
          <NexusPriceChart symbol={selectedSymbol} timeframe={activeTimeframe} />
        )}
      </div>
    </NeonCard>
  );
}

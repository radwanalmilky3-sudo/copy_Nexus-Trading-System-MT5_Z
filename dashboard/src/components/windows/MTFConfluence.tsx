'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { Layers, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getAuthHeaders } from '@/lib/api-client';

const API = process.env.NEXT_PUBLIC_API_URL || '';

interface TFData {
  bias: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  close: number;
  rsi: number;
  adx: number;
  macd_hist: number;
  atr: number;
  bb_pct_b: number;
  ema_stack: { ema9: number; ema21: number; ema50: number };
}

interface MTFData {
  symbol: string;
  timeframes: Record<string, TFData>;
  confluence: {
    alignment_score: number;
    bull_count: number;
    bear_count: number;
    total_tfs: number;
    overall_bias: string;
  };
}

const TF_ORDER = ['D1', 'H4', 'H1', 'M15', 'M5'];
const TF_LABELS: Record<string, string> = { D1: 'Daily', H4: '4H', H1: '1H', M15: '15M', M5: '5M' };
const TF_WEIGHT: Record<string, string> = { D1: 'Macro', H4: 'الجلسة (Session)', H1: 'Intraday', M15: 'Momentum', M5: 'التنفيذ (Execution)' };

const BIAS_CONFIG = {
  BULLISH: { color: 'text-neon-green', bg: 'bg-neon-green/10', icon: TrendingUp, dot: 'bg-neon-green' },
  BEARISH: { color: 'text-neon-red',   bg: 'bg-neon-red/10',   icon: TrendingDown, dot: 'bg-neon-red' },
  NEUTRAL: { color: 'text-text-muted', bg: 'bg-bg-tertiary',   icon: Minus,        dot: 'bg-text-muted' },
};

export default function MTFConfluence({ symbol = 'XAUUSD' }: { symbol?: string }) {
  const [data, setData] = useState<MTFData | null>(null);
  const [loadError, setLoadError] = useState(false);

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/intelligence/mtf-context/${symbol}`, { headers: getAuthHeaders() });
      if (!res.ok) throw new Error('MTF context unavailable');
      const next = await res.json() as MTFData;
      if (!next?.confluence || typeof next.timeframes !== 'object' || next.timeframes === null) throw new Error('MTF response incomplete');
      setData(next);
      setLoadError(false);
    } catch { setLoadError(true); }
  }, [symbol]);

  useEffect(() => { fetch_(); const t = setInterval(fetch_, 5000); return () => clearInterval(t); }, [fetch_]);

  const conf = data?.confluence;
  const score = conf ? conf.alignment_score : 0;
  const overallBias = conf?.overall_bias || 'NEUTRAL';
  const overallCfg = BIAS_CONFIG[overallBias as keyof typeof BIAS_CONFIG] || BIAS_CONFIG.NEUTRAL;
  const OverallIcon = overallCfg.icon;

  // Score bar: -4 to +4 → 0-100%.
  const scorePct = ((score + 4) / 8) * 100;
  const scoreColor = score >= 2 ? 'bg-neon-green' : score <= -2 ? 'bg-neon-red' : 'bg-yellow-500';

  return (
    <div className="flex flex-col gap-0 h-full">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border-primary/50">
        <Layers className="h-3.5 w-3.5 text-neon-cyan" />
        <span className="text-[11px] font-mono font-bold text-text-secondary tracking-wider">MTF CONFLUENCE</span>
        <span className="ms-2 text-[9px] font-mono text-text-muted" dir="ltr">{symbol}</span>
        <div className="ms-auto flex items-center gap-2">
          {data ? <><OverallIcon className={cn('h-3 w-3', overallCfg.color)} />
          <span className={cn('text-[10px] font-mono font-bold', overallCfg.color)}>{overallBias}</span></> :
            <span className="text-[10px] font-mono text-neon-gold">غير متاح</span>}
        </div>
      </div>

      {loadError && <p role="alert" className="px-3 pt-1 text-[9px] text-neon-gold">تعذر تحديث توافق الأطر الزمنية؛ المعروض قديم إن وُجد.</p>}

      {/* Alignment bar */}
      <div className="px-3 py-2">
        {!data && <p role="status" className="text-[9px] text-text-muted mb-2">لا توجد قراءة MTF حالية؛ لا يُفترض اتجاه محايد.</p>}
        <div className="flex items-center justify-between mb-1">
          <span className="text-[9px] font-mono text-text-muted">BEAR</span>
          <span className="text-[9px] font-mono text-text-secondary font-bold">Score {data ? `${score > 0 ? '+' : ''}${score} / 4` : '—'}</span>
          <span className="text-[9px] font-mono text-text-muted">BULL</span>
        </div>
        <div className="relative h-2 bg-bg-tertiary rounded-full overflow-hidden">
          {/* Center marker */}
          <div className="absolute top-0 bottom-0 left-1/2 w-px bg-border-primary" />
          <div
            className={cn('absolute top-0 bottom-0 rounded-full transition-all duration-700', scoreColor)}
            style={{
              left: score >= 0 ? '50%' : `${scorePct}%`,
              right: score < 0 ? '50%' : `${100 - scorePct}%`,
            }}
          />
        </div>
        <div className="flex justify-between mt-1">
          <span className="text-[9px] font-mono text-neon-red">{conf ? conf.bear_count : '—'} TF bear</span>
          <span className="text-[9px] font-mono text-neon-green">{conf ? conf.bull_count : '—'} TF bull</span>
        </div>
      </div>

      {/* Per-TF rows */}
      <div className="flex flex-col gap-0 flex-1 overflow-y-auto px-3 pb-2">
        {TF_ORDER.map((tf) => {
          const tfData = data?.timeframes[tf];
          const bias = tfData?.bias || 'NEUTRAL';
          const biasLabel = tfData ? bias : '—';
          const bCfg = BIAS_CONFIG[bias];
          const BiasIcon = bCfg.icon;

          return (
            <div key={tf} className="flex items-center gap-2 py-1.5 border-b border-border-primary/20 last:border-0">
              {/* TF label */}
              <div className="w-10 shrink-0">
                <div className="text-[10px] font-mono font-bold text-text-secondary">{TF_LABELS[tf]}</div>
                <div className="text-[8px] font-mono text-text-muted">{TF_WEIGHT[tf]}</div>
              </div>

              {/* Bias badge */}
              <div className={cn('flex items-center gap-1 px-1.5 py-0.5 rounded border text-[9px] font-mono w-20 shrink-0', bCfg.bg, 'border-current')}>
                <div className={cn('w-1.5 h-1.5 rounded-full', bCfg.dot)} />
                <span className={bCfg.color}>{biasLabel}</span>
              </div>

              {/* Mini stats */}
              {tfData && (
                <div className="flex gap-3 text-[9px] font-mono text-text-muted flex-1 min-w-0 overflow-hidden">
                  <span>RSI <span className={tfData.rsi > 60 ? 'text-neon-green' : tfData.rsi < 40 ? 'text-neon-red' : 'text-text-secondary'}>{tfData.rsi.toFixed(0)}</span></span>
                  <span>ADX <span className={tfData.adx > 25 ? 'text-neon-cyan' : 'text-text-secondary'}>{tfData.adx.toFixed(0)}</span></span>
                  <span className="hidden sm:inline">ATR <span className="text-text-secondary">{tfData.atr.toFixed(2)}</span></span>
                </div>
              )}

              {!tfData && <span className="text-[9px] font-mono text-text-muted">لا توجد بيانات</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

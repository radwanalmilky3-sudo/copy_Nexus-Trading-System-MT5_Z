'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { Brain, TrendingUp, TrendingDown, Minus, Clock, Zap, AlertTriangle, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getAuthHeaders } from '@/lib/api-client';
import { sanitizeGroupStats, tradeMemoryPresentation } from '@/lib/data-presentation';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000';

interface GroupStats {
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_pnl: number;
}

interface Streak { type: 'win' | 'loss' | 'none'; count: number }

interface Metrics {
  total_trades: number;
  total_wins: number;
  total_losses: number;
  overall_win_rate: number;
  avg_pnl_pips: number;
  recent_streak: Streak;
  by_session: Record<string, GroupStats>;
  by_direction: Record<string, GroupStats>;
  by_regime: Record<string, GroupStats>;
  by_source: Record<string, GroupStats>;
  by_hour: Record<string, GroupStats>;
}

interface Thresholds {
  quality_score_threshold: number;
  conviction_min: number;
  good_hours: string[];
  bad_hours: string[];
  hour_wr: Record<string, number>;
  overall_wr: number;
  total_trades: number;
  computed_at: string | null;
}

interface MemoryData {
  metrics: Metrics;
  thresholds: Thresholds;
  recent_trades: Record<string, unknown>[];
}

type ActiveTab = 'session' | 'direction' | 'regime' | 'hours' | 'thresholds';

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrColor(wr: number) {
  if (wr >= 0.55) return 'text-neon-green';
  if (wr >= 0.40) return 'text-yellow-400';
  return 'text-neon-red';
}

function pnlColor(v: number) {
  return v > 0 ? 'text-neon-green' : v < 0 ? 'text-neon-red' : 'text-text-muted';
}

function BreakdownTable({ data, label }: { data: unknown; label: string }) {
  const rows = sanitizeGroupStats(data).sort((a, b) => (b.trades ?? -1) - (a.trades ?? -1));
  if (!rows.length) return (
    <div className="text-[9px] font-mono text-text-muted text-center py-4">لا توجد بيانات</div>
  );
  return (
    <div className="flex flex-col gap-0.5">
      {rows.map((s) => (
        <div key={s.key} className="flex items-center gap-2 px-2 py-0.5 rounded hover:bg-bg-tertiary/20">
          <span className="text-[9px] font-mono text-text-muted w-20 shrink-0 truncate">{s.key}</span>
          <div className="flex-1 h-1 rounded-full bg-bg-tertiary/40 overflow-hidden">
            <div
              className={cn('h-full rounded-full', s.winRate != null && s.winRate >= 0.5 ? 'bg-neon-green/60' : 'bg-neon-red/60')}
              style={{ width: `${s.winRate != null ? Math.min(s.winRate * 100, 100) : 0}%` }}
            />
          </div>
          <span className={cn('text-[9px] font-mono font-bold w-9 text-right shrink-0', s.winRate != null ? wrColor(s.winRate) : 'text-text-muted')}>
            {s.winRate != null ? `${(s.winRate * 100).toFixed(0)}%` : '—'}
          </span>
          <span className={cn('text-[8px] font-mono w-12 text-right shrink-0', s.avgPnl != null ? pnlColor(s.avgPnl) : 'text-text-muted')}>
            {s.avgPnl != null ? `${s.avgPnl > 0 ? '+' : ''}${s.avgPnl.toFixed(1)}p` : '—'}
          </span>
          <span className="text-[8px] font-mono text-text-muted w-7 text-right shrink-0">{s.trades != null ? `${s.trades}t` : '—'}</span>
        </div>
      ))}
    </div>
  );
}

function HourGrid({ byHour, goodHours, badHours }: {
  byHour: Record<string, GroupStats>;
  goodHours: string[];
  badHours: string[];
}) {
  const stats = new Map(sanitizeGroupStats(byHour).map((r) => [r.key, r]));
  const hours = Array.from({ length: 24 }, (_, i) => `H${i.toString().padStart(2, '0')}`);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap gap-0.5">
        {hours.map((h) => {
          const s = stats.get(h);
          const isGood = goodHours.includes(h);
          const isBad = badHours.includes(h);
          const wr = s?.winRate ?? null;
          return (
            <div
              key={h}
              title={wr != null || s?.trades != null
                ? `${h}: ${wr != null ? `${(wr * 100).toFixed(0)}% WR` : 'WR —'} — ${s?.trades ?? '—'} trades`
                : `${h}: لا توجد بيانات`}
              className={cn(
                'w-7 h-7 rounded flex flex-col items-center justify-center cursor-default border',
                isGood ? 'border-neon-green/40 bg-neon-green/10' :
                isBad  ? 'border-neon-red/40 bg-neon-red/10' :
                s       ? 'border-border-primary/30 bg-bg-tertiary/20' :
                          'border-border-primary/10 bg-transparent',
              )}
            >
              <span className="text-[7px] font-mono text-text-muted leading-none">{h.slice(1)}</span>
              {wr !== null && (
                <span className={cn('text-[7px] font-mono font-bold leading-none', wrColor(wr))}>
                  {(wr * 100).toFixed(0)}
                </span>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-3 text-[8px] font-mono text-text-muted mt-0.5">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded border border-neon-green/40 bg-neon-green/10 inline-block" /> جيدة (≥50%)</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded border border-neon-red/40 bg-neon-red/10 inline-block" /> سيئة (&lt;30%)</span>
      </div>
    </div>
  );
}

function ThresholdsView({ t }: { t: Thresholds }) {
  if (!t.computed_at) return (
    <div className="text-[9px] font-mono text-text-muted text-center py-4">لا توجد Thresholds محسوبة</div>
  );
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-1.5">
        <div className="bg-bg-tertiary/30 rounded px-2 py-1.5">
          <div className="text-[8px] font-mono text-text-muted">Signal Quality Min</div>
          <div className="text-sm font-mono font-black text-neon-purple">
            {typeof t.quality_score_threshold === 'number' && Number.isFinite(t.quality_score_threshold) ? t.quality_score_threshold : '—'}
          </div>
        </div>
        <div className="bg-bg-tertiary/30 rounded px-2 py-1.5">
          <div className="text-[8px] font-mono text-text-muted">Conviction Min</div>
          <div className="text-sm font-mono font-black text-neon-purple">
            {typeof t.conviction_min === 'number' && Number.isFinite(t.conviction_min) ? `${(t.conviction_min * 100).toFixed(0)}%` : '—'}
          </div>
        </div>
      </div>
      {t.good_hours.length > 0 && (
        <div className="bg-neon-green/5 border border-neon-green/20 rounded px-2 py-1.5">
          <div className="text-[8px] font-mono text-neon-green mb-0.5">الساعات الجيدة (UTC)</div>
          <div className="text-[9px] font-mono text-text-secondary">{t.good_hours.join(' · ')}</div>
        </div>
      )}
      {t.bad_hours.length > 0 && (
        <div className="bg-neon-red/5 border border-neon-red/20 rounded px-2 py-1.5">
          <div className="text-[8px] font-mono text-neon-red mb-0.5">الساعات السيئة (UTC)</div>
          <div className="text-[9px] font-mono text-text-secondary">{t.bad_hours.join(' · ')}</div>
        </div>
      )}
      {t.computed_at && (
        <div className="text-[8px] font-mono text-text-muted">
          محسوب: <span dir="ltr">{new Date(t.computed_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</span>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function TradeMemoryPanel() {
  const [data, setData] = useState<MemoryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [activeTab, setActiveTab] = useState<ActiveTab>('session');

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/intelligence/trade-memory`, { headers: getAuthHeaders() });
      if (!res.ok) throw new Error(`trade memory request failed (${res.status})`);
      const next = await res.json() as MemoryData;
      if (!next || typeof next !== 'object' || !next.metrics || typeof next.metrics !== 'object'
        || !Array.isArray(next.recent_trades)) {
        throw new Error('trade memory response is incomplete');
      }
      setData(next);
      setLoadError(false);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch_();
    const t = setInterval(fetch_, 30_000);
    return () => clearInterval(t);
  }, [fetch_]);

  const m = data?.metrics;
  const th = data?.thresholds;
  const streak = m?.recent_streak;
  const tm = tradeMemoryPresentation(m);
  const noData = !tm.hasMetrics || tm.totalTrades === null || tm.totalTrades === 0;

  const TABS: { id: ActiveTab; label: string }[] = [
    { id: 'session',    label: 'الجلسة' },
    { id: 'direction',  label: 'الاتجاه' },
    { id: 'regime',     label: 'Regime' },
    { id: 'hours',      label: 'ساعات UTC' },
    { id: 'thresholds', label: 'Thresholds' },
  ];

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border-primary/50 shrink-0">
        <Brain className="h-3.5 w-3.5 text-neon-purple" />
        <span className="text-[11px] font-mono font-bold text-text-secondary tracking-wider">TRADE MEMORY</span>
        <span className="text-[8px] font-mono text-text-muted">{tm.totalTrades != null ? `${tm.totalTrades} trades` : '—'}</span>
        <button onClick={fetch_} className="ms-auto p-1 rounded text-text-muted hover:text-neon-purple hover:bg-neon-purple/10 transition-colors">
          <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
        </button>
      </div>
      {loadError && (
        <p role="alert" className="px-3 py-1 text-[9px] font-mono text-neon-gold">
          تعذّر تحديث ذاكرة الصفقات؛ البيانات المعروضة قديمة إن وُجدت.
        </p>
      )}

      {/* Summary strip */}
      {m && !noData && (
        <div className="flex items-center gap-3 px-3 py-1.5 border-b border-border-primary/30 shrink-0 flex-wrap">
          {/* Overall WR */}
          <div className="flex items-center gap-1">
            <span className="text-[8px] font-mono text-text-muted">WR</span>
            <span className={cn('text-[11px] font-mono font-black', tm.winRate != null ? wrColor(tm.winRate) : 'text-text-muted')}>
              {tm.winRate != null ? `${(tm.winRate * 100).toFixed(1)}%` : '—'}
            </span>
          </div>
          <div className="h-3 w-px bg-border-primary/40" />
          {/* Avg PnL */}
          <div className="flex items-center gap-1">
            <span className="text-[8px] font-mono text-text-muted">Avg</span>
            <span className={cn('text-[11px] font-mono font-black', tm.avgPnlPips != null ? pnlColor(tm.avgPnlPips) : 'text-text-muted')}>
              {tm.avgPnlPips != null ? `${tm.avgPnlPips > 0 ? '+' : ''}${tm.avgPnlPips.toFixed(1)}p` : '—'}
            </span>
          </div>
          <div className="h-3 w-px bg-border-primary/40" />
          {/* W/L */}
          <div className="flex items-center gap-1 text-[9px] font-mono">
            <span className="text-neon-green">{tm.totalWins ?? '—'}W</span>
            <span className="text-text-muted">/</span>
            <span className="text-neon-red">{tm.totalLosses ?? '—'}L</span>
          </div>
          {/* Streak */}
          {streak && streak.type !== 'none' && streak.count > 0 && (
            <>
              <div className="h-3 w-px bg-border-primary/40" />
              <div className={cn(
                'flex items-center gap-1 px-1.5 py-0.5 rounded text-[8px] font-mono font-bold',
                streak.type === 'win' ? 'bg-neon-green/10 text-neon-green' : 'bg-neon-red/10 text-neon-red'
              )}>
                {streak.type === 'win' ? <TrendingUp className="h-2.5 w-2.5" /> : <TrendingDown className="h-2.5 w-2.5" />}
                {streak.count} {streak.type === 'win' ? 'رابح' : 'خاسر'}
              </div>
            </>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-0.5 px-2 py-1 border-b border-border-primary/30 shrink-0 overflow-x-auto scrollbar-hide">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'px-2 py-0.5 rounded text-[9px] font-mono whitespace-nowrap transition-all',
              activeTab === tab.id
                ? 'bg-neon-purple/10 text-neon-purple border border-neon-purple/20'
                : 'text-text-muted hover:text-text-secondary'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {loading && (
          <div className="flex items-center justify-center gap-2 py-8 text-text-muted">
            <Brain className="h-4 w-4 animate-pulse text-neon-purple" />
            <span className="text-[10px] font-mono">جارٍ تحميل الذاكرة…</span>
          </div>
        )}

        {!loading && noData && (
          <div className="flex flex-col items-center justify-center gap-2 py-8 text-text-muted">
            <Brain className="h-8 w-8 opacity-20" />
            {loadError ? (
              <span className="text-[10px] font-mono">حالة ذاكرة الصفقات غير متاحة حاليًا</span>
            ) : tm.zeroTrades ? (
              <>
                <span className="text-[10px] font-mono">لا توجد صفقات مسجّلة في الذاكرة</span>
                <span className="text-[9px] font-mono opacity-60">يتعلم النظام بعد كل إغلاق</span>
              </>
            ) : (
              <span className="text-[10px] font-mono">مقاييس الذاكرة غير مكتملة — لا إجماليات قابلة للتحقق</span>
            )}
          </div>
        )}

        {!loading && m && !noData && (
          <>
            {activeTab === 'session' && (
              <BreakdownTable data={m.by_session} label="session" />
            )}
            {activeTab === 'direction' && (
              <BreakdownTable data={m.by_direction} label="direction" />
            )}
            {activeTab === 'regime' && (
              <BreakdownTable data={m.by_regime} label="regime" />
            )}
            {activeTab === 'hours' && (
              <HourGrid
                byHour={m.by_hour}
                goodHours={th?.good_hours ?? []}
                badHours={th?.bad_hours ?? []}
              />
            )}
            {activeTab === 'thresholds' && th && (
              <ThresholdsView t={th} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

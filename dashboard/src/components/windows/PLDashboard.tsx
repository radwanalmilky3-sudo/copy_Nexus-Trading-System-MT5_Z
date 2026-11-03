'use client';

import { useState, useMemo, useEffect } from 'react';
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import NeonCard from '../shared/NeonCard';
import { apiClient } from '@/lib/api-client';

interface PerfSnapshot {
  total_pnl: number;
  win_rate: number;
  profit_factor: number;
  sharpe_ratio: number;
  max_drawdown: number;
  total_trades: number;
  avg_win?: number;
  avg_loss?: number;
}

interface EquityPoint {
  date: string;
  equity: number;
}

interface DailyPLRow {
  date: string;
  pnl: number;
}

type TimeFilter = 'today' | 'week' | 'month' | 'all';

interface KPI {
  label: string;
  value: string;
  color: string;
  glow: string;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const;

function fmtChartLabel(isoOrDate: string): string {
  const d = new Date(isoOrDate);
  if (Number.isNaN(d.getTime())) return String(isoOrDate);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

function sliceByFilter<T>(data: T[], filter: TimeFilter): T[] {
  switch (filter) {
    case 'today':
      return data.slice(-1);
    case 'week':
      return data.slice(-7);
    case 'month':
      return data.slice(-30);
    default:
      return data;
  }
}

function coercePerf(raw: Record<string, unknown>): PerfSnapshot {
  const n = (v: unknown) => {
    const value = typeof v === 'number' ? v : typeof v === 'string' && v.trim() ? Number(v) : NaN;
    if (!Number.isFinite(value)) throw new Error('Performance response is incomplete');
    return value;
  };
  // Derived ratios may be omitted by an older data owner. Blank every KPI over
  // two absent fields would hide the totals that ARE present, so fall back to 0
  // (a real Sharpe/DD of 0 is indistinguishable from "not computed yet", but the
  // panel keeps working and the backend now always returns both fields).
  const optional = (v: unknown) => {
    const value = typeof v === 'number' ? v : typeof v === 'string' && v.trim() ? Number(v) : NaN;
    return Number.isFinite(value) ? value : 0;
  };
  return {
    total_pnl: n(raw.total_pnl),
    win_rate: n(raw.win_rate),
    profit_factor: n(raw.profit_factor),
    sharpe_ratio: optional(raw.sharpe_ratio),
    max_drawdown: optional(raw.max_drawdown),
    total_trades: Math.round(n(raw.total_trades)),
    ...(Number.isFinite(Number(raw.avg_win)) ? { avg_win: Number(raw.avg_win) } : {}),
    ...(Number.isFinite(Number(raw.avg_loss)) ? { avg_loss: Number(raw.avg_loss) } : {}),
  };
}

function NeonTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border-primary/20 bg-bg-primary/95 backdrop-blur-sm px-3 py-2 shadow-lg">
      <p className="text-[10px] font-mono text-text-muted mb-1">{label}</p>
      {payload.map((p: any, i: number) => (
        <p key={i} className="text-xs font-mono font-semibold" style={{ color: p.color }}>
          {p.name}:{' '}
          {typeof p.value === 'number'
            ? p.name === 'P&L' || p.name === 'Cumulative $'
              ? (p.value >= 0 ? '+$' : '-$') + Math.abs(p.value).toFixed(2)
              : p.value.toLocaleString('en-US')
            : p.value}
        </p>
      ))}
    </div>
  );
}

function KPICard({ label, value, color, glow, compact }: KPI & { compact?: boolean }) {
  return (
    <div
      className={`rounded-lg border border-border-primary/10 bg-gradient-card flex flex-col items-center justify-center ${
        compact ? 'p-1.5 gap-0.5 min-h-[52px]' : 'p-3 gap-1'
      }`}
    >
      <span className={`font-mono text-text-muted uppercase tracking-wider text-center leading-tight ${compact ? 'text-[8px]' : 'text-[10px]'}`}>
        {label}
      </span>
      <span className={`font-mono font-bold ${glow} ${compact ? 'text-xs' : 'text-lg'}`} style={{ color }}>
        {value}
      </span>
    </div>
  );
}

export default function PLDashboard({ compact = false, className = '' }: { compact?: boolean; className?: string }) {
  const [filter, setFilter] = useState<TimeFilter>('all');
  const [metrics, setMetrics] = useState<PerfSnapshot | null>(null);
  const [equitySeries, setEquitySeries] = useState<EquityPoint[]>([]);
  const [dailySeries, setDailySeries] = useState<DailyPLRow[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [accountBalance, setAccountBalance] = useState<number | null>(null);
  const [dailyLossPct, setDailyLossPct] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        const [summary, equityPts, dailyPts, riskStatus] = await Promise.all([
          apiClient.getPerformanceSummary(),
          apiClient.getEquityCurvePoints(500),
          apiClient.getDailyPnL(),
          apiClient.getRiskState().catch(() => null),
        ]);
        if (cancelled) return;
        setMetrics(coercePerf(summary as Record<string, unknown>));
        setEquitySeries(
          equityPts.map((row) => ({
            date: fmtChartLabel(row.closed_at),
            equity: Number(row.cumulative_pnl),
          })),
        );
        const ascDaily = [...dailyPts].reverse().map((row) => ({
          date: fmtChartLabel(String(row.date)),
          pnl: Number(row.pnl),
        }));
        setDailySeries(ascDaily);
        const state = (riskStatus?.data as { state?: Record<string, number> } | undefined)?.state;
        if (state) {
          setAccountBalance(typeof state.balance === 'number' ? state.balance : null);
          setDailyLossPct(typeof state.daily_loss_pct === 'number' ? state.daily_loss_pct : null);
        }
        setLoadErr(null);
      } catch (e) {
        if (!cancelled) {
          setLoadErr(e instanceof Error ? e.message : 'Failed to load performance');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    const timer = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const equityData = useMemo(() => sliceByFilter(equitySeries, filter), [equitySeries, filter]);
  const dailyData = useMemo(() => sliceByFilter(dailySeries, filter), [dailySeries, filter]);

  const kpis: KPI[] = [
    {
      label: 'Total P&L',
      value: metrics ?
        (metrics.total_pnl >= 0 ? '+$' : '-$') +
        Math.abs(metrics.total_pnl).toLocaleString('en-US', { minimumFractionDigits: 2 }) : '—',
      color: metrics ? (metrics.total_pnl >= 0 ? '#00ff88' : '#ff2255') : '#606078',
      glow:
        '',
    },
    { label: 'Win Rate', value: metrics ? `${metrics.win_rate.toFixed(1)}%` : '—', color: '#00d4ff', glow: '' },
    { label: 'Profit Factor', value: metrics ? metrics.profit_factor.toFixed(2) : '—', color: '#9945ff', glow: '' },
    { label: 'Sharpe Ratio', value: metrics ? metrics.sharpe_ratio.toFixed(2) : '—', color: '#ffcc00', glow: '' },
    { label: 'Max Drawdown', value: metrics ? `${metrics.max_drawdown.toFixed(1)}%` : '—', color: '#ff2255', glow: '' },
  ];

  const FILTERS: { key: TimeFilter; label: string }[] = [
    { key: 'today', label: 'اليوم' },
    { key: 'week', label: 'هذا الأسبوع' },
    { key: 'month', label: 'هذا الشهر' },
    { key: 'all', label: 'كل الفترات' },
  ];

  const chartsEmpty = equityData.length === 0 && dailyData.length === 0;
  // The gateway substitutes an all-zero performance payload when the data
  // service is unreachable, so all-zero metrics + empty series is ambiguous
  // (genuine empty history vs. unavailable source). Never present it as a
  // confirmed healthy flat record.
  const zerosUnconfirmed =
    !loadErr
    && metrics != null
    && metrics.total_trades === 0
    && metrics.total_pnl === 0
    && equitySeries.length === 0
    && dailySeries.length === 0;

  return (
    <NeonCard
      title={compact ? 'P&L' : 'P&L Dashboard'}
      glow="green"
      noPadding
      icon={
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
        </svg>
      }
      headerRight={
        !compact ? (
          <div className="flex items-center gap-1 flex-wrap justify-end">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={`rounded px-2 py-0.5 text-[10px] font-mono font-semibold transition-all ${
                  f.key === filter
                    ? 'bg-neon-purple/15 text-neon-purple'
                    : 'text-text-muted hover:text-text-secondary'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        ) : (
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as TimeFilter)}
            className="text-[9px] font-mono bg-bg-tertiary border border-border-primary/30 rounded px-1 py-0.5 text-text-secondary"
          >
            {FILTERS.map((f) => (
              <option key={f.key} value={f.key}>{f.label}</option>
            ))}
          </select>
        )
      }
      className={`${compact ? '' : 'h-full'} flex flex-col min-h-0 ${className}`}
    >
      {loadErr && (
        <p className="px-3 pt-2 text-[10px] font-mono text-neon-red">{loadErr}</p>
      )}
      {zerosUnconfirmed && (
        <p className="px-3 pt-2 text-[10px] font-mono text-neon-gold">
          لا توجد صفقات مغلقة مسجّلة — أو أن مصدر الأداء غير متاح حاليًا. القيم الصفري لا تُؤكَّد كسجل فعلي مسطّح.
        </p>
      )}
      {(accountBalance != null || dailyLossPct != null) && (
        <div className="px-3 pt-2 flex flex-wrap gap-3 text-[10px] font-mono text-text-muted border-b border-border-primary/10 pb-2">
          {accountBalance != null && (
            <span>
              الرصيد (Balance): <span className="text-neon-cyan font-semibold" dir="ltr">${accountBalance.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
            </span>
          )}
          {dailyLossPct != null && (
            <span>
              DD اليومي: <span className={dailyLossPct > 2 ? 'text-neon-red' : 'text-neon-green'}>{dailyLossPct.toFixed(2)}%</span>
            </span>
          )}
          <span>صفقات مسجّلة: <span className="text-text-secondary">{metrics ? metrics.total_trades : '—'}</span></span>
        </div>
      )}
      <div
        className={`grid gap-1.5 p-2 border-b border-border-primary/10 ${
          compact ? 'grid-cols-2 sm:grid-cols-3 xl:grid-cols-2' : 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 p-3'
        }`}
      >
        {kpis.map((kpi) => (
          <KPICard key={kpi.label} {...kpi} compact={compact} />
        ))}
      </div>

      {!compact && (
      <div className="flex-1 grid grid-rows-2 gap-0 min-h-0">
        <div className="px-3 pt-3 pb-1 flex flex-col min-h-0">
          <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider mb-1">
            P&amp;L التراكمي (الصفقات المغلقة)
          </span>
          <div className="flex-1 min-h-0 relative">
            {equityData.length === 0 ? (
              <div className="absolute inset-0 flex items-center justify-center text-[11px] font-mono text-text-muted px-4 text-center">
                {loading ? 'جارٍ تحميل بيانات Equity…' : loadErr ? 'بيانات Equity غير متاحة؛ لا يمكن استنتاج تاريخ الصفقات.' : 'لا توجد صفقات مغلقة في DuckDB بعد — يُبنى Equity من عمليات الخروج المسجّلة في قاعدة بيانات البوابة.'}
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={equityData} margin={{ top: 5, right: 5, left: 5, bottom: 0 }}>
                  <defs>
                    <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#00ff88" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#00ff88" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#5a5a72' }} axisLine={{ stroke: '#1a1a2e' }} tickLine={false} />
                  <YAxis tick={{ fontSize: 9, fill: '#5a5a72' }} axisLine={{ stroke: '#1a1a2e' }} tickLine={false} domain={['auto', 'auto']} />
                  <Tooltip content={<NeonTooltip />} />
                  <Area type="monotone" dataKey="equity" name="Cumulative $" stroke="#00ff88" strokeWidth={2} fill="url(#equityGradient)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="px-3 pt-1 pb-3 flex flex-col min-h-0">
          <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider mb-1">Daily P&amp;L</span>
          <div className="flex-1 min-h-0 relative">
            {dailyData.length === 0 ? (
              <div className="absolute inset-0 flex items-center justify-center text-[11px] font-mono text-text-muted px-4 text-center">
                {loading ? 'جارٍ تحميل P&L اليومي…' : loadErr ? 'P&L اليومي غير متاح؛ لا يمكن استنتاج تاريخ الصفقات.' : chartsEmpty
                  ? 'لا يوجد تاريخ صفقات — تُملأ الرسوم عند كتابة الصفقات المغلقة في DuckDB الخاصة بالبوابة.'
                  : 'لا توجد حصص يومية لهذه الفترة.'}
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={dailyData} margin={{ top: 5, right: 5, left: 5, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#5a5a72' }} axisLine={{ stroke: '#1a1a2e' }} tickLine={false} />
                  <YAxis tick={{ fontSize: 9, fill: '#5a5a72' }} axisLine={{ stroke: '#1a1a2e' }} tickLine={false} />
                  <Tooltip content={<NeonTooltip />} />
                  <ReferenceLine y={0} stroke="#5a5a72" strokeDasharray="3 3" />
                  <Bar
                    dataKey="pnl"
                    name="P&L"
                    radius={[2, 2, 0, 0]}
                    fill="#00ff88"
                    shape={(props: any) => {
                      const { x, y, width, height, payload } = props;
                      const fill = payload.pnl >= 0 ? '#00ff88' : '#ff2255';
                      return <rect x={x} y={y} width={width} height={height} rx={2} fill={fill} />;
                    }}
                  />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>
      )}
    </NeonCard>
  );
}

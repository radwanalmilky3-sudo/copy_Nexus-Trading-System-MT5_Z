'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  History,
  Filter,
  Download,
  ArrowUpRight,
  ArrowDownRight,
  Calendar,
  Search,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { getAuthHeaders } from '@/lib/api-client';
import { hasCompleteTradeStats } from '@/lib/trade-stats-status';
import { buildTradeCsv } from '@/lib/trade-csv';

const API = process.env.NEXT_PUBLIC_API_URL || '';

type FilterPeriod = '1d' | '1w' | '1m' | '3m' | 'all';

const PERIOD_OPTIONS: { value: FilterPeriod; label: string }[] = [
  { value: '1d', label: '24H' },
  { value: '1w', label: '1W' },
  { value: '1m', label: '1M' },
  { value: '3m', label: '3M' },
  { value: 'all', label: 'الكل' },
];

function periodToSince(period: FilterPeriod): string | null {
  if (period === 'all') return null;
  const now = new Date();
  const map: Record<string, number> = { '1d': 1, '1w': 7, '1m': 30, '3m': 90 };
  now.setDate(now.getDate() - (map[period] ?? 7));
  return now.toISOString();
}

interface TradeRow {
  id?: string;
  symbol?: string;
  side?: string;
  size?: number;
  entry_price?: number;
  exit_price?: number;
  pnl_usd?: number;
  pnl_pips?: number;
  rr_ratio?: number;
  duration_s?: number;
  session?: string;
  agent_id?: string;
  comment?: string;
  opened_at?: string;
  closed_at?: string;
}

interface TradeStats {
  total_trades: number;
  winning: number;
  losing: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
  avg_rr: number;
  best_trade: number;
  worst_trade: number;
  avg_duration_s: number;
}

function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatCurrency(v: number): string {
  const sign = v >= 0 ? '+' : '';
  return `${sign}$${v.toFixed(2)}`;
}

function formatPips(v: number): string {
  return v.toFixed(1);
}

export default function HistoryPage() {
  const [period, setPeriod] = useState<FilterPeriod>('1w');
  const [search, setSearch] = useState('');
  const [trades, setTrades] = useState<TradeRow[]>([]);
  const [stats, setStats] = useState<TradeStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 50;

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const since = periodToSince(period);
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (since) params.set('since', since);
      if (search) params.set('symbol', search.toUpperCase());

      const [tradesRes, statsRes] = await Promise.all([
        fetch(`${API}/api/trades?${params}`, { headers: getAuthHeaders() }).catch(() => null),
        fetch(`${API}/api/trades/stats?${params}`, { headers: getAuthHeaders() }).catch(() => null),
      ]);

      if (!tradesRes?.ok || !statsRes?.ok) {
        setLoadError('تعذر تحديث سجل التداول. تحقق من خدمة البيانات ثم أعد المحاولة.');
        return;
      }

      const [tradeData, statsData] = await Promise.all([tradesRes.json(), statsRes.json()]);
      if (!Array.isArray(tradeData?.trades) || !Number.isFinite(tradeData?.total) ||
          !hasCompleteTradeStats(statsData)) {
        throw new Error('Invalid trade history response');
      }
      setTrades(tradeData.trades ?? []);
      setTotal(tradeData.total ?? 0);
      setStats(statsData);
      setLoadError(null);
    } catch {
      setLoadError('تعذر تحديث سجل التداول. تحقق من خدمة البيانات ثم أعد المحاولة.');
    } finally {
      setLoading(false);
    }
  }, [period, search, page]);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 30_000);
    return () => clearInterval(id);
  }, [fetchData]);

  useEffect(() => { setPage(1); }, [period, search]);

  const totalPages = Math.ceil(total / pageSize);
  const exportRangeLabel = trades.length
    ? `(${(page - 1) * pageSize + 1}–${(page - 1) * pageSize + trades.length} من ${total})`
    : '(0 صف)';

  const exportCSV = () => {
    const headers = ['Time', 'Symbol', 'Side', 'Volume', 'Entry', 'Exit', 'P&L $', 'Pips', 'R:R', 'Duration', 'Session', 'Agent'];
    const rows = trades.map((t) => [
      t.closed_at || t.opened_at || '', t.symbol, t.side, t.size,
      t.entry_price, t.exit_price, t.pnl_usd?.toFixed(2), t.pnl_pips?.toFixed(1),
      t.rr_ratio?.toFixed(2), formatDuration(t.duration_s ?? 0), t.session, t.agent_id || t.comment,
    ]);
    const csv = buildTradeCsv(headers, rows);
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'trade_history.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div dir="rtl" className="p-2 sm:p-4 space-y-3 sm:space-y-4 animate-fade-in w-full max-w-[1800px] mx-auto">
      <div dir="rtl" className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <History className="h-5 w-5 text-neon-purple" />
          <h1 className="text-lg font-bold text-text-primary">سجل التداول (Trade History)</h1>
          {loading && <RefreshCw className="h-3.5 w-3.5 animate-spin text-text-muted" />}
        </div>
        <button
          onClick={exportCSV}
          disabled={trades.length === 0}
          title={`تصدير الصفحة المعروضة حاليًا (${trades.length} من ${total} صفًا مُصفّى)، وليس كامل النتائج`}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] text-text-secondary hover:text-text-primary bg-bg-card border border-border-primary hover:border-border-accent transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Download className="h-3.5 w-3.5" />
          تصدير CSV <span dir="ltr">{exportRangeLabel}</span>
        </button>
      </div>

      <div dir="rtl" className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-0.5 bg-bg-card rounded-lg p-0.5 border border-border-primary/20">
          {PERIOD_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setPeriod(opt.value)}
              className={cn(
                'px-2.5 py-1 text-[10px] font-mono font-medium rounded transition-all',
                period === opt.value
                  ? 'bg-neon-purple/15 text-neon-purple'
                  : 'text-text-muted hover:text-text-secondary'
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-text-muted" />
          <input
            type="text"
            placeholder="تصفية حسب Symbol..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            dir="ltr"
            className="w-full pl-8 pr-3 py-1.5 text-[11px] font-mono bg-bg-card border border-border-primary/20 rounded-lg text-text-primary placeholder:text-text-muted focus:outline-none focus:border-neon-purple/40"
          />
        </div>
      </div>

      {loadError && (
        <div role="alert" className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 px-3 py-2 text-[11px] text-yellow-300">
          {loadError} يتم الاحتفاظ بالبيانات المُحمّلة سابقًا إن وجدت.
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {[
          { label: 'إجمالي trades', value: stats ? String(stats.total_trades) : '—', color: 'text-text-primary' },
          { label: 'Win Rate', value: stats?.total_trades ? `${stats.win_rate.toFixed(1)}%` : '—', color: stats ? (stats.win_rate >= 50 ? 'text-neon-green' : 'text-neon-red') : 'text-text-muted' },
          { label: 'صافي P&L', value: stats ? formatCurrency(stats.total_pnl) : '—', color: stats ? (stats.total_pnl >= 0 ? 'text-neon-green' : 'text-neon-red') : 'text-text-muted' },
          { label: 'متوسط المدة', value: stats?.total_trades ? formatDuration(stats.avg_duration_s) : '—', color: 'text-neon-cyan' },
        ].map((stat) => (
          <div key={stat.label} className="rounded-lg border border-border-primary/15 bg-bg-secondary/40 px-3 py-2">
            <p className="text-[9px] text-text-muted uppercase font-mono">{stat.label}</p>
            <p dir="ltr" className={cn('text-sm font-bold font-mono', stat.color)}>{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Extended stats */}
      {stats && stats.total_trades > 0 && (
        <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
          {[
            { label: 'رابحة', value: String(stats.winning), color: 'text-neon-green' },
            { label: 'خاسرة', value: String(stats.losing), color: 'text-neon-red' },
            { label: 'متوسط P&L', value: formatCurrency(stats.avg_pnl), color: stats.avg_pnl >= 0 ? 'text-neon-green' : 'text-neon-red' },
            { label: 'متوسط RR', value: stats.avg_rr.toFixed(2), color: stats.avg_rr >= 1 ? 'text-neon-green' : 'text-neon-red' },
            { label: 'أفضل trade', value: formatCurrency(stats.best_trade), color: 'text-neon-green' },
            { label: 'أضعف trade', value: formatCurrency(stats.worst_trade), color: 'text-neon-red' },
          ].map((stat) => (
            <div key={stat.label} className="rounded-lg border border-border-primary/10 bg-bg-secondary/30 px-2.5 py-1.5">
              <p className="text-[8px] text-text-muted uppercase font-mono">{stat.label}</p>
              <p dir="ltr" className={cn('text-[11px] font-bold font-mono', stat.color)}>{stat.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Trade table */}
      <div className="rounded-xl border border-border-primary/15 bg-bg-primary overflow-hidden">
        <div className="overflow-x-auto scrollbar-hide">
          <table className="w-full table-fixed min-w-[900px]">
            <colgroup>
              <col className="w-[130px]" />
              <col className="w-[72px]" />
              <col className="w-[58px]" />
              <col className="w-[52px]" />
              <col className="w-[82px]" />
              <col className="w-[82px]" />
              <col className="w-[80px]" />
              <col className="w-[52px]" />
              <col className="w-[44px]" />
              <col className="w-[56px]" />
              <col className="w-[80px]" />
            </colgroup>
            <thead>
              <tr className="border-b border-border-primary/15">
                {['الوقت', 'Symbol', 'الجهة', 'الحجم', 'الدخول', 'الخروج', 'P&L', 'Pips', 'R:R', 'المدة', 'المصدر'].map(
                  (col) => (
                    <th
                      key={col}
                      className="px-2 py-1.5 text-start text-[8px] font-mono font-semibold text-text-muted uppercase tracking-wider"
                    >
                      {col}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={11} className="px-4 py-12 text-center text-[11px] text-text-muted">
                    {loading ? (
                      <div className="flex items-center justify-center gap-2">
                        <RefreshCw className="h-4 w-4 animate-spin" />
                        جارٍ تحميل trades...
                      </div>
                    ) : loadError ? (
                      <>سجل التداول غير متاح. الحالة الفارغة المعروضة لا تؤكد عدم وجود trades.</>
                    ) : (
                      <>
                        <Calendar className="h-6 w-6 mx-auto mb-2 opacity-30" />
                        لا توجد trades مسجّلة في هذه الفترة. ابدأ جلسة تداول لعرض السجل.
                      </>
                    )}
                  </td>
                </tr>
              ) : (
                trades.map((trade, i) => {
                  const isBuy = (trade.side || '').toUpperCase() === 'BUY';
                  const pnl = trade.pnl_usd ?? 0;
                  return (
                    <tr
                      key={trade.id || i}
                      className="border-b border-border-primary/5 hover:bg-bg-secondary/30 transition-colors"
                    >
                      <td dir="ltr" className="px-2 py-1.5 text-[9px] font-mono text-text-muted truncate">
                        {trade.closed_at
                          ? new Date(trade.closed_at).toLocaleString('en-US', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' })
                          : trade.opened_at
                          ? new Date(trade.opened_at).toLocaleString('en-US', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' })
                          : '—'}
                      </td>
                      <td dir="ltr" className="px-2 py-1.5 text-[10px] font-semibold text-text-primary font-mono">
                        {trade.symbol}
                      </td>
                      <td className="px-2 py-1.5">
                        <span
                          dir="ltr"
                          className={cn(
                            'inline-flex items-center gap-0.5 text-[9px] font-mono font-bold',
                            isBuy ? 'text-neon-green' : 'text-neon-red'
                          )}
                        >
                          {isBuy ? <ArrowUpRight className="h-2.5 w-2.5" /> : <ArrowDownRight className="h-2.5 w-2.5" />}
                          {trade.side?.toUpperCase()}
                        </span>
                      </td>
                      <td dir="ltr" className="px-2 py-1.5 text-[9px] font-mono text-text-secondary tabular-nums">
                        {trade.size ?? '—'}
                      </td>
                      <td dir="ltr" className="px-2 py-1.5 text-[9px] font-mono text-text-secondary tabular-nums">
                        {trade.entry_price?.toFixed(2) ?? '—'}
                      </td>
                      <td dir="ltr" className="px-2 py-1.5 text-[9px] font-mono text-text-secondary tabular-nums">
                        {trade.exit_price?.toFixed(2) ?? '—'}
                      </td>
                      <td dir="ltr" className={cn('px-2 py-1.5 text-[10px] font-mono font-bold tabular-nums', pnl >= 0 ? 'text-neon-green' : 'text-neon-red')}>
                        {formatCurrency(pnl)}
                      </td>
                      <td dir="ltr" className="px-2 py-1.5 text-[9px] font-mono text-text-secondary tabular-nums">
                        {trade.pnl_pips != null ? formatPips(trade.pnl_pips) : '—'}
                      </td>
                      <td dir="ltr" className={cn('px-2 py-1.5 text-[9px] font-mono tabular-nums', (trade.rr_ratio ?? 0) >= 1 ? 'text-neon-cyan' : 'text-text-muted')}>
                        {trade.rr_ratio != null ? trade.rr_ratio.toFixed(1) : '—'}
                      </td>
                      <td dir="ltr" className="px-2 py-1.5 text-[9px] font-mono text-text-muted">
                        {formatDuration(trade.duration_s ?? 0)}
                      </td>
                      <td className="px-2 py-1.5 text-[9px] font-mono text-neon-purple truncate">
                        {trade.agent_id || trade.comment || '—'}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-3 py-2 border-t border-border-primary/10">
            <span className="text-[10px] text-text-muted font-mono">
              <span dir="ltr">{total} trades</span> · صفحة <span dir="ltr">{page}/{totalPages}</span>
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="p-1 rounded text-text-muted hover:text-text-secondary disabled:opacity-30"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="p-1 rounded text-text-muted hover:text-text-secondary disabled:opacity-30"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

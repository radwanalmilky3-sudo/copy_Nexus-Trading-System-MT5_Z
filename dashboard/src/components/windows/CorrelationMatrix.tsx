'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { GitCompare, AlertTriangle, RefreshCw, Activity } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getAuthHeaders } from '@/lib/api-client';
import {
  availableWindowKeys,
  corrCellPresentation,
  lagPairPresentation,
  correlationBasisNote,
  correlationDisclaimer,
  type CorrCellView,
  type CorrWindowPayload,
  type LagPairLike,
} from '@/lib/correlation-presentation';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000';

interface CorrMatrix { [asset: string]: { [asset: string]: number | null } }

interface Divergence {
  pair: string;
  corr_7d: number;
  corr_30d: number;
  shift: number;
  severity: 'HIGH' | 'MEDIUM';
  description: string;
}

interface CorrData {
  assets: string[];
  matrices: { '7d': CorrMatrix; '30d': CorrMatrix };
  windows?: Record<string, CorrWindowPayload>;
  lag_signals?: LagPairLike[];
  basis?: string | null;
  disclaimer?: string | null;
  available?: boolean;
  reason?: string;
  divergences: Divergence[];
  updated_at: string | null;
  error?: string;
}

const ASSET_COLORS: Record<string, string> = {
  XAUUSD: 'text-yellow-400',
  BTCUSD: 'text-orange-400',
  OIL:    'text-cyan-400',
  SPX:    'text-neon-green',
};

function corrColor(cell: CorrCellView, raw: number | null): string {
  if (cell.tone !== 'value' || raw === null) return 'bg-bg-tertiary/40 text-text-muted';
  if (raw >= 0.7)  return 'bg-neon-green/30 text-neon-green';
  if (raw >= 0.4)  return 'bg-neon-green/15 text-neon-green/80';
  if (raw >= 0.15) return 'bg-neon-green/8 text-neon-green/60';
  if (raw <= -0.7) return 'bg-neon-red/30 text-neon-red';
  if (raw <= -0.4) return 'bg-neon-red/15 text-neon-red/80';
  if (raw <= -0.15) return 'bg-neon-red/8 text-neon-red/60';
  return 'bg-bg-tertiary/30 text-text-muted';
}

function CorrCell({ val, isDiag, cell }: { val: number | null; isDiag: boolean; cell: CorrCellView }) {
  if (isDiag) {
    return (
      <div className="flex items-center justify-center h-full w-full bg-bg-tertiary/20 rounded">
        <span className="text-[10px] font-mono text-text-muted">—</span>
      </div>
    );
  }
  return (
    <div
      title={cell.title}
      className={cn('flex items-center justify-center h-full w-full rounded text-[10px] font-mono font-bold', corrColor(cell, val))}
    >
      {cell.text}
    </div>
  );
}

export default function CorrelationMatrix() {
  const [data, setData] = useState<CorrData | null>(null);
  const [winKey, setWinKey] = useState<string>('20');
  const [age, setAge] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/intelligence/correlation`, { headers: getAuthHeaders() });
      if (!res.ok) throw new Error('correlation unavailable');
      setData(await res.json());
      setLoadError(false);
    } catch { setLoadError(true); }
  }, []);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, 30_000);
    return () => clearInterval(t);
  }, [fetchData]);

  useEffect(() => {
    if (!data?.updated_at) return;
    const update = () => {
      const diff = Math.floor((Date.now() - new Date(data.updated_at!).getTime()) / 60000);
      setAge(diff < 1 ? 'الآن' : diff < 60 ? `${diff}m` : `${Math.floor(diff / 60)}h`);
    };
    update();
    const t = setInterval(update, 30_000);
    return () => clearInterval(t);
  }, [data?.updated_at]);

  const handleRefresh = async () => {
    setLoading(true);
    await fetchData();
    setLoading(false);
  };

  const windowKeys = availableWindowKeys(data);
  const activeKey = windowKeys.includes(winKey) ? winKey : (windowKeys[0] ?? '');
  const assets = data?.assets ?? ['XAUUSD', 'BTCUSD', 'OIL', 'SPX'];
  const winPayload = data?.windows?.[activeKey];
  const legacyMatrix = data?.matrices?.[activeKey as '7d' | '30d'];
  const matrix = winPayload?.matrix ?? legacyMatrix ?? {};
  const divs = data?.divergences ?? [];
  const lags = data?.lag_signals ?? [];

  const cellView = (row: string, col: string): { val: number | null; cell: CorrCellView } => {
    const val = matrix[row]?.[col] ?? null;
    const stats = winPayload?.pairs?.[`${row}/${col}`] ?? winPayload?.pairs?.[`${col}/${row}`];
    if (stats) return { val: stats.corr, cell: corrCellPresentation(stats, stats.corr) };
    if (val !== null) {
      return {
        val,
        cell: { text: (val >= 0 ? '+' : '') + val.toFixed(2), tone: 'value', title: 'نافذة بلا بيانات عيّنات' },
      };
    }
    return { val: null, cell: corrCellPresentation(undefined, null) };
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border-primary/50 shrink-0">
        <GitCompare className="h-3.5 w-3.5 text-neon-purple" />
        <span className="text-[11px] font-mono font-bold text-text-secondary tracking-wider">
          ارتباط متعدد الأصول (Multi-Asset)
        </span>

        {/* Window toggle — returns-based windows 20/60/120 (legacy 7d/30d fallback) */}
        <div className="ms-3 flex gap-0.5">
          {windowKeys.map(w => (
            <button
              key={w}
              onClick={() => setWinKey(w)}
              className={cn(
                'px-2 py-0.5 rounded text-[9px] font-mono font-bold transition-all',
                activeKey === w
                  ? 'bg-neon-purple/20 text-neon-purple border border-neon-purple/30'
                  : 'text-text-muted hover:text-text-secondary'
              )}
            >
              {w}
            </button>
          ))}
        </div>

        <div className="ms-auto flex items-center gap-2">
          {age && <span className="text-[9px] font-mono text-text-muted">{age}</span>}
          <button
            onClick={handleRefresh}
            className="text-text-muted hover:text-neon-purple transition-colors"
          >
            <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
          </button>
        </div>
      </div>

      {loadError && <p role="alert" className="px-3 pt-2 text-[9px] text-neon-gold">تعذر تحديث مصفوفة الارتباط؛ المعروض قديم إن وُجد.</p>}
      {!data ? <div role="status" className="flex-1 flex items-center justify-center px-4 text-center text-[10px] font-mono text-text-muted">
        {loadError ? 'بيانات الارتباط غير متاحة؛ لم تُنشأ مصفوفة افتراضية.' : 'جارٍ تحميل بيانات الارتباط…'}
      </div> : <div className="flex-1 min-h-0 overflow-auto px-3 py-2 flex flex-col gap-3">
        {!data.updated_at && (
          <p role="status" className="text-[9px] text-neon-gold">
            {data.available === false
              ? 'لا توجد لقطة ارتباط مكتملة بعد — الخلايا الفارغة قيم غير متاحة، وليس ارتباطًا صفرًا.'
              : 'لا توجد لقطة ارتباط مكتملة بعد — الخلايا الفارغة قيم غير متاحة، وليس ارتباطًا صفرًا.'}
          </p>
        )}
        {data.basis && <p className="text-[8px] font-mono text-text-muted">{correlationBasisNote()}</p>}
        {/* Correlation heatmap */}
        <div className="flex gap-2">
          {/* Row labels column */}
          <div className="flex flex-col gap-1 shrink-0">
            <div className="h-6" /> {/* spacer for column headers */}
            {assets.map(a => (
              <div key={a} className="flex items-center h-7">
                <span className={cn('text-[10px] font-mono font-bold w-14 text-right pr-2', ASSET_COLORS[a] ?? 'text-text-secondary')}>
                  {a}
                </span>
              </div>
            ))}
          </div>

          {/* Grid */}
          <div className="flex-1 min-w-0">
            {/* Column headers */}
            <div className="flex gap-1 mb-1">
              {assets.map(a => (
                <div key={a} className="flex-1 flex items-center justify-center h-6">
                  <span className={cn('text-[9px] font-mono font-bold', ASSET_COLORS[a] ?? 'text-text-secondary')}>
                    {a}
                  </span>
                </div>
              ))}
            </div>

            {/* Matrix rows */}
            <div className="flex flex-col gap-1">
              {assets.map(rowAsset => (
                <div key={rowAsset} className="flex gap-1">
                  {assets.map(colAsset => {
                    const isDiag = rowAsset === colAsset;
                    const { val, cell } = cellView(rowAsset, colAsset);
                    return (
                      <div key={colAsset} className="flex-1 h-7 min-w-0">
                        <CorrCell val={val} isDiag={isDiag} cell={cell} />
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-[8px] font-mono text-text-muted">مقياس Pearson (العوائد):</span>
          {[
            { label: '≥+0.7 ارتباط قوي+', cls: 'bg-neon-green/30 text-neon-green' },
            { label: '+0.4/+0.7 متوسط+', cls: 'bg-neon-green/15 text-neon-green/80' },
            { label: '±0.15 محايد', cls: 'bg-bg-tertiary/30 text-text-muted' },
            { label: '-0.4/-0.7 متوسط−', cls: 'bg-neon-red/15 text-neon-red/80' },
            { label: '≤-0.7 ارتباط قوي−', cls: 'bg-neon-red/30 text-neon-red' },
            { label: '— غير متاح/ثابت', cls: 'bg-bg-tertiary/40 text-text-muted' },
          ].map(({ label, cls }) => (
            <div key={label} className={cn('px-1.5 py-0.5 rounded text-[8px] font-mono', cls)}>
              {label}
            </div>
          ))}
        </div>

        {/* Lag signals (context only, never a prediction) */}
        {lags.length > 0 && (
          <div className="border-t border-border-primary/30 pt-2">
            <div className="flex items-center gap-1 mb-1.5 text-[9px] font-mono text-text-muted tracking-wider">
              <Activity className="h-2.5 w-2.5 text-neon-purple" />
              إشارات Lag (عوائد متزامنة)
            </div>
            <div className="flex flex-col gap-0.5">
              {lags.map((p, i) => {
                const view = lagPairPresentation(p);
                return (
                  <div key={`${p.pair}-${i}`} className="flex items-center gap-2 px-2 py-0.5 text-[9px] font-mono">
                    <span className={cn(
                      'shrink-0 w-24 font-bold',
                      view.tone === 'lead' ? 'text-neon-purple' : view.tone === 'sync' ? 'text-text-secondary' : 'text-text-muted'
                    )}>
                      {p.pair}
                    </span>
                    <span className={cn(
                      'flex-1',
                      view.tone === 'unavailable' ? 'text-text-muted' : 'text-text-secondary'
                    )}>
                      {view.label}
                      {p.insufficient_data ? ' — بيانات غير كافية' : ''}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Divergences */}
        {divs.length > 0 && (
          <div className="border-t border-border-primary/30 pt-2">
            <div className="flex items-center gap-1 mb-1.5 text-[9px] font-mono text-text-muted tracking-wider">
              <AlertTriangle className="h-2.5 w-2.5 text-yellow-400" />
              التباعدات المكتشفة (7d مقابل 30d)
            </div>
            <div className="flex flex-col gap-1">
              {divs.slice(0, 4).map((d, i) => (
                <div
                  key={i}
                  className={cn(
                    'flex items-center gap-2 px-2 py-1 rounded text-[9px] font-mono',
                    d.severity === 'HIGH' ? 'bg-neon-red/8 border border-neon-red/20' : 'bg-yellow-400/8 border border-yellow-400/20'
                  )}
                >
                  <span className={cn('font-bold shrink-0 w-20', d.severity === 'HIGH' ? 'text-neon-red' : 'text-yellow-400')}>
                    {d.pair}
                  </span>
                  <span className="text-text-muted flex-1">{d.description}</span>
                  <span className={cn('shrink-0 font-bold', d.severity === 'HIGH' ? 'text-neon-red' : 'text-yellow-400')}>
                    Δ{d.shift.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {data.updated_at && (
          <p className="text-[8px] font-mono text-text-muted border-t border-border-primary/30 pt-1.5">
            {data.disclaimer ?? correlationDisclaimer()}
          </p>
        )}
      </div>
      }
    </div>
  );
}

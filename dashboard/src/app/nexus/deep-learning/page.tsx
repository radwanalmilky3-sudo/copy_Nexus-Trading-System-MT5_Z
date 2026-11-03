'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  Network,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Target,
  BarChart3,
  Zap,
  AlertCircle,
  CheckCircle2,
  Play,
  Layers,
  Brain,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { apiClient, getAuthHeaders } from '@/lib/api-client';

const API = process.env.NEXT_PUBLIC_API_URL || '';

interface ModelPerformance {
  model_type: string;
  model_name: string;
  is_fitted: boolean;
  total_trades: number;
  win_rate: number;
  profit_factor: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown: number;
  total_return: number;
  avg_rr: number;
  avg_win_pips: number;
  avg_loss_pips: number;
  expectancy: number;
  train_samples: number;
  last_trained: string;
  training_time_sec: number;
  equity_curve: number[];
  recent_signals: Array<{
    direction: string;
    confidence: number;
    sl_pips: number;
    tp_pips: number;
    symbol: string;
    timestamp: string;
    reasoning: string;
  }>;
}

function MetricCard({
  label,
  value,
  format = 'number',
  positive,
}: {
  label: string;
  value: number;
  format?: 'number' | 'pct' | 'ratio';
  positive?: boolean;
}) {
  const formatted =
    format === 'pct'
      ? `${(value * 100).toFixed(1)}%`
      : format === 'ratio'
      ? value.toFixed(2)
      : value.toFixed(4);

  return (
    <div className="flex flex-col gap-1 p-3 rounded-lg bg-bg-card border border-border-primary/20">
      <span className="text-[10px] text-text-muted font-mono uppercase">{label}</span>
      <span
        dir="ltr"
        className={cn(
          'text-lg font-mono font-bold',
          positive === undefined ? 'text-text-primary' : positive ? 'text-neon-green' : 'text-neon-red'
        )}
      >
        {formatted}
      </span>
    </div>
  );
}

function MiniEquityChart({ data, color = '#bf40ff' }: { data: number[]; color?: string }) {
  if (data.length < 2) return <div className="text-[10px] text-text-muted">لا توجد بيانات equity</div>;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 400;
  const h = 100;
  const points = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * h}`);

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-24">
      <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
      <polyline points={`0,${h} ${points.join(' ')} ${w},${h}`} fill={`${color}15`} stroke="none" />
    </svg>
  );
}

export default function DeepLearningPage() {
  const [perf, setPerf] = useState<ModelPerformance | null>(null);
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [training, setTraining] = useState(false);
  const [error, setError] = useState('');

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/ml/traders/status`, { headers: getAuthHeaders() });
      if (res.ok) {
        const data = await res.json();
        if (typeof data?.dl?.performance?.is_fitted !== 'boolean') throw new Error('Incomplete DL status response');
        setPerf(data.dl?.performance || null);
        setStatusLoaded(true);
        setError('');
      } else {
        setError('الخدمة غير متاحة');
      }
    } catch {
      setError('تعذّر الاتصال');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, 10_000);
    return () => clearInterval(id);
  }, [fetchStatus]);

  const handleTrain = async () => {
    setTraining(true);
    try {
      await apiClient.trainModels(['dl']);
    } catch {
      setError('فشل طلب التدريب. لم يتغيّر حالة الـ model.');
      setTraining(false);
      return;
    }
    setTimeout(() => { setTraining(false); fetchStatus(); }, 3000);
  };

  return (
    <div dir="rtl" className="p-2 sm:p-4 w-full max-w-[1800px] mx-auto space-y-3 sm:space-y-4">
      {/* Header */}
      <div dir="rtl" className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <Network className="h-5 w-5 text-neon-purple" />
          <h1 className="text-sm font-bold text-text-primary">متداول التعلّم العميق (Deep Learning Trader)</h1>
        </div>
        <span className="text-[10px] font-mono text-text-muted bg-bg-card px-2 py-0.5 rounded border border-border-primary/20">
          Transformer Encoder | Multi-Head Attention | SL/TP Heads
        </span>
        <div className="flex-1" />
        {!statusLoaded ? (
          <span className="flex items-center gap-1 text-[10px] text-neon-gold"><AlertCircle className="h-3 w-3" /> {error ? 'الحالة غير متاحة' : loading ? 'جارٍ فحص الحالة…' : 'الحالة غير متاحة'}</span>
        ) : error ? (
          <span className="flex items-center gap-1 text-[10px] text-neon-gold"><AlertCircle className="h-3 w-3" /> آخر حالة معروفة (قديمة)</span>
        ) : perf?.is_fitted ? (
          <span className="flex items-center gap-1 text-[10px] text-neon-green">
            <CheckCircle2 className="h-3 w-3" /> مُدرَّب (Trained)
          </span>
        ) : (
          <span className="flex items-center gap-1 text-[10px] text-neon-gold">
            <AlertCircle className="h-3 w-3" /> غير مُدرَّب (Not Trained)
          </span>
        )}
        <button
          onClick={handleTrain}
          disabled={training || !statusLoaded || Boolean(error)}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium border transition-all',
            training
              ? 'border-border-primary text-text-muted cursor-not-allowed'
              : 'border-neon-purple/30 text-neon-purple bg-neon-purple/5 hover:bg-neon-purple/10'
          )}
        >
          {training ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
          {training ? 'جارٍ التدريب…' : 'تدريب الـ model'}
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-neon-red/10 border border-neon-red/20 text-[11px] text-neon-red">
          <AlertCircle className="h-3 w-3" /> {error}
        </div>
      )}

      {perf && (
        <>
          {/* Architecture */}
          <div className="rounded-xl border border-neon-purple/20 bg-bg-primary p-4">
            <div className="flex items-center gap-2 mb-3">
              <Layers className="h-4 w-4 text-neon-purple" />
              <span className="text-[11px] font-mono font-semibold text-text-secondary">البنية (Architecture)</span>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {[
                { label: 'Input Projection', detail: `${perf.train_samples > 0 ? 'نشط' : 'قيد الانتظار'}` },
                { label: 'Positional Encoding', detail: 'Sinusoidal' },
                { label: 'Transformer Encoder', detail: '3 طبقات' },
                { label: 'Multi-Head Attention', detail: '4 رؤوس' },
                { label: 'Classification Head', detail: '3 فئات' },
                { label: 'SL Regression', detail: 'Softplus' },
                { label: 'TP Regression', detail: 'Softplus' },
              ].map((block, i) => (
                <React.Fragment key={i}>
                  <div className="flex flex-col items-center px-3 py-2 rounded-lg bg-bg-card border border-neon-purple/10">
                    <span className="text-[10px] font-mono font-bold text-neon-purple">{block.label}</span>
                    <span className="text-[9px] text-text-muted">{block.detail}</span>
                  </div>
                  {i < 6 && <span className="text-neon-purple/40 text-xs">&rarr;</span>}
                </React.Fragment>
              ))}
            </div>
          </div>

          {/* Metrics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
            <MetricCard label="Win Rate" value={perf.win_rate} format="pct" positive={perf.win_rate > 0.5} />
            <MetricCard label="Profit Factor" value={perf.profit_factor} format="ratio" positive={perf.profit_factor > 1} />
            <MetricCard label="Sharpe" value={perf.sharpe_ratio} format="ratio" positive={perf.sharpe_ratio > 0} />
            <MetricCard label="Max DD" value={perf.max_drawdown} format="pct" positive={perf.max_drawdown > -0.1} />
            <MetricCard label="Avg RR" value={perf.avg_rr} format="ratio" positive={perf.avg_rr > 1} />
            <MetricCard label="Trades" value={perf.total_trades} />
          </div>

          {/* Equity Curve */}
          <div className="rounded-xl border border-border-primary/20 bg-bg-primary p-3">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp className="h-3.5 w-3.5 text-neon-purple" />
              <span className="text-[11px] font-mono font-semibold text-text-secondary">منحنى Equity</span>
              <span className="text-[10px] text-text-muted me-auto" dir="rtl">
                العائد: <span dir="ltr">{(perf.total_return * 100).toFixed(2)}%</span>
              </span>
            </div>
            <MiniEquityChart data={perf.equity_curve} />
          </div>

          {/* Training Info + Signals */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="rounded-xl border border-border-primary/20 bg-bg-primary p-3">
              <div className="flex items-center gap-2 mb-2">
                <Brain className="h-3.5 w-3.5 text-neon-purple" />
                <span className="text-[11px] font-mono font-semibold text-text-secondary">تفاصيل التدريب (Training Details)</span>
              </div>
              <div className="space-y-1.5 text-[11px] font-mono">
                <div className="flex justify-between"><span className="text-text-muted">التسلسلات (Sequences)</span><span dir="ltr" className="text-neon-purple">{perf.train_samples.toLocaleString('en-US')}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">طول التسلسل</span><span dir="ltr" className="text-text-primary">30 bars</span></div>
                <div className="flex justify-between"><span className="text-text-muted">المحسّن (Optimizer)</span><span dir="ltr" className="text-text-primary">AdamW (cosine LR)</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Loss</span><span dir="ltr" className="text-text-primary">CE + SmoothL1</span></div>
                <div className="flex justify-between"><span className="text-text-muted">وقت التدريب</span><span dir="ltr" className="text-text-primary">{perf.training_time_sec.toFixed(1)}s</span></div>
                <div className="flex justify-between"><span className="text-text-muted">متوسط الربح</span><span dir="ltr" className="text-neon-green">{perf.avg_win_pips.toFixed(1)} pips</span></div>
                <div className="flex justify-between"><span className="text-text-muted">متوسط الخسارة</span><span dir="ltr" className="text-neon-red">{perf.avg_loss_pips.toFixed(1)} pips</span></div>
                <div className="flex justify-between"><span className="text-text-muted">آخر تدريب</span><span dir="ltr" className="text-text-secondary">{perf.last_trained ? new Date(perf.last_trained).toLocaleString('en-US') : 'لم يُدرَّب'}</span></div>
              </div>
            </div>

            <div className="rounded-xl border border-border-primary/20 bg-bg-primary p-3">
              <div className="flex items-center gap-2 mb-2">
                <Zap className="h-3.5 w-3.5 text-neon-gold" />
                <span className="text-[11px] font-mono font-semibold text-text-secondary">الإشارات الحديثة (Recent Signals)</span>
              </div>
              <div className="max-h-[240px] overflow-y-auto scrollbar-hide space-y-1">
                {perf.recent_signals.length === 0 ? (
                  <div className="text-[10px] text-text-muted text-center py-4">لا توجد إشارات بعد</div>
                ) : (
                  perf.recent_signals.map((sig, i) => (
                    <div key={i} dir="ltr" className="flex items-center gap-2 text-[10px] font-mono py-1 border-b border-border-primary/10">
                      <span className={cn('font-bold w-10', sig.direction === 'BUY' ? 'text-neon-green' : sig.direction === 'SELL' ? 'text-neon-red' : 'text-text-muted')}>{sig.direction}</span>
                      <span className="text-text-secondary">conf={sig.confidence.toFixed(2)}</span>
                      <span className="text-neon-gold">SL={sig.sl_pips.toFixed(0)} TP={sig.tp_pips.toFixed(0)}</span>
                      <span className="text-text-muted truncate flex-1">{sig.reasoning?.slice(0, 50)}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {loading && !perf && (
        <div className="flex items-center justify-center py-12 text-text-muted text-xs">
          <RefreshCw className="h-4 w-4 animate-spin me-2" /> جارٍ تحميل حالة DL model…
        </div>
      )}
    </div>
  );
}

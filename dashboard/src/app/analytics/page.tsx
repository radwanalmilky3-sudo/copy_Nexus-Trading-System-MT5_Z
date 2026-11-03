'use client';

import { useState } from 'react';
import {
  BarChart3,
  TrendingUp,
  TrendingDown,
  Percent,
  DollarSign,
  Target,
  Timer,
  Activity,
} from 'lucide-react';
import { cn } from '@/lib/utils';

type AnalyticsTab = 'overview' | 'agents' | 'symbols' | 'drawdown';

const TABS: { value: AnalyticsTab; label: string }[] = [
  { value: 'overview', label: 'نظرة عامة' },
  { value: 'agents', label: 'حسب Agent' },
  { value: 'symbols', label: 'حسب Symbol' },
  { value: 'drawdown', label: 'تحليل Drawdown' },
];

interface MetricCard {
  label: string;
  value: string;
  change?: string;
  positive?: boolean;
  icon: React.ElementType;
  color: string;
}

const OVERVIEW_METRICS: MetricCard[] = [
  { label: 'Total P&L', value: '$0.00', change: '+0%', positive: true, icon: DollarSign, color: 'var(--neon-green)' },
  { label: 'Win Rate', value: '0%', icon: Target, color: 'var(--neon-cyan)' },
  { label: 'Profit Factor', value: '0.00', icon: TrendingUp, color: 'var(--neon-purple)' },
  { label: 'Sharpe Ratio', value: '0.00', icon: Activity, color: 'var(--neon-gold)' },
  { label: 'Max Drawdown', value: '0%', icon: TrendingDown, color: 'var(--neon-red)' },
  { label: 'Avg Trade Duration', value: '—', icon: Timer, color: 'var(--neon-blue)' },
  { label: 'Expectancy', value: '$0.00', icon: Percent, color: 'var(--neon-orange)' },
  { label: 'Recovery Factor', value: '0.00', icon: BarChart3, color: 'var(--neon-pink)' },
];

export default function AnalyticsPage() {
  const [activeTab, setActiveTab] = useState<AnalyticsTab>('overview');

  return (
    <div dir="rtl" className="space-y-6 animate-fade-in">
      {/* Header */}
      <div dir="rtl" className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BarChart3 className="h-6 w-6 text-neon-cyan" />
          <h1 className="text-xl font-bold text-text-primary">التحليلات (Analytics)</h1>
        </div>
      </div>

      {/* Tabs */}
      <div dir="rtl" className="flex items-center gap-1 bg-bg-card rounded-lg p-1 border border-border-primary w-fit">
        {TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setActiveTab(tab.value)}
            className={cn(
              'px-4 py-2 text-sm font-medium rounded-md transition-all',
              activeTab === tab.value
                ? 'bg-neon-purple/15 text-neon-purple'
                : 'text-text-muted hover:text-text-secondary'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Overview Metrics Grid */}
      {activeTab === 'overview' && (
        <>
          <div className="grid grid-cols-4 gap-4">
            {OVERVIEW_METRICS.map((metric) => {
              const Icon = metric.icon;
              return (
                <div key={metric.label} className="neon-card p-4 group">
                  <div className="flex items-center justify-between mb-3">
                    <Icon
                      className="h-5 w-5 opacity-70 group-hover:opacity-100 transition-opacity"
                      style={{ color: metric.color }}
                    />
                    {metric.change && (
                      <span
                        dir="ltr"
                        className={cn(
                          'text-xs font-mono px-1.5 py-0.5 rounded',
                          metric.positive
                            ? 'bg-neon-green/10 text-neon-green'
                            : 'bg-neon-red/10 text-neon-red'
                        )}
                      >
                        {metric.change}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-text-muted mb-1">{metric.label}</p>
                  <p dir="ltr" className="text-xl font-bold font-mono text-text-primary">
                    {metric.value}
                  </p>
                </div>
              );
            })}
          </div>

          {/* Equity Curve Placeholder */}
          <div className="neon-card p-6">
            <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-4">
              منحنى Equity
            </h3>
            <div className="h-64 flex items-center justify-center border border-dashed border-border-primary rounded-lg">
              <span className="text-text-muted text-sm font-mono">
                سيُرسم منحنى Equity هنا باستخدام Recharts
              </span>
            </div>
          </div>

          {/* Distribution Charts */}
          <div className="grid grid-cols-2 gap-4">
            <div className="neon-card p-6">
              <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-4">
                توزيع P&amp;L
              </h3>
              <div className="h-48 flex items-center justify-center border border-dashed border-border-primary rounded-lg">
                <span className="text-text-muted text-xs font-mono">
                  Histogram — بانتظار البيانات
                </span>
              </div>
            </div>
            <div className="neon-card p-6">
              <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-4">
                الأرباح/الخسائر حسب الساعة
              </h3>
              <div className="h-48 flex items-center justify-center border border-dashed border-border-primary rounded-lg">
                <span className="text-text-muted text-xs font-mono">
                  Heatmap — بانتظار البيانات
                </span>
              </div>
            </div>
          </div>
        </>
      )}

      {activeTab === 'agents' && (
        <div className="neon-card p-6">
          <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-4">
            مقارنة أداء Agent
          </h3>
          <div className="h-96 flex items-center justify-center border border-dashed border-border-primary rounded-lg">
            <span className="text-text-muted text-sm font-mono">
              تفصيل Agent — بانتظار بيانات التداول
            </span>
          </div>
        </div>
      )}

      {activeTab === 'symbols' && (
        <div className="neon-card p-6">
          <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-4">
            أداء Symbol
          </h3>
          <div className="h-96 flex items-center justify-center border border-dashed border-border-primary rounded-lg">
            <span className="text-text-muted text-sm font-mono">
              تحليلات لكل Symbol — بانتظار بيانات التداول
            </span>
          </div>
        </div>
      )}

      {activeTab === 'drawdown' && (
        <div className="neon-card p-6">
          <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-4">
            تحليل Drawdown
          </h3>
          <div className="h-96 flex items-center justify-center border border-dashed border-border-primary rounded-lg">
            <span className="text-text-muted text-sm font-mono">
              شلال Drawdown — بانتظار بيانات التداول
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

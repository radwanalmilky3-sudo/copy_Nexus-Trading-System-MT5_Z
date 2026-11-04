'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import {
  LineChart,
  TrendingUp,
  Newspaper,
  Terminal,
  BrainCircuit,
  Shield,
  Zap,
  Brain,
  BookOpen,
  FlaskConical,
  RotateCcw,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { apiClient, getAuthHeaders } from '@/lib/api-client';
import { useDashboardStore, DEFAULT_LAYOUT } from '@/stores/dashboardStore';
import type { LayoutItem } from '@/types';
import ActivePositions from '@/components/windows/ActivePositions';
import AgentConsole from '@/components/windows/AgentConsole';
import NewsFeed from '@/components/windows/NewsFeed';
import RegimeIndicator from '@/components/windows/RegimeIndicator';
import SessionClock from '@/components/windows/SessionClock';
import LiveDecisionPanel from '@/components/windows/LiveDecisionPanel';
import SystemDiagnostic from '@/components/windows/SystemDiagnostic';
import GatewayDiagnostic from '@/components/windows/GatewayDiagnostic';
import { RiskMonitor } from '@/components/windows/RiskMonitor';
import { SystemHealth } from '@/components/windows/SystemHealth';
import { AutoTradeToggle } from '@/components/trade-controls/AutoTradeToggle';
import { KillSwitch } from '@/components/trade-controls/KillSwitch';
import { TradeSettingsPanel } from '@/components/trade-controls/TradeSettingsPanel';
import SystemConsole from '@/components/windows/SystemConsole';
import RegimeLive from '@/components/windows/RegimeLive';
import TradeJournal from '@/components/windows/TradeJournal';
import PLDashboard from '@/components/windows/PLDashboard';
import GridBoard from '@/components/shared/GridBoard';
import WindowBoundary from '@/components/shared/WindowBoundary';
import ConnectionStatusChip from '@/components/shared/ConnectionStatusChip';

/* ── M1.5: heavy windows load on demand (next/dynamic) with a skeleton ── */
const WindowSkeleton = () => (
  <div className="h-full min-h-[120px] w-full animate-pulse rounded-lg border border-border-primary bg-bg-card/60" />
);

const LiveChart = dynamic(() => import('@/components/windows/LiveChart'), { ssr: false, loading: WindowSkeleton });
const AutonomousMLPanel = dynamic(() => import('@/components/windows/AutonomousMLPanel'), { ssr: false, loading: WindowSkeleton });
const AgentFlowchart = dynamic(() => import('@/components/windows/AgentFlowchart'), { ssr: false, loading: WindowSkeleton });
const RLLifecycle = dynamic(() => import('@/components/windows/RLLifecycle'), { ssr: false, loading: WindowSkeleton });
const GenAIBrief = dynamic(() => import('@/components/windows/GenAIBrief'), { ssr: false, loading: WindowSkeleton });
const CorrelationMatrix = dynamic(() => import('@/components/windows/CorrelationMatrix'), { ssr: false, loading: WindowSkeleton });
const CrossAsset = dynamic(() => import('@/components/windows/CrossAsset'), { ssr: false, loading: WindowSkeleton });
const TradeMemoryPanel = dynamic(() => import('@/components/windows/TradeMemoryPanel'), { ssr: false, loading: WindowSkeleton });
const ModelsByRegime = dynamic(() => import('@/components/windows/ModelsByRegime'), { ssr: false, loading: WindowSkeleton });
const MTFConfluence = dynamic(() => import('@/components/windows/MTFConfluence'), { ssr: false, loading: WindowSkeleton });
const SignalQualityGate = dynamic(() => import('@/components/windows/SignalQualityGate'), { ssr: false, loading: WindowSkeleton });
const ErgodicIntelligencePanel = dynamic(() => import('@/components/windows/ErgodicIntelligencePanel'), { ssr: false, loading: WindowSkeleton });
const BacktestPanel = dynamic(() => import('@/components/windows/BacktestPanel'), { ssr: false, loading: WindowSkeleton });
const FundamentalWorkspace = dynamic(() => import('@/components/fundamental/FundamentalWorkspace'), { ssr: false, loading: WindowSkeleton });

const SUB_TABS = [
  { id: 'overview',      label: 'نظرة عامة (Overview)',      icon: LineChart },
  { id: 'positions',     label: 'المراكز (Positions)',       icon: TrendingUp },
  { id: 'risk',          label: 'المخاطرة (Risk)',           icon: Shield },
  { id: 'news',          label: 'الأخبار (News)',            icon: Newspaper },
  { id: 'agents',        label: 'الوكلاء (Agents)',          icon: BrainCircuit },
  { id: 'intelligence',  label: 'الذكاء (Intelligence)',     icon: Brain },
  { id: 'fundamental',   label: 'التحليل الأساسي', icon: BrainCircuit },
  { id: 'journal',       label: 'السجل (Journal)',           icon: BookOpen },
  { id: 'backtest',      label: 'الاختبار الخلفي (Backtest)', icon: FlaskConical },
  { id: 'console',       label: 'وحدة التحكم (Console)',      icon: Terminal },
] as const;

type SubTabId = (typeof SUB_TABS)[number]['id'];

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<SubTabId>('overview');

  /* M1.5 — lazy tab mounting: a tab's content mounts on first visit, then
   * stays mounted (display:none) so later switches remain instant. */
  const [visited, setVisited] = useState<Set<SubTabId>>(
    () => new Set<SubTabId>(['overview'])
  );
  useEffect(() => {
    setVisited((prev) =>
      prev.has(activeTab) ? prev : new Set<SubTabId>(prev).add(activeTab)
    );
  }, [activeTab]);

  /* M1.4 — layout reset wiring (button in the tab bar). */
  const setGridLayout = useDashboardStore((s) => s.setGridLayout);
  const [layoutEpoch, setLayoutEpoch] = useState(0);
  const resetLayout = useCallback(() => {
    setGridLayout(DEFAULT_LAYOUT.map((l) => ({ ...l })));
    setLayoutEpoch((e) => e + 1);
  }, [setGridLayout]);

  return (
    <div className="flex flex-col h-full">
      {/* Sub-tab bar with trade controls — Gold Terminal strip */}
      <div dir="rtl" className="flex items-center gap-1 px-3 h-9 border-b border-amber-500/10 bg-bg-primary/70 backdrop-blur-md shrink-0 overflow-x-auto scrollbar-hide">
        {SUB_TABS.map((tab) => {
          const isActive = tab.id === activeTab;
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium font-mono whitespace-nowrap transition-all border',
                isActive
                  ? 'bg-gradient-to-b from-amber-400 to-amber-600 text-amber-950 font-bold border-amber-500/40 shadow-md shadow-amber-500/25'
                  : 'text-text-muted hover:text-amber-300/80 hover:bg-bg-tertiary/30 border-transparent'
              )}
            >
              <Icon className="h-3 w-3" />
              {tab.label}
            </button>
          );
        })}

        <div className="flex-1" />

        {/* Live-feed status + layout reset + inline trade controls */}
        <div className="flex items-center gap-2 shrink-0">
          <ConnectionStatusChip />
          <button
            onClick={resetLayout}
            title="استعادة التخطيط الافتراضي للوحة"
            className="flex items-center gap-1 rounded border border-border-primary px-2 py-1 font-mono text-[10px] text-text-muted transition-colors hover:bg-bg-tertiary hover:text-text-secondary"
          >
            <RotateCcw className="h-3 w-3" />
            التخطيط الافتراضي
          </button>
          <ScalpingModeToggle />
          <AutoTradeToggle compact />
          <KillSwitch compact />
        </div>
      </div>

      {/* Content — tabs stay mounted (display:none) after first visit so switching is instant */}
      <div dir="rtl" className="flex-1 min-h-0 overflow-auto relative">
        <div style={{ display: activeTab === 'overview' ? 'block' : 'none' }}>
          <OverviewGrid resetKey={layoutEpoch} />
        </div>
        <div style={{ display: activeTab === 'positions' ? 'block' : 'none' }} className="p-2 sm:p-3 h-full w-full max-w-[1600px] mx-auto">
          {visited.has('positions') && (
            <WindowBoundary label="ActivePositions">
              <ActivePositions />
            </WindowBoundary>
          )}
        </div>
        <div
          style={{ display: activeTab === 'risk' ? 'grid' : 'none' }}
          className="p-2 sm:p-3 grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(280px,360px)] gap-2 sm:gap-3 w-full max-w-[1800px] mx-auto min-h-[calc(100vh-90px)] h-[calc(100vh-90px)]"
        >
          {visited.has('risk') && (
            <>
              <div className="flex flex-col gap-2 min-h-0 overflow-hidden">
                <WindowBoundary label="RiskMonitor">
                  <RiskMonitor />
                </WindowBoundary>
                <div className="flex-1 min-h-[160px] overflow-hidden">
                  <WindowBoundary label="ActivePositions">
                    <ActivePositions />
                  </WindowBoundary>
                </div>
              </div>
              <div className="flex flex-col gap-2 min-h-0 overflow-hidden">
                <WindowBoundary label="TradeSettingsPanel">
                  <TradeSettingsPanel />
                </WindowBoundary>
                <WindowBoundary label="SessionClock">
                  <SessionClock compact />
                </WindowBoundary>
                <div className="flex-1 min-h-[140px] overflow-hidden">
                  <WindowBoundary label="SystemHealth">
                    <SystemHealth compact className="h-full" />
                  </WindowBoundary>
                </div>
              </div>
            </>
          )}
        </div>
        <div style={{ display: activeTab === 'news' ? 'block' : 'none' }} className="p-2 sm:p-3 w-full max-w-[1200px] mx-auto">
          {visited.has('news') && (
            <WindowBoundary label="NewsFeed">
              <NewsFeed />
            </WindowBoundary>
          )}
        </div>
        <div style={{ display: activeTab === 'agents' ? 'flex' : 'none' }} className="p-2 sm:p-3 w-full max-w-[1600px] mx-auto min-h-[calc(100vh-90px)] h-[calc(100vh-90px)] flex flex-col">
          {visited.has('agents') && (
            <WindowBoundary label="AgentFlowchart">
              <AgentFlowchart />
            </WindowBoundary>
          )}
        </div>
        <div style={{ display: activeTab === 'intelligence' ? 'block' : 'none' }} className="p-2 sm:p-3 w-full max-w-[1800px] mx-auto">
          {visited.has('intelligence') && <IntelligenceGrid />}
        </div>
        <div style={{ display: activeTab === 'fundamental' ? 'block' : 'none' }} className="w-full max-w-[1900px] mx-auto">
          {visited.has('fundamental') && (
            <WindowBoundary label="FundamentalWorkspace">
              <FundamentalWorkspace />
            </WindowBoundary>
          )}
        </div>
        <div style={{ display: activeTab === 'journal' ? 'flex' : 'none' }} className="p-2 sm:p-3 w-full max-w-[1200px] mx-auto min-h-[calc(100vh-90px)] h-[calc(100vh-90px)] flex flex-col">
          {visited.has('journal') && (
            <div className="flex-1 min-h-0 overflow-hidden border border-border-primary rounded-lg bg-bg-secondary/40">
              <WindowBoundary label="TradeJournal">
                <TradeJournal />
              </WindowBoundary>
            </div>
          )}
        </div>
        <div style={{ display: activeTab === 'backtest' ? 'flex' : 'none' }} className="p-2 sm:p-3 w-full max-w-[1800px] mx-auto min-h-[calc(100vh-90px)] h-[calc(100vh-90px)] flex flex-col">
          {visited.has('backtest') && (
            <div className="flex-1 min-h-0 overflow-hidden border border-neon-purple/20 rounded-lg bg-bg-secondary/40">
              <WindowBoundary label="BacktestPanel">
                <BacktestPanel />
              </WindowBoundary>
            </div>
          )}
        </div>
        <div style={{ display: activeTab === 'console' ? 'flex' : 'none' }} className="p-2 sm:p-3 w-full max-w-[1600px] mx-auto min-h-[calc(100vh-90px)] h-[calc(100vh-90px)] flex flex-col">
          {visited.has('console') && (
            <WindowBoundary label="AgentConsole">
              <AgentConsole />
            </WindowBoundary>
          )}
        </div>
      </div>
    </div>
  );
}

function ScalpingModeToggle() {
  // null = mode not yet confirmed by the server — never fabricate a default.
  const [mode, setMode] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const API = process.env.NEXT_PUBLIC_API_URL || '';

  const loadMode = React.useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/ml/traders/mode`, { headers: getAuthHeaders() });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (typeof d?.current_mode === 'string' && d.current_mode) {
        setMode(d.current_mode);
      } else {
        setMode(null);
      }
    } catch {
      // Keep the last confirmed mode; mark the state unknown if never loaded.
      setMode((prev) => prev);
    }
  }, [API]);

  React.useEffect(() => { void loadMode(); }, [loadMode]);

  const toggle = async () => {
    if (!mode) return;
    const next = mode === 'scalping' ? 'swing' : 'scalping';
    setLoading(true);
    setError('');
    try {
      await apiClient.switchMlMode(next);
      // Re-read the authoritative mode instead of assuming the switch stuck.
      await loadMode();
    } catch (err) {
      // The rejected switch changed nothing server-side — re-read the real
      // mode so the chip never shows an invented value.
      setError(err instanceof Error ? err.message : 'Failed to switch mode');
      await loadMode();
    } finally { setLoading(false); }
  };

  return (
    <button
      onClick={toggle}
      disabled={loading || mode === null}
      title={error || (mode === null ? 'Mode state unavailable' : undefined)}
      className={cn(
        'flex items-center gap-1.5 px-2.5 py-1 rounded text-[10px] font-mono font-bold border transition-all',
        mode === null
          ? 'text-text-muted bg-bg-tertiary border-border-primary cursor-not-allowed'
          : mode === 'scalping'
            ? 'text-neon-green bg-neon-green/10 border-neon-green/30 hover:bg-neon-green/20'
            : 'text-neon-purple bg-neon-purple/10 border-neon-purple/30 hover:bg-neon-purple/20'
      )}
    >
      <Zap className="h-3 w-3" />
      {mode === null ? 'MODE N/A' : mode.toUpperCase()}
    </button>
  );
}

function IntelligenceGrid() {
  return (
    <div className="flex flex-col gap-2 sm:gap-3">
      {/* Top row: Regime + MTF + Signal Quality */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-2 sm:gap-3 min-h-[320px]">
        <div className="border border-border-primary rounded-lg bg-bg-secondary/40 overflow-hidden">
          <WindowBoundary label="RegimeLive">
            <RegimeLive />
          </WindowBoundary>
        </div>
        <div className="border border-border-primary rounded-lg bg-bg-secondary/40 overflow-hidden">
          <WindowBoundary label="MTFConfluence">
            <MTFConfluence />
          </WindowBoundary>
        </div>
        <div className="border border-border-primary rounded-lg bg-bg-secondary/40 overflow-hidden">
          <WindowBoundary label="SignalQualityGate">
            <SignalQualityGate />
          </WindowBoundary>
        </div>
      </div>
      {/* Bottom row: Models by Regime + GenAI Brief + RL Lifecycle + Cross-Asset */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-2 sm:gap-3 min-h-[340px]">
        <div className="border border-border-primary rounded-lg bg-bg-secondary/40 overflow-hidden">
          <WindowBoundary label="ModelsByRegime">
            <ModelsByRegime />
          </WindowBoundary>
        </div>
        <div className="border border-border-primary rounded-lg bg-bg-secondary/40 overflow-hidden">
          <WindowBoundary label="GenAIBrief">
            <GenAIBrief />
          </WindowBoundary>
        </div>
        <div className="border border-neon-purple/20 rounded-lg bg-neon-purple/5 overflow-hidden">
          <WindowBoundary label="RLLifecycle">
            <RLLifecycle />
          </WindowBoundary>
        </div>
        <div className="border border-neon-purple/20 rounded-lg bg-neon-purple/5 overflow-hidden">
          <WindowBoundary label="CrossAsset">
            <CrossAsset />
          </WindowBoundary>
        </div>
      </div>
      {/* Trade Memory + Correlation row */}
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(320px,420px)_minmax(0,1fr)] gap-2 sm:gap-3 min-h-[280px]">
        <div className="border border-neon-purple/20 rounded-lg bg-neon-purple/5 overflow-hidden">
          <WindowBoundary label="TradeMemoryPanel">
            <TradeMemoryPanel />
          </WindowBoundary>
        </div>
        <div className="border border-neon-purple/20 rounded-lg bg-neon-purple/5 overflow-hidden">
          <WindowBoundary label="CorrelationMatrix">
            <CorrelationMatrix />
          </WindowBoundary>
        </div>
      </div>
      {/* Ergodic Intelligence row */}
      <div className="grid grid-cols-1 gap-2 sm:gap-3">
        <div className="border border-amber-500/20 rounded-lg bg-amber-500/5 overflow-hidden">
          <div className="flex items-center gap-2 px-3 pt-3 pb-1">
            <span className="text-xs font-medium text-amber-300 uppercase tracking-widest">الذكاء الإرجعي المؤسسي (Ergodic Intelligence)</span>
            <span className="text-xs text-text-muted" dir="ltr">Hurst · Kelly Peters · Lyapunov · Entropy</span>
          </div>
          <WindowBoundary label="ErgodicIntelligencePanel">
            <ErgodicIntelligencePanel />
          </WindowBoundary>
        </div>
      </div>
    </div>
  );
}

/* M1.4 — Overview as a draggable/resizable GridBoard wired to the store. */
function OverviewGrid({ resetKey }: { resetKey: number }) {
  const gridLayout = useDashboardStore((s) => s.gridLayout);
  const setGridLayout = useDashboardStore((s) => s.setGridLayout);

  /* Defensive merge: accept saved values only for known slots; anything
   * stale (old ids / corrupted) falls back to the shipped default. */
  const layout = useMemo<LayoutItem[]>(
    () =>
      DEFAULT_LAYOUT.map((def) => {
        const saved = gridLayout.find((l) => l.i === def.i);
        return saved ? { ...def, ...saved, i: def.i } : { ...def };
      }),
    [gridLayout]
  );

  const items = useMemo(
    () => [
      {
        i: 'system-diag',
        node: (
          <WindowBoundary label="SystemDiagnostic">
            <SystemDiagnostic />
          </WindowBoundary>
        ),
      },
      {
        i: 'gateway-diag',
        node: (
          <WindowBoundary label="GatewayDiagnostic">
            <GatewayDiagnostic />
          </WindowBoundary>
        ),
      },
      {
        i: 'live-chart',
        node: (
          <WindowBoundary label="LiveChart">
            <LiveChart />
          </WindowBoundary>
        ),
      },
      {
        i: 'side-widgets',
        node: (
          <div className="flex h-full flex-col gap-2 overflow-hidden">
            <WindowBoundary label="SessionClock">
              <SessionClock compact />
            </WindowBoundary>
            <WindowBoundary label="PLDashboard">
              <PLDashboard compact />
            </WindowBoundary>
            <WindowBoundary label="RegimeIndicator">
              <RegimeIndicator compact />
            </WindowBoundary>
          </div>
        ),
      },
      {
        i: 'decisions',
        node: (
          <WindowBoundary label="LiveDecisionPanel">
            <LiveDecisionPanel />
          </WindowBoundary>
        ),
      },
      {
        i: 'positions',
        node: (
          <WindowBoundary label="ActivePositions">
            <ActivePositions />
          </WindowBoundary>
        ),
      },
      {
        i: 'ml-panel',
        node: (
          <WindowBoundary label="AutonomousMLPanel">
            <AutonomousMLPanel />
          </WindowBoundary>
        ),
      },
      {
        i: 'risk',
        node: (
          <WindowBoundary label="RiskMonitor">
            <RiskMonitor className="h-full" />
          </WindowBoundary>
        ),
      },
      {
        i: 'console',
        node: (
          <WindowBoundary label="SystemConsole">
            <SystemConsole className="h-full" />
          </WindowBoundary>
        ),
      },
    ],
    []
  );

  const handleLayoutChange = useCallback(
    (next: LayoutItem[]) => {
      const normalized: LayoutItem[] = next.map((l) => ({
        i: l.i,
        x: l.x,
        y: l.y,
        w: l.w,
        h: l.h,
        minW: l.minW,
        minH: l.minH,
      }));
      setGridLayout(normalized);
    },
    [setGridLayout]
  );

  return (
    <div className="w-full max-w-[1800px] mx-auto p-2 sm:p-3">
      <GridBoard
        key={resetKey}
        layout={layout}
        items={items}
        onLayoutChange={handleLayoutChange}
      />
    </div>
  );
}

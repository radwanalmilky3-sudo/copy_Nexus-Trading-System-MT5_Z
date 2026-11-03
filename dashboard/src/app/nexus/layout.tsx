'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  Zap,
  Activity,
  Shield,
  Bell,
  LayoutDashboard,
  History,
  BrainCircuit,
  Settings,
  Wallet,
  ChevronDown,
  Cpu,
  Trophy,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { apiClient } from '@/lib/api-client';
import { resyncSystemState } from '@/lib/system-state';
import { useDashboardStore } from '@/stores/dashboardStore';
import type { Timeframe } from '@/types';
import { NotificationBell } from '@/components/ui/NotificationBell';
import NewsTickerBar from '@/components/fundamental/NewsTickerBar';
import UserMenu from '@/components/UserMenu';

function GatewaySettingsHydrator() {
  useEffect(() => {
    let cancelled = false;
    const syncSystemState = async () => {
      // Mode/auto-trade/kill-switch come only from GET /api/system/mode
      // (process mode + Redis latches), never from the legacy config cache.
      if (cancelled) return;
      await resyncSystemState();
    };

    const loadAccountSnapshot = async () => {
      try {
        const snap = await apiClient.getPositionsSnapshot();
        if (cancelled) return;
        const acc = snap.data?.account;
        if (!acc) return;
        const store = useDashboardStore.getState();
        store.setAccount({
          balance: typeof acc.balance === 'number' ? acc.balance : undefined,
          equity: typeof acc.equity === 'number' ? acc.equity : undefined,
          margin: typeof acc.margin === 'number' ? acc.margin : undefined,
          freeMargin: typeof acc.free_margin === 'number' ? acc.free_margin : undefined,
        });
        store.setAccountLoaded(true);
      } catch {
        /* gateway/executor offline — keep last known balance, never a permanent zero */
      }
    };

    const loadInitialDashboardState = async () => {
      try {
        const settingsResult = await apiClient.getSettings().catch(() => null);
        if (cancelled) return;

        if (settingsResult) {
          const d = settingsResult.data;
          const sym = d.default_symbol;
          if (typeof sym === 'string' && sym.length >= 4) {
            useDashboardStore.getState().setSymbol(sym.toUpperCase().replace(/\//g, ''));
          }
          const tf = d.default_timeframe;
          if (typeof tf === 'string') {
            useDashboardStore.getState().setTimeframe(tf as Timeframe);
          }
        }

        await loadAccountSnapshot();
      } catch {
        /* gateway offline — keep persisted state */
      }
    };

    void loadInitialDashboardState();
    void syncSystemState();
    const syncTimer = window.setInterval(() => { void syncSystemState(); }, 5000);
    const accountTimer = window.setInterval(() => { void loadAccountSnapshot(); }, 20_000);

    return () => {
      cancelled = true;
      window.clearInterval(syncTimer);
      window.clearInterval(accountTimer);
    };
  }, []);

  return null;
}

const NAV_ITEMS = [
  { href: '/nexus',                       label: 'Trading',    icon: LayoutDashboard },
  { href: '/nexus/strategies',             label: 'Strategies', icon: BrainCircuit },
  { href: '/nexus/models',                 label: 'Models',     icon: Cpu },
  { href: '/nexus/model-comparison',       label: 'Compare',    icon: Trophy },
  { href: '/nexus/history',                label: 'History',    icon: History },
  { href: '/nexus/settings',               label: 'Settings',   icon: Settings },
  { href: '/nexus/progress',                label: 'متابعة التطوير', icon: Activity },
  { href: '/nexus/research-lab',            label: 'مختبر البحث', icon: BrainCircuit },
  { href: '/nexus/audit-progress',          label: 'نتائج التدقيق', icon: Shield },
];

function ModeToggle() {
  const mode = useDashboardStore((s) => s.mode);
  const setMode = useDashboardStore((s) => s.setMode);
  const systemStateStatus = useDashboardStore((s) => s.systemStateStatus);
  const [open, setOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');

  const handleSelectPaper = async () => {
    if (syncing || systemStateStatus !== 'confirmed' || mode === 'PAPER') { setOpen(false); return; }
    setSyncing(true);
    setError('');
    try {
      const response = await apiClient.systemSwitchMode('paper');
      const confirmedMode = response.data.mode.toLowerCase();
      if (confirmedMode !== 'paper') throw new Error('لم يؤكد الخادم التحويل إلى PAPER');
      setMode('PAPER');
      useDashboardStore.getState().setAutoTrade(response.data.auto_trade === true);
      useDashboardStore.getState().setKillSwitch(response.data.kill_switch === true);
      useDashboardStore.getState().setSystemStateStatus('confirmed');
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'تعذر تغيير وضع التداول');
      // A 409/rejection means no mode change was applied server-side;
      // re-read the authoritative state so the header never shows a
      // locally invented mode.
      void resyncSystemState();
    } finally {
      setSyncing(false);
    }
  };

  return (
    <>
      <div className="relative">
        <button
          onClick={() => setOpen(!open)}
          disabled={syncing || systemStateStatus !== 'confirmed'}
          aria-busy={syncing}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-mono font-bold border transition-all',
            syncing && 'opacity-60 pointer-events-none',
            mode === 'LIVE'
              ? 'border-neon-red/40 text-neon-red bg-neon-red/10 hover:bg-neon-red/20'
              : 'border-neon-green/30 text-neon-green bg-neon-green/10 hover:bg-neon-green/20'
          )}
        >
          <Activity className={cn('h-3 w-3', mode === 'LIVE' && 'animate-pulse')} />
          {systemStateStatus === 'confirmed' ? mode : systemStateStatus === 'loading' ? 'SYNC…' : '—'}
          <ChevronDown className="h-2.5 w-2.5 opacity-60" />
        </button>

        {open && systemStateStatus === 'confirmed' && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <div className="absolute right-0 top-full mt-1 w-44 rounded-lg border border-border-primary bg-bg-primary shadow-lg z-50 overflow-hidden">
              {error && <p role="alert" className="border-b border-border-primary px-3 py-2 text-[10px] text-neon-red">{error}</p>}
              <button
                onClick={handleSelectPaper}
                className={cn(
                  'flex items-center gap-2 w-full px-3 py-2.5 text-xs font-medium transition-all border-b border-border-primary/20',
                  mode === 'PAPER' ? 'bg-neon-green/10 text-neon-green' : 'text-text-secondary hover:bg-bg-card-hover'
                )}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-neon-green shrink-0" />
                Paper Trading
              </button>
              <div
                title="يتطلب إعادة تشغيل النظام مع --live --confirm-live"
                className={cn(
                  'flex items-center gap-2 w-full px-3 py-2.5 text-xs font-medium opacity-70',
                  mode === 'LIVE' ? 'bg-neon-red/10 text-neon-red' : 'text-text-muted'
                )}
                aria-disabled="true"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-neon-red shrink-0 animate-pulse" />
                LIVE — إعادة تشغيل مطلوبة
              </div>
              <p className="px-3 pb-2 text-[9px] leading-snug text-text-muted">LIVE لا يُفعّل من الواجهة؛ يتطلب تشغيل النظام بـ --live --confirm-live.</p>
            </div>
          </>
        )}
      </div>
    </>
  );
}

function BalanceDisplay() {
  const balance = useDashboardStore((s) => s.account.balance);
  const equity = useDashboardStore((s) => s.account.equity);
  const dailyPnL = useDashboardStore((s) => s.account.dailyPnL);
  const accountLoaded = useDashboardStore((s) => s.accountLoaded);

  const fmt = (n: number) =>
    n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });

  return (
    <div className="hidden md:flex items-center gap-2 lg:gap-3 px-2 lg:px-3 py-1 rounded-md bg-bg-card border border-border-primary/30">
      <div className="flex items-center gap-1.5">
        <Wallet className="h-3 w-3 text-neon-gold" />
        <span className="text-[10px] text-text-muted font-mono">BAL</span>
        <span className="text-[11px] font-mono font-bold text-neon-gold">{accountLoaded ? fmt(balance) : '—'}</span>
      </div>
      {dailyPnL !== 0 && (
        <>
          <div className="h-3 w-px bg-border-primary" />
          <span className={cn(
            'text-[11px] font-mono font-bold',
            dailyPnL >= 0 ? 'text-neon-green' : 'text-neon-red'
          )}>
            {dailyPnL >= 0 ? '+' : ''}{fmt(dailyPnL)}
          </span>
        </>
      )}
      {accountLoaded && equity !== balance && (
        <>
          <div className="h-3 w-px bg-border-primary" />
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-text-muted font-mono">EQ</span>
            <span className="text-[11px] font-mono text-text-secondary">{fmt(equity)}</span>
          </div>
        </>
      )}
    </div>
  );
}

function LiveModeBanner() {
  const mode = useDashboardStore((s) => s.mode);
  const isKilled = useDashboardStore((s) => s.isKilled);
  const systemStateStatus = useDashboardStore((s) => s.systemStateStatus);

  if (systemStateStatus !== 'confirmed' || mode !== 'LIVE' || isKilled) return null;

  return (
    <div className="h-0.5 w-full bg-gradient-to-r from-transparent via-neon-red/60 to-transparent animate-pulse shrink-0" />
  );
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isKilled = useDashboardStore((s) => s.isKilled);
  const [authStatus, setAuthStatus] = useState<'checking' | 'ready' | 'error'>('checking');
  const [authAttempt, setAuthAttempt] = useState(0);

  useEffect(() => {
    const token = localStorage.getItem('nexus-token');
    if (!token) { router.replace('/login'); return; }
    let cancelled = false;
    // JWT-aware ApiClient probe: bounded by the fetch deadline in api-client
    // (ApiTimeoutError), so the gate can never spin forever.
    apiClient.getMe()
      .then(() => { if (!cancelled) setAuthStatus('ready'); })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof Error && err.message === 'Unauthorized') {
          localStorage.removeItem('nexus-token');
          router.replace('/login');
          return;
        }
        setAuthStatus('error');
      });
    return () => { cancelled = true; };
  }, [router, authAttempt]);

  if (authStatus === 'checking') return <div className="grid h-screen place-items-center bg-bg-primary text-xs text-text-muted">جارٍ التحقق من الحساب…</div>;

  if (authStatus === 'error') {
    return (
      <div className="grid h-screen place-items-center bg-bg-primary px-4" dir="rtl">
        <div className="flex flex-col items-center gap-4 text-center">
          <p role="alert" className="text-xs text-neon-red font-medium">
            تعذر التحقق من الحساب — تحقق من تشغيل الواجهة الخلفية
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => { setAuthStatus('checking'); setAuthAttempt((a) => a + 1); }}
              className="neon-button px-4 py-2 text-xs"
            >
              إعادة المحاولة
            </button>
            <button
              type="button"
              onClick={() => router.replace('/login')}
              className="neon-button px-4 py-2 text-xs"
            >
              تسجيل الدخول
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <GatewaySettingsHydrator />

      {/* Kill switch banner */}
      {isKilled && (
        <div className="flex items-center justify-center gap-2 h-6 bg-neon-red/15 border-b border-neon-red/30 shrink-0">
          <Shield className="h-3 w-3 text-neon-red" />
          <span className="text-[10px] font-mono font-bold text-neon-red uppercase tracking-widest">
            KILL SWITCH ACTIVO — TRADING PAUSADO
          </span>
        </div>
      )}

      {/* Top Nav Bar */}
      <header className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-4 h-10 border-b border-border-primary bg-bg-secondary/90 backdrop-blur-sm shrink-0 z-20">
        {/* Brand */}
        <div className="flex items-center gap-2 mr-3 shrink-0">
          <Zap className="h-4 w-4 text-neon-green" />
          <span className="text-xs font-black tracking-[0.2em] gradient-text hidden sm:inline select-none">
            NEXUS
          </span>
          <span className="hidden sm:inline px-1.5 py-0.5 rounded text-[8px] font-mono font-bold bg-yellow-400/10 border border-yellow-400/30 text-yellow-400 tracking-wider select-none">
            DEMO
          </span>
        </div>

        <div className="h-4 w-px bg-border-primary shrink-0" />

        {/* Nav links */}
        <nav className="flex items-center gap-0.5 flex-1 overflow-x-auto scrollbar-hide">
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.href === '/nexus'
                ? pathname === '/nexus'
                : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-medium whitespace-nowrap transition-all relative',
                  isActive
                    ? 'bg-neon-purple/15 text-neon-purple'
                    : 'text-text-muted hover:text-text-secondary hover:bg-bg-tertiary/50'
                )}
              >
                <Icon className="h-3 w-3" />
                <span className="hidden sm:inline">{item.label}</span>
                {isActive && (
                  <span className="absolute bottom-0 left-1 right-1 h-px rounded-full bg-neon-purple/60" />
                )}
              </Link>
            );
          })}
        </nav>

        {/* Right controls */}
        <div className="flex items-center gap-1.5 shrink-0">
          <BalanceDisplay />

          <div className="h-4 w-px bg-border-primary" />

          <ModeToggle />

          <div className="h-4 w-px bg-border-primary" />

          <NotificationBell />
          <UserMenu />
        </div>
      </header>

      {/* Live mode indicator line */}
      <LiveModeBanner />

      {/* Fundamental/news alert layer. Presentation only; no execution authority. */}
      <NewsTickerBar />

      <main className="flex-1 min-h-0 overflow-auto">{children}</main>
    </div>
  );
}

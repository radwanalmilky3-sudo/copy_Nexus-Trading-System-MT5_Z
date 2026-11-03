'use client';

import { useState } from 'react';
import { Activity, ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { apiClient } from '@/lib/api-client';
import { resyncSystemState } from '@/lib/system-state';
import { useDashboardStore } from '@/stores/dashboardStore';

/** Legacy exported selector; all mode changes are confirmed by the gateway. */
export function ModeSelector() {
  const mode = useDashboardStore((state) => state.mode);
  const systemStateStatus = useDashboardStore((state) => state.systemStateStatus);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const selectPaper = async () => {
    if (busy || systemStateStatus !== 'confirmed') return;
    setBusy(true);
    setError('');
    try {
      const response = await apiClient.systemSwitchMode('paper');
      if (response.data.mode.toLowerCase() !== 'paper') {
        throw new Error('الخادم لم يؤكد وضع PAPER');
      }
      const store = useDashboardStore.getState();
      store.setMode('PAPER');
      store.setAutoTrade(response.data.auto_trade === true);
      store.setKillSwitch(response.data.kill_switch === true);
      store.setSystemStateStatus('confirmed');
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'تعذر تغيير وضع التداول');
      // Rejected/failed switch: no server-side change was applied — resync
      // so the label keeps showing the real process mode.
      void resyncSystemState();
    } finally {
      setBusy(false);
    }
  };

  const label = systemStateStatus === 'confirmed'
    ? (mode === 'LIVE' ? 'LIVE' : mode === 'BACKTEST' ? 'BACKTEST' : 'PAPER')
    : systemStateStatus === 'loading' ? 'SYNC…' : '—';

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((value) => !value)}
        disabled={busy || systemStateStatus !== 'confirmed'}
        aria-busy={busy}
        className={cn(
          'flex items-center gap-2 rounded-lg px-3 py-2 bg-bg-input border border-border-primary transition-colors',
          'hover:border-neon-purple/40 disabled:cursor-not-allowed disabled:opacity-50',
        )}
      >
        <Activity className={cn('h-4 w-4', mode === 'LIVE' ? 'text-neon-red' : 'text-text-muted')} />
        <span className="text-xs font-bold text-text-primary">{label}</span>
        <ChevronDown className="h-3 w-3 text-text-muted" />
      </button>
      {open && systemStateStatus === 'confirmed' && (
        <div className="absolute top-full left-0 mt-1 z-50 w-64 rounded-lg border border-border-primary bg-bg-card p-2 shadow-lg">
          {error && <p role="alert" className="px-2 py-1 text-xs text-neon-red">{error}</p>}
          <button
            onClick={selectPaper}
            disabled={busy || mode === 'PAPER'}
            className="w-full rounded px-2 py-2 text-left text-xs text-text-secondary hover:bg-bg-card-hover disabled:opacity-50"
          >
            Switch to PAPER (server confirmed)
          </button>
          <p className="px-2 py-1 text-[10px] leading-relaxed text-text-muted">
            LIVE cannot be enabled in the dashboard; restart the runner with its explicit live confirmation flags.
          </p>
        </div>
      )}
    </div>
  );
}

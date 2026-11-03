import { apiClient } from '@/lib/api-client';
import { useDashboardStore } from '@/stores/dashboardStore';

/**
 * Load trading mode / auto-trade / kill-switch from the authoritative
 * ``GET /api/system/mode`` endpoint (process-level mode + Redis system
 * latches) and only then update the Zustand store.
 *
 * Returns true when the server payload was valid and applied; otherwise the
 * store is marked ``unavailable`` so no control claims a confirmed state.
 * Callers must never optimistically flip the store before this resolves.
 */
export async function resyncSystemState(): Promise<boolean> {
  try {
    const result = await apiClient.getSystemMode();
    const state = result.data;
    const mode = typeof state.mode === 'string' ? state.mode.toLowerCase() : '';
    if (
      (mode === 'live' || mode === 'paper')
      && typeof state.auto_trade === 'boolean'
      && typeof state.kill_switch === 'boolean'
    ) {
      const store = useDashboardStore.getState();
      store.setMode(mode === 'live' ? 'LIVE' : 'PAPER');
      store.setAutoTrade(state.auto_trade);
      // setKillSwitch(true) also forces auto-trade off, matching the
      // backend kill-switch semantics; call it after setAutoTrade.
      store.setKillSwitch(state.kill_switch);
      store.setSystemStateStatus('confirmed');
      return true;
    }
    useDashboardStore.getState().setSystemStateStatus('unavailable');
    return false;
  } catch {
    useDashboardStore.getState().setSystemStateStatus('unavailable');
    return false;
  }
}

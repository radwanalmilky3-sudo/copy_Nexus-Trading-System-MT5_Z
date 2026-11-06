import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { TradingMode, Timeframe, LayoutItem, AccountInfo } from '@/types';

interface DashboardState {
  /* Trading state */
  symbol: string;
  timeframe: Timeframe;
  mode: TradingMode;
  autoTradeEnabled: boolean;
  isKilled: boolean;
  systemStateStatus: 'loading' | 'confirmed' | 'unavailable';

  /* Account */
  account: AccountInfo;
  accountLoaded: boolean;

  /* Layout */
  gridLayout: LayoutItem[];
  sidebarCollapsed: boolean;

  /* Actions */
  setSymbol: (symbol: string) => void;
  setTimeframe: (tf: Timeframe) => void;
  setMode: (mode: TradingMode) => void;
  toggleAutoTrade: () => void;
  setAutoTrade: (enabled: boolean) => void;
  setSystemStateStatus: (status: 'loading' | 'confirmed' | 'unavailable') => void;
  setKillSwitch: (enabled: boolean) => void;
  activateKillSwitch: () => void;
  deactivateKillSwitch: () => void;
  setAccount: (account: Partial<AccountInfo>) => void;
  setAccountLoaded: (loaded: boolean) => void;
  setGridLayout: (layout: LayoutItem[]) => void;
  toggleSidebar: () => void;
}

/* M1.4 — Overview board slots (12-col GridBoard). Ids must match the
 * windows rendered in OverviewGrid (nexus/page.tsx); stale persisted
 * layouts are discarded by migrate + the defensive merge in the page.
 * 2026-11-06 — restored the owner's previous arrangement (screenshot
 * match): wide chart 9/3 with the side widgets, narrow Live Decision
 * 3/9 beside Active Positions, ML full width, Risk|Console 6/6. */
export const DEFAULT_LAYOUT: LayoutItem[] = [
  { i: 'system-diag',   x: 0, y: 0,  w: 12, h: 3,  minW: 6, minH: 2 },
  { i: 'gateway-diag',  x: 0, y: 3,  w: 12, h: 3,  minW: 6, minH: 2 },
  { i: 'live-chart',    x: 0, y: 6,  w: 9,  h: 14, minW: 6, minH: 10 },
  { i: 'side-widgets',  x: 9, y: 6,  w: 3,  h: 14, minW: 3, minH: 10 },
  { i: 'decisions',     x: 0, y: 20, w: 3,  h: 12, minW: 3, minH: 8 },
  { i: 'positions',     x: 3, y: 20, w: 9,  h: 12, minW: 4, minH: 8 },
  { i: 'ml-panel',      x: 0, y: 32, w: 12, h: 10, minW: 6, minH: 6 },
  { i: 'risk',          x: 0, y: 42, w: 6,  h: 12, minW: 4, minH: 8 },
  { i: 'console',       x: 6, y: 42, w: 6,  h: 12, minW: 4, minH: 8 },
];

export const useDashboardStore = create<DashboardState>()(
  persist(
    (set) => ({
      symbol: 'XAUUSD',
      timeframe: 'M15',
      mode: 'PAPER',
      autoTradeEnabled: true,
      isKilled: false,
      systemStateStatus: 'loading',

      account: {
        balance: 0,
        equity: 0,
        margin: 0,
        freeMargin: 0,
        dailyPnL: 0,
        openPositions: 0,
      },
      accountLoaded: false,

      gridLayout: DEFAULT_LAYOUT,
      sidebarCollapsed: false,

      setSymbol: (symbol) => set({ symbol }),
      setTimeframe: (timeframe) => set({ timeframe }),
      setMode: (mode) => set({ mode }),
      toggleAutoTrade: () =>
        set((s) => ({ autoTradeEnabled: !s.autoTradeEnabled })),
      setAutoTrade: (enabled) => set({ autoTradeEnabled: enabled }),
      setSystemStateStatus: (systemStateStatus) => set({ systemStateStatus }),
      setKillSwitch: (enabled) => set(
        enabled ? { isKilled: true, autoTradeEnabled: false } : { isKilled: false },
      ),
      activateKillSwitch: () =>
        set({ isKilled: true, autoTradeEnabled: false }),
      deactivateKillSwitch: () => set({ isKilled: false }),
      setAccount: (account) =>
        set((s) => ({ account: { ...s.account, ...account } })),
      setAccountLoaded: (accountLoaded) => set({ accountLoaded }),
      setGridLayout: (gridLayout) => set({ gridLayout }),
      toggleSidebar: () =>
        set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
    }),
    {
      name: 'nexus-dashboard',
      version: 6,
      partialize: (state) => ({
        symbol: state.symbol,
        timeframe: state.timeframe,
        mode: state.mode,
        autoTradeEnabled: state.autoTradeEnabled,
        gridLayout: state.gridLayout,
        sidebarCollapsed: state.sidebarCollapsed,
      }),
      migrate: (persisted: unknown, version: number) => {
        const state = persisted as unknown as Partial<DashboardState>;
        // Ensure symbol is always one of our valid symbols
        if (state?.symbol && !['XAUUSD', 'BTCUSD'].includes(state.symbol)) {
          state.symbol = 'XAUUSD';
        }
        // v6: owner's restored arrangement — discard stale/incompatible layouts.
        const defaultIds = DEFAULT_LAYOUT.map((l) => l.i);
        const gl = state?.gridLayout;
        const valid =
          version >= 6 &&
          Array.isArray(gl) &&
          gl.length === defaultIds.length &&
          gl.every(
            (item) =>
              item &&
              defaultIds.includes(item.i) &&
              typeof item.x === 'number' &&
              typeof item.y === 'number' &&
              typeof item.w === 'number' &&
              typeof item.h === 'number'
          );
        if (!valid) {
          state.gridLayout = DEFAULT_LAYOUT.map((l) => ({ ...l }));
        }
        return state as DashboardState;
      },
    }
  )
);

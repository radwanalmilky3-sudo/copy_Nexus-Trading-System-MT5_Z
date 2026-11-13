import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const SRC = fileURLToPath(new URL('../src/', import.meta.url));

/** Load a TS/TSX module in a sandbox, resolving '@/…' aliases to src/. */
function load(path, sandboxExtras = {}) {
  const code = ts.transpileModule(readFileSync(path, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const context = {
    exports: {}, console, process: { env: {} },
    require: (name) => {
      if (name.startsWith('@/')) return load(resolve(SRC, name.slice(2)));
      if (!name.startsWith('.')) return require(name);
      const p = resolve(dirname(path), name);
      return load(existsSync(p + '.tsx') ? p + '.tsx' : p + '.ts');
    },
    ...sandboxExtras,
  };
  vm.runInNewContext(code, context);
  return context.exports;
}

// Storage stub installed as the REAL globalThis.localStorage BEFORE the store
// module loads: zustand v4's default getStorage closes over zustand's own
// module scope (real Node), so it reads the host globalThis — not the sandbox.
function storageStub(initial) {
  let value = initial ?? null;
  const calls = { setItem: [] };
  const localStorage = {
    getItem: () => value,
    setItem: (_k, v) => { calls.setItem.push(v); value = v; },
    removeItem: () => { value = null; },
  };
  return {
    calls,
    install() { globalThis.localStorage = localStorage; },
    uninstall() { delete globalThis.localStorage; },
  };
}

/** Load the dashboard store with a fresh module instance and bound storage. */
function loadStore(storage) {
  storage.install();
  try {
    return load(resolve(SRC, 'stores/dashboardStore.ts'));
  } finally {
    storage.uninstall();
  }
}

test('dashboard store defaults are safe', () => {
  const { useDashboardStore } = loadStore(storageStub());
  const s = useDashboardStore.getState();
  assert.equal(s.symbol, 'XAUUSD');
  assert.equal(s.mode, 'PAPER');
  assert.equal(s.isKilled, false);
  assert.equal(s.systemStateStatus, 'loading', 'controls must not claim a confirmed state before resync');
});

test('latching the kill switch forces auto-trade off', () => {
  const { useDashboardStore } = loadStore(storageStub());
  const store = useDashboardStore;
  store.getState().setAutoTrade(true);
  store.getState().setKillSwitch(true);
  assert.equal(store.getState().isKilled, true);
  assert.equal(store.getState().autoTradeEnabled, false, 'kill switch must cut auto-trade');
});

test('releasing the kill switch does NOT silently re-enable auto-trade', () => {
  const { useDashboardStore } = loadStore(storageStub());
  const store = useDashboardStore;
  store.getState().setAutoTrade(true);
  store.getState().setKillSwitch(true);
  store.getState().setKillSwitch(false);
  assert.equal(store.getState().isKilled, false);
  assert.equal(store.getState().autoTradeEnabled, false,
    'auto-trade must come back only by an explicit confirmed toggle');
  store.getState().activateKillSwitch();
  assert.equal(store.getState().isKilled, true);
  store.getState().deactivateKillSwitch();
  assert.equal(store.getState().isKilled, false);
  assert.equal(store.getState().autoTradeEnabled, false);
});

test('setAccount merges partial account info', () => {
  const { useDashboardStore } = loadStore(storageStub());
  const store = useDashboardStore;
  store.getState().setAccount({ balance: 1000, equity: 1050 });
  const a = store.getState().account;
  assert.equal(a.balance, 1000);
  assert.equal(a.equity, 1050);
  assert.equal('margin' in a, true, 'unspecified fields are preserved, not wiped');
});

test('persisted snapshot excludes volatile safety state', () => {
  const storage = storageStub();
  const { useDashboardStore } = loadStore(storage);
  useDashboardStore.getState().setKillSwitch(true);
  useDashboardStore.getState().setSystemStateStatus('confirmed');
  assert.equal(storage.calls.setItem.length > 0, true, 'persist wrote a snapshot');
  const snapshot = JSON.parse(storage.calls.setItem.at(-1)).state;
  assert.equal('isKilled' in snapshot, false, 'kill latch must come from the server, never localStorage');
  assert.equal('systemStateStatus' in snapshot, false);
  assert.equal('account' in snapshot, false);
  assert.equal(snapshot.symbol, 'XAUUSD');
});

test('rehydrate discards a stale (pre-v6) layout and resets unknown symbols', async () => {
  const stale = JSON.stringify({
    state: { symbol: 'EURUSD', gridLayout: [{ i: 'old-panel', x: 0, y: 0, w: 4, h: 4 }] },
    version: 5,
  });
  const { useDashboardStore } = loadStore(storageStub(stale));
  await useDashboardStore.persist.rehydrate();
  const s = useDashboardStore.getState();
  assert.equal(s.symbol, 'XAUUSD', 'unknown symbols fall back to XAUUSD');
  assert.equal(s.gridLayout.length, 9, 'stale layouts are replaced by DEFAULT_LAYOUT');
  assert.equal(s.gridLayout.some((l) => l.i === 'live-chart'), true);
});

test('rehydrate keeps a valid v6 layout', async () => {
  const { DEFAULT_LAYOUT } = loadStore(storageStub());
  const valid = JSON.stringify({ state: { symbol: 'BTCUSD', gridLayout: DEFAULT_LAYOUT }, version: 6 });
  const { useDashboardStore } = loadStore(storageStub(valid));
  await useDashboardStore.persist.rehydrate();
  const s = useDashboardStore.getState();
  assert.equal(s.symbol, 'BTCUSD');
  // Both sides come from different vm realms (different object prototypes),
  // so compare JSON-normalized copies created in the host realm.
  assert.deepEqual(JSON.parse(JSON.stringify(s.gridLayout)), JSON.parse(JSON.stringify(DEFAULT_LAYOUT)));
});

test('DEFAULT_LAYOUT slots are unique and inside the 12-col grid', () => {
  const { DEFAULT_LAYOUT } = loadStore(storageStub());
  const ids = DEFAULT_LAYOUT.map((l) => l.i);
  assert.equal(new Set(ids).size, ids.length, 'no duplicate slot ids');
  for (const l of DEFAULT_LAYOUT) {
    assert.ok(l.w >= (l.minW ?? 0) && l.h >= (l.minH ?? 0), `${l.i} respects its own minimums`);
    assert.ok(l.x >= 0 && l.x + l.w <= 12, `${l.i} fits the 12 columns`);
    assert.ok(l.y >= 0 && l.h > 0, `${l.i} has a positive row span`);
  }
});

test('trading store: defaults, toggle, and mode', () => {
  const { useTradingStore } = load(resolve(SRC, 'stores/trading.ts'));
  const store = useTradingStore;
  assert.equal(store.getState().autoTrade, false, 'trading store starts conservative');
  assert.equal(store.getState().mode, 'paper');
  assert.equal(store.getState().selectedSymbol, 'XAUUSD');
  store.getState().toggleAutoTrade();
  assert.equal(store.getState().autoTrade, true);
  store.getState().setMode('live');
  assert.equal(store.getState().mode, 'live');
  store.getState().setSelectedTimeframe('M5');
  assert.equal(store.getState().selectedTimeframe, 'M5');
});

test('notification store: add, cap, dismiss, clear, auto-dismiss timing', () => {
  const captured = [];
  // The store runs inside the vm sandbox — inject the capturing setTimeout
  // there instead of patching the host global.
  const fakeSetTimeout = (fn, ms) => { captured.push([fn, ms]); return captured.length; };
  const { useNotificationStore } = load(resolve(SRC, 'stores/notifications.ts'), { setTimeout: fakeSetTimeout });
  const store = useNotificationStore;

  store.getState().info('t1', 'm1', 0); // duration 0 → never auto-dismissed
  store.getState().warning('t2', undefined, 0);
  assert.equal(store.getState().notifications.length, 2);
  assert.equal(store.getState().notifications[0].type, 'warning', 'newest first');

  for (let i = 0; i < 60; i++) store.getState().info(`n${i}`, undefined, 0);
  assert.equal(store.getState().notifications.length, 50, 'history is capped at 50');

  const id = store.getState().notifications[0].id;
  store.getState().dismissNotification(id);
  assert.equal(store.getState().notifications.find((n) => n.id === id).dismissed, true);
  store.getState().clearAll();
  assert.equal(store.getState().notifications.every((n) => n.dismissed), true);

  // error() uses a longer duration (8s) — assert the scheduling, don't wait.
  store.getState().error('boom');
  store.getState().success('ok');
  assert.deepEqual(captured.at(-2)[1], 8000, 'errors persist longer than toasts');
  assert.deepEqual(captured.at(-1)[1], 5000);
  const [autoDismissFn, autoMs] = captured.at(-1);
  assert.equal(typeof autoDismissFn, 'function');
  assert.ok(autoMs > 0);
});

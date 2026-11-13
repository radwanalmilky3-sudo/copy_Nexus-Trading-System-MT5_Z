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

function load(path, sandboxExtras = {}) {
  const code = ts.transpileModule(readFileSync(path, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const context = {
    exports: {}, console, process: { env: {} },
    require: (name) => {
      const tryExts = (p) => load(existsSync(p + '.tsx') ? p + '.tsx' : p + '.ts', sandboxExtras);
      if (name.startsWith('@/')) return tryExts(resolve(SRC, name.slice(2)));
      if (!name.startsWith('.')) return require(name);
      return tryExts(resolve(dirname(path), name));
    },
    ...sandboxExtras,
  };
  vm.runInNewContext(code, context);
  return context.exports;
}

// ── Browser-ish environment fakes ──

class FakeWS {
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  static instances = [];
  constructor(url) {
    this.url = url; this.readyState = 0; this.sent = []; this.closedWith = null;
    FakeWS.instances.push(this);
  }
  send(raw) { this.sent.push(JSON.parse(raw)); }
  close(code = 1000, reason) { // mirrors the browser default close code
    this.readyState = 3; this.closedWith = { code, reason };
    if (this.onclose) this.onclose({ code });
  }
  open() { this.readyState = 1; if (this.onopen) this.onopen(); }
  message(obj) { if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) }); }
}

function freshClient({ token = 'tok-1' } = {}) {
  FakeWS.instances = [];
  const timers = { scheduled: [], cleared: [] };
  const localStorage = {
    getItem: (k) => (k === 'nexus-token' ? token : null),
    setItem: () => {}, removeItem: () => {},
  };
  const prevWindow = globalThis.window;
  globalThis.window = { location: { protocol: 'https:', host: 'dash.example' } };
  const { wsClient } = load(resolve(SRC, 'lib/ws-client.ts'), {
    WebSocket: FakeWS,
    localStorage,
    // The module checks `typeof window` inside the sandbox — the host global
    // does not leak into the vm context, so pass it explicitly.
    window: globalThis.window,
    setTimeout: (fn, ms) => { timers.scheduled.push({ fn, ms }); return timers.scheduled.length; },
    clearTimeout: (id) => { timers.cleared.push(id); },
  });
  return {
    wsClient, timers,
    get lastSocket() { return FakeWS.instances.at(-1) ?? null; },
    cleanup() {
      wsClient.disconnect();
      globalThis.window = prevWindow;
    },
  };
}

test('unsupported channels stay inert — the client never fakes a link', () => {
  const env = freshClient();
  try {
    const statuses = [];
    env.wsClient.onStatusChange((s) => statuses.push(s));
    env.wsClient.subscribe('performance');
    assert.equal(env.lastSocket, null, 'no socket dialed for a channel with no gateway route');
    assert.equal(env.wsClient.status, 'disconnected', 'status never claims connected for a missing feed');
  } finally { env.cleanup(); }
});

test('no JWT → no dial, status error', () => {
  const env = freshClient({ token: null });
  try {
    env.wsClient.subscribe('ticks');
    assert.equal(env.lastSocket, null);
    assert.equal(env.wsClient.status, 'error');
  } finally { env.cleanup(); }
});

test('dial URL targets the gateway /ws/<channel> with the transform port', () => {
  const env = freshClient();
  try {
    env.wsClient.subscribe('ticks', { symbols: 'XAUUSD' });
    const ws = env.lastSocket;
    assert.equal(ws.url, 'wss://dash.example/ws/ticks?XTransformPort=9000');
  } finally { env.cleanup(); }
});

test('auth frame is the FIRST frame and carries the JWT', () => {
  const env = freshClient();
  try {
    env.wsClient.subscribe('ticks', { symbols: 'XAUUSD' });
    const ws = env.lastSocket;
    ws.open();
    assert.deepEqual(ws.sent[0], { type: 'auth', token: 'tok-1' });
    assert.equal(env.wsClient.status, 'connecting', 'bare TCP open is never reported as connected');
  } finally { env.cleanup(); }
});

test('auth ack gates the channel and re-sends the ticks subscription', () => {
  const env = freshClient();
  try {
    env.wsClient.subscribe('ticks', { symbols: 'XAUUSD,  BTCUSD' });
    const ws = env.lastSocket;
    ws.open();
    ws.message({ type: 'auth', ok: true });
    assert.equal(env.wsClient.status, 'connected');
    assert.deepEqual(ws.sent[1], { action: 'subscribe', symbols: ['XAUUSD', 'BTCUSD'] },
      'subscription params are normalized to a symbol array');
  } finally { env.cleanup(); }
});

test('auth rejection closes with 4401 and does not hammer reconnects', () => {
  const env = freshClient();
  try {
    env.wsClient.subscribe('ticks');
    const ws = env.lastSocket;
    ws.open();
    ws.message({ type: 'auth', ok: false });
    assert.equal(ws.closedWith.code, 4401);
    assert.equal(env.timers.scheduled.length, 0, 'no reconnect after an auth/permission rejection');
    assert.equal(env.wsClient.status, 'error');
  } finally { env.cleanup(); }
});

test('data frames dispatch to the channel and the wildcard listener; junk is ignored', () => {
  const env = freshClient();
  try {
    const seen = { ticks: [], star: [] };
    env.wsClient.on('ticks', (m) => seen.ticks.push(m));
    env.wsClient.on('*', (m) => seen.star.push(m));
    env.wsClient.subscribe('ticks');
    const ws = env.lastSocket;
    ws.open();
    ws.message({ type: 'auth', ok: true });
    ws.message({ channel: 'ticks', data: { price: 2035.5 } });
    ws.message({ channel: 'risk', data: { note: 'misrouted' } });
    assert.equal(seen.ticks.length, 1, 'a frame tagged risk is routed to risk, not ticks');
    assert.equal(seen.star.length, 2, 'the wildcard listener sees every frame');
    ws.onmessage({ data: 'not-json' });
    assert.equal(seen.ticks.length, 1, 'non-JSON frames are dropped silently');
    assert.equal(seen.star.length, 2);
  } finally { env.cleanup(); }
});

test('abnormal close schedules an exponential-backoff reconnect', () => {
  const env = freshClient();
  try {
    env.wsClient.subscribe('ticks');
    const ws = env.lastSocket;
    ws.open();
    ws.message({ type: 'auth', ok: true });
    ws.close(1006, 'connection lost');
    assert.equal(env.timers.scheduled.length, 1);
    assert.equal(env.timers.scheduled[0].ms, 1000, 'first retry after 1s');
    assert.notEqual(env.wsClient.status, 'connected', 'a dropped socket is never reported connected');
    // Fire the timer → a new dial happens with auth re-sent on open.
    env.timers.scheduled[0].fn();
    assert.equal(FakeWS.instances.length, 2, 'reconnect dials a fresh socket');
    FakeWS.instances[1].open();
    assert.deepEqual(FakeWS.instances[1].sent[0].type, 'auth', 'auth is re-sent on every reconnect');
  } finally { env.cleanup(); }
});

test('disconnect() cancels pending reconnects and stops dialing', () => {
  const env = freshClient();
  try {
    env.wsClient.subscribe('ticks');
    env.lastSocket.open();
    env.lastSocket.close(1006);
    assert.equal(env.timers.scheduled.length, 1);
    env.wsClient.disconnect();
    env.timers.scheduled[0].fn();
    assert.equal(FakeWS.instances.length, 1, 'no dial after an explicit disconnect');
    assert.equal(env.wsClient.status, 'disconnected');
  } finally { env.cleanup(); }
});

test('unsubscribe closes the socket and removes the channel', () => {
  const env = freshClient();
  try {
    env.wsClient.subscribe('positions');
    const ws = env.lastSocket;
    ws.open();
    ws.message({ type: 'auth', ok: true });
    env.wsClient.unsubscribe('positions');
    assert.equal(ws.closedWith.code, 1000, 'unsubscribe is a clean close');
    assert.equal(env.wsClient.status, 'disconnected');
  } finally { env.cleanup(); }
});

test('emit only sends on an authenticated ticks socket', () => {
  const env = freshClient();
  try {
    env.wsClient.emit('ping', { x: 1 });
    assert.equal(env.lastSocket, null, 'nothing dialed, nothing sent');
    env.wsClient.subscribe('ticks');
    const ws = env.lastSocket;
    ws.open();
    env.wsClient.emit('ping', { x: 1 });
    assert.equal(ws.sent.length, 1, 'pre-auth frames are not sent');
    ws.message({ type: 'auth', ok: true });
    env.wsClient.emit('ping', { x: 1 });
    assert.deepEqual(ws.sent.at(-1), { event: 'ping', data: { x: 1 } });
  } finally { env.cleanup(); }
});

test('onStatusChange fires immediately with the current status and unsubscribes cleanly', () => {
  const env = freshClient();
  try {
    const seen = [];
    const off = env.wsClient.onStatusChange((s) => seen.push(s));
    assert.deepEqual(seen, ['disconnected']);
    off();
    env.wsClient.subscribe('ticks');
    env.lastSocket.open();
    env.lastSocket.message({ type: 'auth', ok: true });
    assert.equal(seen.length, 1, 'listener removed — no further status events');
  } finally { env.cleanup(); }
});

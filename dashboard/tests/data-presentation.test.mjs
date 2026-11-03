import assert from 'node:assert/strict';
import test from 'node:test';
import { positionPresentation, backtestHasObservations, gatewayTiltStatus, fetchSessionPerformance } from '../src/lib/data-presentation.ts';

test('a failed empty position snapshot does not claim no open positions or zero PnL', () => {
  const view = positionPresentation({ received: false, stale: true, liveConnected: false, count: 0 });
  assert.equal(view.confirmed, false);
  assert.match(view.emptyMessage, /unavailable/i);
  assert.doesNotMatch(view.emptyMessage, /no open positions/i);
});

test('only a received fresh connected empty snapshot can confirm no positions', () => {
  assert.equal(positionPresentation({ received: false, stale: false, liveConnected: false, count: 0 }).confirmed, false);
  assert.equal(positionPresentation({ received: true, stale: false, liveConnected: false, count: 0 }).confirmed, false);
  const view = positionPresentation({ received: true, stale: false, liveConnected: true, count: 0 });
  assert.equal(view.confirmed, true);
  assert.match(view.emptyMessage, /no open positions/i);
});

test('previous positions remain explicitly stale after a failed refresh', () => {
  const view = positionPresentation({ received: true, stale: true, liveConnected: true, count: 2 });
  assert.equal(view.confirmed, false);
  assert.match(view.emptyMessage, /stale/i);
});

test('zero, missing and malformed trade counts cannot be evaluated as performance', () => {
  for (const value of [undefined, null, 0, -1, NaN, Infinity, '4', 0.5]) assert.equal(backtestHasObservations(value), false);
  assert.equal(backtestHasObservations(1), true);
  assert.equal(backtestHasObservations(20), true);
});

test('missing or stale tilt is unknown rather than normal', () => {
  assert.equal(gatewayTiltStatus(undefined, undefined, false), 'UNKNOWN');
  assert.equal(gatewayTiltStatus('NORMAL', undefined, true), 'UNKNOWN');
  assert.equal(gatewayTiltStatus('NORMAL', undefined, false), 'NORMAL');
  assert.equal(gatewayTiltStatus(undefined, 'TILT', false), 'TILT');
  assert.equal(gatewayTiltStatus('unexpected', undefined, false), 'UNKNOWN');
});

test('session metrics use the implemented authenticated intelligence contract', async () => {
  const original = globalThis.fetch;
  let requested;
  globalThis.fetch = async (url, options) => {
    requested = { url, headers: options.headers };
    return new Response(JSON.stringify({ metrics: { by_session: { LONDON: {
      total_trades: 4, win_rate: 0.75, avg_win_pips: 20, avg_loss_pips: -10, net_pnl_usd: 30,
    } } }, thresholds: {}, recent_trades: [] }));
  };
  try {
    const rows = await fetchSessionPerformance('http://localhost:9000', { Authorization: 'Bearer test-only' });
    assert.equal(requested.url, 'http://localhost:9000/api/intelligence/trade-memory');
    assert.equal(requested.headers.Authorization, 'Bearer test-only');
    assert.deepEqual(rows, [{ session: 'LONDON', trades: 4, win_rate: 0.75, net_pnl: 30, kelly: 0.625 }]);
  } finally { globalThis.fetch = original; }
});

test('unavailable memory is not a successful empty session snapshot', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response('{}', { status: 503 });
  try { await assert.rejects(fetchSessionPerformance('http://localhost:9000', {}), /503/); }
  finally { globalThis.fetch = original; }
});

test('actual producer session contract preserves counts without inventing Kelly or dollars', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ metrics: {
    total_trades: 4, total_wins: 3, total_losses: 1, overall_win_rate: 0.75,
    by_session: { LONDON: { trades: 4, wins: 3, losses: 1, win_rate: 0.75, avg_pnl: 12.5 } },
  }, thresholds: {}, recent_trades: [] }));
  try {
    assert.deepEqual(await fetchSessionPerformance('http://localhost:9000', {}), [
      { session: 'LONDON', trades: 4, win_rate: 0.75, net_pnl: null, kelly: null },
    ]);
  } finally { globalThis.fetch = original; }
});

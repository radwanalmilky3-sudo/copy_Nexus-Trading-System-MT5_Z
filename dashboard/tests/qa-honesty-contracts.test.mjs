import assert from 'node:assert/strict';
import test from 'node:test';
import {
  backtestHasObservations,
  crossAssetPresentation,
  gatewayTiltStatus,
  positionPresentation,
  sanitizeGroupStats,
  tradeMemoryPresentation,
} from '../src/lib/data-presentation.ts';
import {
  classifyCandlesProbe,
  classifyDiagnosticBanner,
  classifyUpstreamProbe,
} from '../src/lib/system-health-status.ts';

// ══ UI-02: gateway tilt must fall to UNKNOWN, never a fabricated NORMAL ══════

test('UI-02 pin: gatewayTiltStatus(undefined, "normal", false) === "UNKNOWN"', () => {
  assert.equal(gatewayTiltStatus(undefined, 'normal', false), 'UNKNOWN');
});

test('UI-02 pin: lowercase/dirty risk values never match the whitelist', () => {
  assert.equal(gatewayTiltStatus(undefined, 'normal', false), 'UNKNOWN');
  assert.equal(gatewayTiltStatus('ok', undefined, false), 'UNKNOWN');
  assert.equal(gatewayTiltStatus('ready', null, false), 'UNKNOWN');
  assert.equal(gatewayTiltStatus(0, 0, false), 'UNKNOWN');
});

test('UI-02 pin: stale wins over any status value', () => {
  assert.equal(gatewayTiltStatus('NORMAL', 'NORMAL', true), 'UNKNOWN');
  assert.equal(gatewayTiltStatus(undefined, undefined, true), 'UNKNOWN');
});

test('UI-02 control: only exact NORMAL/WARNING/TILT survive when not stale', () => {
  assert.equal(gatewayTiltStatus('NORMAL', null, false), 'NORMAL');
  assert.equal(gatewayTiltStatus(undefined, 'WARNING', false), 'WARNING');
  assert.equal(gatewayTiltStatus(null, 'TILT', false), 'TILT');
  assert.equal(gatewayTiltStatus(undefined, undefined, false), 'UNKNOWN');
});

// ══ UI-03: position presentation never claims an unverified "empty" ═══════════

test('UI-03 pin: stale snapshot reports staleness, not "no open positions"', () => {
  const p = positionPresentation({ received: true, stale: true, liveConnected: true, count: 0 });
  assert.equal(p.confirmed, false);
  assert.match(p.emptyMessage, /stale/i);
  assert.doesNotMatch(p.emptyMessage, /^No open positions/);
});

test('UI-03 pin: never-received / disconnected data is unconfirmed', () => {
  const never = positionPresentation({ received: false, stale: false, liveConnected: false, count: 0 });
  assert.equal(never.confirmed, false);
  assert.match(never.emptyMessage, /unavailable or awaiting verification/i);
  assert.match(never.emptyMessage, /Cannot confirm/i);

  const disconnected = positionPresentation({ received: true, stale: false, liveConnected: false, count: 0 });
  assert.equal(disconnected.confirmed, false);
  assert.match(disconnected.emptyMessage, /Cannot confirm/i);
});

test('UI-03 control: verified empty snapshot may say "No open positions"', () => {
  const p = positionPresentation({ received: true, stale: false, liveConnected: true, count: 0 });
  assert.equal(p.confirmed, true);
  assert.match(p.emptyMessage, /verified live snapshot/);
});

// ══ UI-04: cross-asset without price inputs can never produce a grade ═════════

test('UI-04 pin: crossAssetPresentation with no price input is unavailable', () => {
  for (const payload of [null, undefined, {}, { dxy: { level: null }, us10y: { level: null } }]) {
    const p = crossAssetPresentation(payload);
    assert.equal(p.available, false, `payload ${JSON.stringify(payload)}`);
    assert.equal(p.regime, 'unknown');
    assert.equal(p.pts, null);
    assert.equal(p.divergence, null);
    assert.equal(p.updatedAt, null);
  }
});

test('UI-04 pin: a claimed grade from missing data is stripped', () => {
  const p = crossAssetPresentation({
    dxy: { level: null, source: 'no_data' },
    us10y: { level: null, source: 'no_data' },
    gold_yield_regime: 'neutral',
    gold_dxy_divergence: 0,
    cross_asset_signal_pts: 3,
    updated_at: null,
  });
  assert.equal(p.available, false);
  assert.equal(p.regime, 'unknown');
  assert.equal(p.pts, null);
  assert.equal(p.divergence, null);
});

test('UI-04 pin: out-of-range / non-string regime values degrade to unknown', () => {
  const base = { dxy: { level: 98.4 }, us10y: { level: 4.2 } };
  assert.equal(crossAssetPresentation({ ...base, cross_asset_signal_pts: 7 }).pts, null);
  assert.equal(crossAssetPresentation({ ...base, cross_asset_signal_pts: -1 }).pts, null);
  assert.equal(crossAssetPresentation({ ...base, cross_asset_signal_pts: NaN }).pts, null);
  assert.equal(crossAssetPresentation({ ...base, gold_dxy_divergence: 2 }).divergence, null);
  assert.equal(crossAssetPresentation({ ...base, gold_yield_regime: 'ready' }).regime, 'unknown');
  assert.equal(crossAssetPresentation({ ...base, gold_yield_regime: 5 }).regime, 'unknown');
});

// ══ UI-05: trade-memory never fabricates totals from garbage ══════════════════

test('UI-05 pin: tradeMemoryPresentation({}) has no fabricated totals', () => {
  const p = tradeMemoryPresentation({});
  assert.equal(p.hasMetrics, true);
  assert.equal(p.totalTrades, null);
  assert.equal(p.totalWins, null);
  assert.equal(p.totalLosses, null);
  assert.equal(p.winRate, null);
  assert.equal(p.avgPnlPips, null);
  assert.equal(p.zeroTrades, false, 'missing totals must not read as "zero trades"');
});

test('UI-05 pin: non-object input is "no metrics", not zeroed metrics', () => {
  for (const bad of [null, undefined, 'NaN', 42, [], [1, 2]]) {
    const p = tradeMemoryPresentation(bad);
    assert.equal(p.hasMetrics, false, `input ${JSON.stringify(bad)}`);
    assert.equal(p.totalTrades, null);
    assert.equal(p.zeroTrades, false);
  }
});

test('UI-05 pin: only a real integer 0 counts as zeroTrades', () => {
  assert.equal(tradeMemoryPresentation({ total_trades: 0 }).zeroTrades, true);
  assert.equal(tradeMemoryPresentation({ total_trades: '0' }).totalTrades, null);
  assert.equal(tradeMemoryPresentation({ total_trades: NaN }).totalTrades, null);
  assert.equal(tradeMemoryPresentation({ total_trades: -3 }).totalTrades, null);
  assert.equal(tradeMemoryPresentation({ total_trades: 2.5 }).totalTrades, null);
  assert.equal(tradeMemoryPresentation({ total_trades: 7 }).totalTrades, 7);
});

test('UI-05 pin: invalid win-rate / pnl values are dropped, not coerced', () => {
  assert.equal(tradeMemoryPresentation({ overall_win_rate: 1.5 }).winRate, null);
  assert.equal(tradeMemoryPresentation({ overall_win_rate: '0.5' }).winRate, null);
  assert.equal(tradeMemoryPresentation({ overall_win_rate: NaN }).winRate, null);
  assert.equal(tradeMemoryPresentation({ avg_pnl_pips: Infinity }).avgPnlPips, null);
  assert.equal(tradeMemoryPresentation({ avg_pnl_pips: -2.5 }).avgPnlPips, -2.5);
});

test('UI-05 pin: sanitizeGroupStats turns junk into null cells, never NaN', () => {
  const rows = sanitizeGroupStats({
    asia: { trades: NaN, win_rate: '0.6', avg_pnl: 'x' },
    london: { trades: 4, win_rate: 0.5, avg_pnl: 1.2 },
    broken: null,
    list: [1, 2],
  });
  assert.equal(rows.length, 2);
  const asia = rows.find((r) => r.key === 'asia');
  assert.equal(asia.trades, null);
  assert.equal(asia.winRate, null);
  assert.equal(asia.avgPnl, null);
  const london = rows.find((r) => r.key === 'london');
  assert.equal(london.trades, 4);
  assert.equal(london.winRate, 0.5);
  assert.equal(sanitizeGroupStats(null).length, 0);
  assert.equal(sanitizeGroupStats('junk').length, 0);
});

// ══ UI-06: zero observations are "no data", never a negative performance ══════

test('UI-06 pin: backtestHasObservations(0) === false', () => {
  assert.equal(backtestHasObservations(0), false);
});

test('UI-06 pin: non-observation values are rejected', () => {
  for (const bad of [undefined, null, NaN, -1, 0.5, 3.7, '5', '0', {}, [], true]) {
    assert.equal(backtestHasObservations(bad), false, `input ${JSON.stringify(bad)}`);
  }
});

test('UI-06 control: a positive integer count is an observation', () => {
  assert.equal(backtestHasObservations(1), true);
  assert.equal(backtestHasObservations(42), true);
});

// ══ API-01: probe classification separates auth/upstream/route failures ══════

test('API-01 pin: classifyUpstreamProbe(502) contains "upstream offline"', () => {
  const r = classifyUpstreamProbe(502);
  assert.equal(r.kind, 'upstream');
  assert.match(r.detail, /upstream offline/);
});

test('API-01 pin: 503/504 are upstream offline; 401/403 are auth; 404 is route', () => {
  assert.match(classifyUpstreamProbe(503).detail, /upstream offline/);
  assert.match(classifyUpstreamProbe(504).detail, /upstream offline/);
  assert.equal(classifyUpstreamProbe(401).kind, 'auth');
  assert.equal(classifyUpstreamProbe(403).kind, 'auth');
  const nf = classifyUpstreamProbe(404);
  assert.equal(nf.kind, 'not-found');
  assert.match(nf.detail, /route not found/);
});

test('API-01 pin: no non-2xx status may ever classify as ok', () => {
  for (const status of [0, 204.5, 400, 401, 404, 418, 500, 502, 503]) {
    if (status >= 200 && status < 300) continue;
    assert.notEqual(classifyUpstreamProbe(status).kind, 'ok', `HTTP ${status}`);
  }
  assert.equal(classifyUpstreamProbe(200).kind, 'ok');
  assert.equal(classifyUpstreamProbe(299).kind, 'ok');
});

test('API-01 pin: classifyCandlesProbe(401) is auth, not offline', () => {
  const r = classifyCandlesProbe(401, false);
  assert.equal(r.kind, 'auth');
  assert.doesNotMatch(r.detail, /offline/i);
  assert.doesNotMatch(r.detail, /unavailable/i);
  assert.match(r.detail, /auth required/);
});

test('API-01 pin: candles 403 auth, 502 upstream, 200 empty is no-data not ok', () => {
  assert.equal(classifyCandlesProbe(403, true).kind, 'auth');
  assert.equal(classifyCandlesProbe(502, false).kind, 'upstream');
  const empty = classifyCandlesProbe(200, false);
  assert.equal(empty.kind, 'no-data');
  assert.notEqual(empty.kind, 'ok');
  assert.equal(classifyCandlesProbe(200, true).kind, 'ok');
  assert.equal(classifyCandlesProbe(0, false).kind, 'unreachable');
});

// ══ UI-01: the banner never claims health before a completed check ═══════════

test('UI-01 pin: empty service lists are always "checking", never "healthy"', () => {
  assert.equal(classifyDiagnosticBanner(false, []), 'checking');
  assert.equal(classifyDiagnosticBanner(true, []), 'checking');
});

test('UI-01 pin: "healthy" requires a completed check with all services ok', () => {
  assert.equal(classifyDiagnosticBanner(false, [{ ok: true }]), 'checking');
  assert.equal(classifyDiagnosticBanner(true, [{ ok: true }]), 'healthy');
  assert.equal(classifyDiagnosticBanner(true, [{ ok: true }, { ok: false }]), 'fault');
  assert.equal(classifyDiagnosticBanner(true, [{ ok: false }]), 'fault');
});

import assert from 'node:assert/strict';
import test from 'node:test';
import {
  crossAssetPresentation,
  tradeMemoryPresentation,
  sanitizeGroupStats,
} from '../src/lib/data-presentation.ts';

// ── UI-04: missing cross-asset inputs must not yield a grade ──────────────────

test('UI-04 regression: no_data levels + claimed neutral/3 are presented as unavailable', () => {
  // The exact shape the gateway used to fabricate before the API fix.
  const payload = {
    dxy: { level: null, source: 'no_data' },
    us10y: { level: null, source: 'no_data' },
    gold_yield_regime: 'neutral',
    gold_dxy_divergence: 0,
    cross_asset_signal_pts: 3,
    updated_at: null,
  };
  const p = crossAssetPresentation(payload);
  assert.equal(p.available, false);
  assert.equal(p.regime, 'unknown');
  assert.equal(p.pts, null);
  assert.equal(p.divergence, null);
  assert.equal(p.updatedAt, null);
});

test('cross-asset: a null payload is unavailable', () => {
  const p = crossAssetPresentation(null);
  assert.equal(p.available, false);
  assert.equal(p.pts, null);
});

test('cross-asset: recent success (real levels) passes regime and points through', () => {
  const p = crossAssetPresentation({
    dxy: { level: 98.4 },
    us10y: { level: 4.21 },
    gold_yield_regime: 'risk_off',
    gold_dxy_divergence: 1,
    cross_asset_signal_pts: 5,
    updated_at: '2026-10-21T10:00:00Z',
  });
  assert.equal(p.available, true);
  assert.equal(p.regime, 'risk_off');
  assert.equal(p.pts, 5);
  assert.equal(p.divergence, 1);
  assert.equal(p.updatedAt, '2026-10-21T10:00:00Z');
});

test('cross-asset: partial data (one asset has a level) is still available', () => {
  const p = crossAssetPresentation({
    dxy: { level: 98.4, source: 'official' },
    us10y: { level: null, source: 'no_data' },
    gold_yield_regime: 'neutral',
    cross_asset_signal_pts: 3,
    updated_at: '2026-10-21T10:00:00Z',
  });
  assert.equal(p.available, true);
  assert.equal(p.regime, 'neutral');
});

test('cross-asset: out-of-range points and unknown regimes never leak through', () => {
  const p = crossAssetPresentation({
    dxy: { level: 98.4 },
    us10y: { level: 4.2 },
    gold_yield_regime: 'banana',
    cross_asset_signal_pts: 9,
    gold_dxy_divergence: 7,
    updated_at: '2026-10-21T10:00:00Z',
  });
  assert.equal(p.regime, 'unknown');
  assert.equal(p.pts, null);
  assert.equal(p.divergence, null);
});

test('cross-asset: non-finite levels (NaN/Infinity) do not count as prices', () => {
  const p = crossAssetPresentation({
    dxy: { level: NaN },
    us10y: { level: Infinity },
    gold_yield_regime: 'neutral',
    cross_asset_signal_pts: 3,
  });
  assert.equal(p.available, false);
});

// ── UI-05: trade-memory metrics must never render undefined ───────────────────

test('UI-05 regression: metrics={} yields unknown totals, not undefined and not zero', () => {
  const tm = tradeMemoryPresentation({});
  assert.equal(tm.hasMetrics, true);
  assert.equal(tm.totalTrades, null);
  assert.equal(tm.zeroTrades, false);
  assert.equal(tm.winRate, null);
  assert.equal(tm.avgPnlPips, null);
});

test('trade-memory: missing metrics object is an unknown state', () => {
  const tm = tradeMemoryPresentation(undefined);
  assert.equal(tm.hasMetrics, false);
  assert.equal(tm.totalTrades, null);
  assert.equal(tm.zeroTrades, false);
});

test('trade-memory: an explicit zero is the valid "zero trades" state', () => {
  const tm = tradeMemoryPresentation({ total_trades: 0, total_wins: 0, total_losses: 0, overall_win_rate: 0 });
  assert.equal(tm.totalTrades, 0);
  assert.equal(tm.zeroTrades, true);
});

test('trade-memory: non-numeric totals (strings/NaN) are rejected to null', () => {
  assert.equal(tradeMemoryPresentation({ total_trades: '12' }).totalTrades, null);
  assert.equal(tradeMemoryPresentation({ total_trades: NaN }).totalTrades, null);
  assert.equal(tradeMemoryPresentation({ total_trades: 12.5 }).totalTrades, null);
  assert.equal(tradeMemoryPresentation({ total_trades: -3 }).totalTrades, null);
});

test('trade-memory: partial metrics keep the valid fields and null the rest', () => {
  const tm = tradeMemoryPresentation({ total_trades: 12, total_wins: 7 });
  assert.equal(tm.totalTrades, 12);
  assert.equal(tm.totalWins, 7);
  assert.equal(tm.totalLosses, null);
  assert.equal(tm.winRate, null);
  assert.equal(tm.zeroTrades, false);
});

test('trade-memory: out-of-range win rates are rejected', () => {
  assert.equal(tradeMemoryPresentation({ total_trades: 5, overall_win_rate: 55 }).winRate, null);
  assert.equal(tradeMemoryPresentation({ total_trades: 5, overall_win_rate: -0.1 }).winRate, null);
  assert.equal(tradeMemoryPresentation({ total_trades: 5, overall_win_rate: 0.55 }).winRate, 0.55);
});

test('trade-memory: a healthy sample passes through unchanged', () => {
  const tm = tradeMemoryPresentation({
    total_trades: 40, total_wins: 22, total_losses: 18,
    overall_win_rate: 0.55, avg_pnl_pips: 1.2,
  });
  assert.deepEqual(tm, {
    hasMetrics: true, totalTrades: 40, totalWins: 22, totalLosses: 18,
    winRate: 0.55, avgPnlPips: 1.2, zeroTrades: false,
  });
});

// ── Breakdown sanitization ────────────────────────────────────────────────────

test('sanitizeGroupStats: valid rows survive, invalid fields become null', () => {
  const rows = sanitizeGroupStats({
    asia: { trades: 10, win_rate: 0.6, avg_pnl: 1.5 },
    london: { trades: 'many', win_rate: NaN, avg_pnl: null },
    new_york: { not_stats: true },
  });
  const byKey = Object.fromEntries(rows.map((r) => [r.key, r]));
  assert.deepEqual(byKey.asia, { key: 'asia', trades: 10, winRate: 0.6, avgPnl: 1.5 });
  assert.deepEqual(byKey.london, { key: 'london', trades: null, winRate: null, avgPnl: null });
  assert.deepEqual(byKey.new_york, { key: 'new_york', trades: null, winRate: null, avgPnl: null });
});

test('sanitizeGroupStats: non-object input yields no rows', () => {
  assert.deepEqual(sanitizeGroupStats(null), []);
  assert.deepEqual(sanitizeGroupStats([]), []);
  assert.deepEqual(sanitizeGroupStats('x'), []);
});

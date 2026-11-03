import assert from 'node:assert/strict';
import test from 'node:test';
import { hasCompleteTradeStats } from '../src/lib/trade-stats-status.ts';

test('incomplete successful response is not treated as zero-valued trade statistics', () => {
  assert.equal(hasCompleteTradeStats({ total_trades: 0, total_pnl: 0 }), false);
});

test('complete zero-trade response remains a valid empty history snapshot', () => {
  assert.equal(hasCompleteTradeStats({
    total_trades: 0, winning: 0, losing: 0, win_rate: 0, total_pnl: 0,
    avg_pnl: 0, avg_rr: 0, best_trade: 0, worst_trade: 0, avg_duration_s: 0,
  }), true);
});

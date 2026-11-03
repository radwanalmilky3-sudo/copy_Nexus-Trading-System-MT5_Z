import assert from 'node:assert/strict';
import test from 'node:test';
import { hasMarketFeedBars } from '../src/lib/market-feed-status.ts';

test('an empty successful candle response is not considered a healthy feed', () => {
  assert.equal(hasMarketFeedBars({ success: true, data: [] }), false);
});

test('a successful response with at least one bar is considered a healthy feed', () => {
  assert.equal(hasMarketFeedBars({ success: true, data: [{ timestamp: '2026-10-14T00:00:00Z' }] }), true);
});

test('malformed or unsuccessful candle responses are not considered a healthy feed', () => {
  assert.equal(hasMarketFeedBars({ success: false, data: [{ timestamp: '2026-10-14T00:00:00Z' }] }), false);
  assert.equal(hasMarketFeedBars({ success: true, data: null }), false);
});

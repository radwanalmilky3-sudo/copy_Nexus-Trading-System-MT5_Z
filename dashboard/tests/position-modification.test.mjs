import assert from 'node:assert/strict';
import test from 'node:test';
import { preparePositionModification } from '../src/lib/position-modification.ts';

test('blank levels do not produce a mutation payload', () => {
  assert.deepEqual(
    preparePositionModification({ side: 'BUY', currentPrice: 100 }, ' ', ''),
    { ok: false, reason: 'no_changes' },
  );
});

test('only explicitly supplied levels are sent for a BUY position', () => {
  assert.deepEqual(
    preparePositionModification({ side: 'BUY', currentPrice: 100 }, '95.5', ''),
    { ok: true, payload: { sl: 95.5 } },
  );
});

test('SELL levels use inverse protective and profitable directions', () => {
  assert.deepEqual(
    preparePositionModification({ side: 'SELL', currentPrice: 100 }, '', '90'),
    { ok: true, payload: { tp1: 90 } },
  );
  assert.deepEqual(
    preparePositionModification({ side: 'SELL', currentPrice: 100 }, '105', ''),
    { ok: true, payload: { sl: 105 } },
  );
});

test('rejects malformed prices, non-positive values, and invalid trade geometry', () => {
  assert.deepEqual(
    preparePositionModification({ side: 'BUY', currentPrice: 100 }, 'NaN', ''),
    { ok: false, reason: 'invalid_stop_loss' },
  );
  assert.deepEqual(
    preparePositionModification({ side: 'BUY', currentPrice: 100 }, '100', ''),
    { ok: false, reason: 'stop_loss_not_protective' },
  );
  assert.deepEqual(
    preparePositionModification({ side: 'BUY', currentPrice: 100 }, '', '99'),
    { ok: false, reason: 'take_profit_not_profitable' },
  );
  assert.deepEqual(
    preparePositionModification({ side: 'BUY', currentPrice: Infinity }, '90', ''),
    { ok: false, reason: 'price_unavailable' },
  );
});

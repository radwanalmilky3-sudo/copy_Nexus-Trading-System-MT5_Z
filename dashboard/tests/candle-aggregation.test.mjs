import assert from 'node:assert/strict';
import test from 'node:test';
import {
  applyTick,
  bucketStart,
  candleRowsToBars,
  positionPriceLines,
  safeEpochSeconds,
  tickPrice,
  tradeMarkers,
  TF_SECONDS,
} from '../src/lib/candle-aggregation.ts';

test('timeframe seconds map covers the five supported frames', () => {
  assert.deepEqual(TF_SECONDS, { M1: 60, M5: 300, M15: 900, H1: 3600, H4: 14400 });
});

test('safeEpochSeconds parses ISO, epoch seconds and milliseconds', () => {
  const iso = '2026-11-05T10:00:00Z';
  assert.equal(safeEpochSeconds(iso), Date.parse(iso) / 1000);
  assert.equal(safeEpochSeconds(1700000000), 1700000000);
  assert.equal(safeEpochSeconds(1700000000123), 1700000000);
  assert.equal(safeEpochSeconds('not-a-date'), null);
  assert.equal(safeEpochSeconds(null), null);
  assert.equal(safeEpochSeconds(undefined), null);
  assert.equal(safeEpochSeconds(0), null);
  assert.equal(safeEpochSeconds(-5), null);
});

test('bucketStart floors to the timeframe grid', () => {
  // 10:07:34 UTC → M15 bucket 10:00, H1 bucket 10:00, M1 bucket 10:07.
  const t = Date.UTC(2026, 10, 5, 10, 7, 34) / 1000;
  assert.equal(bucketStart(t, 'M15'), Date.UTC(2026, 10, 5, 10, 0) / 1000);
  assert.equal(bucketStart(t, 'H1'), Date.UTC(2026, 10, 5, 10, 0) / 1000);
  assert.equal(bucketStart(t, 'M1'), Date.UTC(2026, 10, 5, 10, 7) / 1000);
});

test('tickPrice uses the mid price and falls back to one finite side', () => {
  assert.equal(tickPrice(2000.0, 2000.2), 2000.1);
  assert.equal(tickPrice(2000.0, undefined), 2000.0);
  assert.equal(tickPrice(undefined, 2000.2), 2000.2);
  assert.equal(tickPrice(Number.NaN, 0), null);
  assert.equal(tickPrice(undefined, undefined), null);
});

test('applyTick updates the current bucket without rewriting history', () => {
  const t0 = Date.UTC(2026, 10, 5, 10, 0, 5) / 1000;
  const first = applyTick(null, t0, 2000.0, 'M15');
  assert.ok(first);
  assert.equal(first.isNew, true);
  assert.equal(first.bar.time, Date.UTC(2026, 10, 5, 10, 0) / 1000);
  assert.equal(first.bar.open, 2000.0);

  const sameBucket = applyTick(first.bar, t0 + 60, 2010.0, 'M15');
  assert.ok(sameBucket);
  assert.equal(sameBucket.isNew, false);
  assert.equal(sameBucket.bar.high, 2010.0);
  assert.equal(sameBucket.bar.low, 2000.0);
  assert.equal(sameBucket.bar.close, 2010.0);
  assert.equal(sameBucket.bar.volume, 2);

  // A later bucket opens a NEW bar (open/close = the fresh price).
  const nextBucket = applyTick(first.bar, t0 + 900, 2020.0, 'M15');
  assert.ok(nextBucket);
  assert.equal(nextBucket.isNew, true);
  assert.equal(nextBucket.bar.open, 2020.0);

  // A LATE tick (older bucket) is dropped — never back-fill from ticks.
  const late = applyTick(first.bar, t0 - 3600, 1990.0, 'M15');
  assert.equal(late, null);
});

test('applyTick rejects unusable inputs', () => {
  assert.equal(applyTick(null, t_of('2026-11-05T10:00:00Z'), 0, 'M15'), null);
  assert.equal(applyTick(null, t_of('2026-11-05T10:00:00Z'), -3, 'M15'), null);
  assert.equal(applyTick(null, t_of('2026-11-05T10:00:00Z'), Number.NaN, 'M15'), null);
  assert.equal(applyTick(null, Number.NaN, 2000, 'M15'), null);
});

function t_of(iso) {
  return Date.parse(iso) / 1000;
}

test('candleRowsToBars sorts, dedupes and drops invalid rows', () => {
  const a = '2026-11-05T10:15:00Z';
  const b = '2026-11-05T10:30:00Z';
  const bars = candleRowsToBars(
    [
      { timestamp: b, open: 10, high: 12, low: 9, close: 11, volume: 5 },
      { timestamp: a, open: 9, high: 10, low: 8, close: 9.5, volume: 3 },
      // duplicate of b with different close — last wins
      { timestamp: b, open: 10, high: 13, low: 9, close: 12, volume: 6 },
      // invalid rows are dropped, never coerced
      { timestamp: 'bad', open: 1, high: 1, low: 1, close: 1, volume: 1 },
      { timestamp: a, open: -1, high: 10, low: 8, close: 9.5, volume: 3 },
      { timestamp: a, open: 'x', high: 10, low: 8, close: 9.5, volume: 3 },
    ],
    'M15',
  );
  assert.equal(bars.length, 2);
  assert.equal(bars[0].time, t_of(a));
  assert.equal(bars[1].time, t_of(b));
  assert.equal(bars[1].close, 12);
  // high/low are normalized against open/close
  assert.equal(bars[1].high, 13);
  assert.ok(bars[0].low <= bars[0].open && bars[0].low <= bars[0].close);
  assert.deepEqual(candleRowsToBars(null, 'M15'), []);
  assert.deepEqual(candleRowsToBars('nope', 'M15'), []);
});

test('tradeMarkers filters by symbol, snaps to buckets and clips to range', () => {
  const trades = [
    { symbol: 'XAUUSD', side: 'BUY', opened_at: '2026-11-05T10:07:00Z', closed_at: '2026-11-05T10:44:00Z', pnl_usd: 12.34 },
    { symbol: 'BTCUSD', side: 'BUY', opened_at: '2026-11-05T10:07:00Z' },
    { symbol: 'XAUUSD', side: 'SELL', opened_at: '2026-11-05T11:02:00Z' },
    { symbol: 'XAUUSD', side: 'weird', opened_at: '2026-11-05T11:02:00Z' },
  ];
  const range = { from: t_of('2026-11-05T10:00:00Z'), to: t_of('2026-11-05T10:59:59Z') };
  const markers = tradeMarkers(trades, 'XAUUSD', 'M15', range);
  // BUY entry (10:07→10:00) + BUY exit (10:44→10:30) inside range; SELL at 11:02 clipped out.
  assert.equal(markers.length, 2);
  assert.equal(markers[0].shape, 'arrowUp');
  assert.equal(markers[0].position, 'belowBar');
  assert.equal(markers[0].time, t_of('2026-11-05T10:00:00Z'));
  assert.equal(markers[1].shape, 'circle');
  assert.equal(markers[1].text, '+12.3');
  assert.deepEqual(tradeMarkers(trades, 'BTCUSD', 'M15', null).length, 1);
  assert.deepEqual(tradeMarkers([], 'XAUUSD', 'M15', null), []);
  assert.deepEqual(tradeMarkers(null, 'XAUUSD', 'M15', null), []);
});

test('positionPriceLines emits entry/SL/TP for the matching symbol only', () => {
  const positions = [
    { symbol: 'XAUUSD', entry_price: 2000, sl: 1990, tp1: 2030 },
    { symbol: 'BTCUSD', entry_price: 60000, sl: 59000, tp: 62000 },
    { symbol: 'XAUUSD', entry_price: Number.NaN, sl: 0, tp1: undefined },
  ];
  const specs = positionPriceLines(positions, 'xauusd');
  assert.deepEqual(
    specs.map((s) => [s.title, s.price]),
    [
      ['ENTRY', 2000],
      ['SL', 1990],
      ['TP', 2030],
    ],
  );
  assert.deepEqual(positionPriceLines([], 'XAUUSD'), []);
  assert.deepEqual(positionPriceLines(null, 'XAUUSD'), []);
});

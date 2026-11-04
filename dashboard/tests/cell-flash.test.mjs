import assert from 'node:assert/strict';
import test from 'node:test';
import { cellFlashes, flashClass } from '../src/lib/cell-flash.ts';

test('first snapshot never flashes (no previous values)', () => {
  assert.deepEqual(cellFlashes(null, { a: 1 }), {});
  assert.deepEqual(cellFlashes(undefined, { a: 1 }), {});
});

test('increases flash up and decreases flash down', () => {
  const out = cellFlashes({ price: 2000, pnl: -5 }, { price: 2001.5, pnl: -7.2, unchanged: 3 });
  assert.deepEqual(out, { price: 'up', pnl: 'down' });
});

test('new keys and non-finite values never flash', () => {
  const out = cellFlashes({ known: 10 }, { known: 10, fresh: 99, broken: Number.NaN });
  assert.deepEqual(out, {});
});

test('equal values produce no flash', () => {
  assert.deepEqual(cellFlashes({ a: 5 }, { a: 5 }), {});
});

test('flashClass maps directions to the CSS hooks', () => {
  assert.equal(flashClass('up'), 'cell-flash-up');
  assert.equal(flashClass('down'), 'cell-flash-down');
  assert.equal(flashClass(undefined), '');
});

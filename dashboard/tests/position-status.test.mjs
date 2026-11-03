import assert from 'node:assert/strict';
import test from 'node:test';
import { getPositionConnectionLabel } from '../src/lib/position-status.ts';

test('a failed refresh labels the previous live snapshot stale', () => {
  assert.equal(
    getPositionConnectionLabel({ stale: true, liveConnected: true, accountBroker: 'MT5' }),
    'STALE',
  );
});

test('a fresh live snapshot retains its broker label', () => {
  assert.equal(
    getPositionConnectionLabel({ stale: false, liveConnected: true, accountBroker: 'MT5' }),
    'LIVE:MT5',
  );
});

test('a fresh disconnected snapshot remains offline', () => {
  assert.equal(
    getPositionConnectionLabel({ stale: false, liveConnected: false, accountBroker: null }),
    'OFFLINE',
  );
});

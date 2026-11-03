import assert from 'node:assert/strict';
import test from 'node:test';
import { classifyProbeStatus } from '../src/lib/system-health-status.ts';

test('a 5xx response is reachable but unhealthy, not offline', () => {
  assert.equal(classifyProbeStatus(false, 503), 'degraded');
});

test('a transport failure is offline and a successful response is online', () => {
  assert.equal(classifyProbeStatus(false, 0), 'offline');
  assert.equal(classifyProbeStatus(true, 200), 'online');
});

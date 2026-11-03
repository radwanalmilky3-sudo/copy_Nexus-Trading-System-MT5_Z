import assert from 'node:assert/strict';
import test from 'node:test';
import { parseAgentStatusPayload } from '../src/lib/agent-status.ts';

test('invalid or absent agent-status payload is not treated as an empty live snapshot', () => {
  assert.deepEqual(parseAgentStatusPayload(null), { available: false, rows: [] });
  assert.deepEqual(parseAgentStatusPayload({ agents: null }), { available: false, rows: [] });
});

test('valid empty and populated snapshots are distinct from unavailable', () => {
  assert.deepEqual(parseAgentStatusPayload([]), { available: true, rows: [] });
  assert.deepEqual(parseAgentStatusPayload({ agents: [{ id: 'A1', status: 'idle' }, null] }), {
    available: true,
    rows: [{ id: 'A1', status: 'idle' }],
  });
});

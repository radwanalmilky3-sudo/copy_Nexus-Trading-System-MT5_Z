import assert from 'node:assert/strict';
import test from 'node:test';

test('research refresh repeats and stops after cleanup', async (t) => {
  const { startResearchRefresh } = await import('../src/components/research-lab/refresh.ts');
  t.mock.timers.enable({ apis: ['setInterval'] });
  let count = 0;
  const stop = startResearchRefresh(() => count++, { setInterval, clearInterval });
  t.mock.timers.tick(60_000);
  assert.equal(count, 1);
  t.mock.timers.tick(60_000);
  assert.equal(count, 2);
  stop();
  t.mock.timers.tick(60_000);
  assert.equal(count, 2);
});

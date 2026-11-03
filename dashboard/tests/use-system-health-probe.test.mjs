import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { classifyProbeStatus } from '../src/lib/system-health-status.ts';
import { hasMarketFeedBars } from '../src/lib/market-feed-status.ts';

// Execute the actual private probe without loading React or browser credentials.
const source = readFileSync(new URL('../src/hooks/useSystemHealth.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(`${source}\nexport { probe };`, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

async function runProbe(url, response) {
  const context = {
    exports: {}, process: { env: {} }, performance, AbortController, setTimeout, clearTimeout,
    fetch: async () => {
      if (response instanceof Error) throw response;
      return response;
    },
    require: (name) => {
      if (name === 'react') return {};
      if (name === '@/lib/api-client') return { getAuthHeaders: () => ({}) };
      if (name === '@/lib/system-health-status') return { classifyProbeStatus };
      if (name === '@/lib/market-feed-status') return { hasMarketFeedBars };
      throw new Error(`Unexpected dependency: ${name}`);
    },
  };
  vm.runInNewContext(compiled, context);
  const result = await context.exports.probe(url);
  return { ...result, classification: classifyProbeStatus(result.ok, result.status) };
}

for (const [name, payload, expected] of [
  ['running', { meta: { service_online: true } }, 'online'],
  ['stopped', { meta: { service_online: false } }, 'degraded'],
  ['missing meta', {}, 'degraded'],
  ['missing flag', { meta: {} }, 'degraded'],
  ['null meta', { meta: null }, 'degraded'],
  ['null payload', null, 'degraded'],
  ['string flag', { meta: { service_online: 'true' } }, 'degraded'],
]) {
  test(`agents HTTP 200: ${name}`, async () => {
    const result = await runProbe('/api/agents/status', Response.json(payload));
    assert.equal(result.classification, expected);
    assert.equal(result.status, 200);
  });
}

test('agents invalid JSON is degraded', async () => {
  const result = await runProbe('/api/agents/status', new Response('{'));
  assert.equal(result.classification, 'degraded');
});

test('agents HTTP failure cannot be overridden by a true flag', async () => {
  const result = await runProbe('/api/agents/status', Response.json(
    { meta: { service_online: true } }, { status: 503 },
  ));
  assert.equal(result.classification, 'degraded');
});

test('agents transport failure is offline', async () => {
  const result = await runProbe('/api/agents/status', new Error('network unavailable'));
  assert.equal(result.classification, 'offline');
});

test('other probes preserve their existing response handling', async () => {
  for (const url of ['/api/risk/status', '/api/positions', '/api/ml/traders/status']) {
    const result = await runProbe(url, Response.json({}));
    assert.equal(result.classification, 'online', url);
  }
  const health = await runProbe('/health', Response.json({ cpu_pct: 12, ram_pct: 34 }));
  assert.equal(health.classification, 'online');
  assert.equal(health.cpu, 12);
  assert.equal(health.ram, 34);
  for (const [data, expected] of [[[], 'degraded'], [[{ close: 1 }], 'online']]) {
    const market = await runProbe('/api/v2/market/ticks?symbol=XAUUSD&count=1&source=cache',
      Response.json({ success: true, data }));
    assert.equal(market.classification, expected);
  }
});

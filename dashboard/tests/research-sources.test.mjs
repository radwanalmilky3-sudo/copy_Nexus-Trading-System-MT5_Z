import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { withRequestTimeout } from '../src/lib/request-timeout.ts';

const code = ts.transpileModule(readFileSync(new URL('../src/components/research-lab/adapters.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
function sources(fetch) {
  const context = { exports: {}, process: { env: {} }, fetch,
    window: { localStorage: { getItem: () => 'test-token' } },
    require: (name) => {
      if (name.includes('request-timeout')) return { withRequestTimeout };
      throw new Error(name);
    },
  };
  vm.runInNewContext(code, context);
  return context.exports.researchSources;
}

test('unavailable is preserved rather than displayed as an empty connected source', async () => {
  const result = await sources(async () => Response.json({ status: 'unavailable', source: 'nexus-data:quality_runs', items: [] })).validation.load();
  assert.equal(result.status, 'unavailable');
  assert.equal(result.source, 'nexus-data:quality_runs');
  assert.equal(result.rows.length, 0);
});
test('a healthy empty dataset catalog remains available', async () => {
  const result = await sources(async (url, options) => {
    assert.ok(url.endsWith('/datasets'));
    assert.equal(options.headers.Authorization, 'Bearer test-token');
    return Response.json({ status: 'available', source: 'nexus-data:ohlcv', items: [], total: 0 });
  })['data-import'].load();
  assert.equal(result.status, 'available');
  assert.equal(result.rows.length, 0);
});
test('provenance uses the dataset fingerprint and provider without inventing a hash', async () => {
  const result = await sources(async () => Response.json({ status: 'available', source: 'nexus-data:ohlcv', items: [
    { dataset_id: 'ohlcv:XAUUSD:M5:mt5', name: 'XAUUSD/M5', source: 'mt5', content_hash: 'abc123', updated_at: '2026-10-19T10:00:00Z' },
  ] })).provenance.load();
  assert.equal(result.rows[0].hash, 'abc123');
  assert.equal(result.rows[0].origin, 'mt5');
});
test('malformed payload is an error rather than a healthy empty result', async () => {
  await assert.rejects(sources(async () => Response.json({ items: {} })).news.load());
});
test('unimplemented cleaning source reports unavailable', async () => {
  const result = await sources(() => { throw new Error('should not fetch'); }).cleaning.load();
  assert.equal(result.status, 'unavailable');
});
test('missing news sentiment is unknown rather than neutral', async () => {
  const result = await sources(async () => Response.json({ status: 'available', items: [
    { news_id: 'n1', headline: 'Official release', sentiment: null },
  ] })).news.load();
  assert.equal(result.rows[0].sentiment, 'unknown');
});
test('a quality run without checks or a score cannot be displayed as pass', async () => {
  const result = await sources(async () => Response.json({ status: 'available', items: [
    { quality_run_id: 'q1', status: 'complete', score: null, checks: {} },
  ] })).validation.load();
  assert.equal(result.rows[0].result, 'warning');
});
test('an explicitly warning quality run never turns into a green pass', async () => {
  const result = await sources(async () => Response.json({ status: 'available', items: [
    { quality_run_id: 'q1', status: 'warning', score: 0.95, checks: { format: true } },
  ] })).validation.load();
  assert.equal(result.rows[0].result, 'warning');
});
test('warning-only checks and explanations stay warnings rather than failed prices', async () => {
  const result = await sources(async () => Response.json({ status: 'available', items: [
    { quality_run_id: 'q1', status: 'warning', score: 0.6, checks: { recent_observation: false }, issues: [], warnings: ['قد يكون السوق مغلقًا'], content_hash: 'abc' },
  ] })).validation.load();
  assert.equal(result.rows[0].result, 'warning');
  assert.ok(result.rows[0].details.includes('قد يكون السوق مغلقًا'));
});
test('dataset audit is stale after the snapshot changes or the time budget expires', async () => {
  for (const quality of [{ status: 'passed', snapshot_current: false, expired: false }, { status: 'passed', snapshot_current: true, expired: true }]) {
    const result = await sources(async () => Response.json({ status: 'available', items: [
      { dataset_id: 'd1', name: 'XAUUSD/M5', source: 'mt5', status: 'stored', quality_summary: quality },
    ] }))['data-import'].load();
    assert.equal(result.rows[0].qualityStatus, 'stale');
  }
});

test('dataset keeps certificate time distinct from live fingerprint verification', async () => {
  const result = await sources(async () => Response.json({ status: 'available', items: [
    { dataset_id: 'd1', source: 'mt5_backfill', quality_summary: {
      status:'warning',snapshot_current:true,expired:false,checked_at:'2026-10-19T14:57:01Z',
      snapshot_verified_at:'2026-10-19T15:25:00Z',expires_at:'2026-10-19T15:57:01Z',warnings:['unclassified'],
    } },
  ] }))['data-import'].load();
  assert.equal(result.rows[0].qualityCheckedAt,'2026-10-19T14:57:01Z');
  assert.equal(result.rows[0].qualityVerifiedAt,'2026-10-19T15:25:00Z');
  assert.equal(result.rows[0].qualityExpiresAt,'2026-10-19T15:57:01Z');
  assert.equal(result.rows[0].historicalSlice,true);
  assert.equal(result.rows[0].qualityStatus,'warning');
});

test('calendar outage and gap evidence survive dataset adaptation', async () => {
  const result=await sources(async()=>Response.json({status:'available',items:[{
    dataset_id:'d1',source:'mt5',quality_summary:{status:'warning',snapshot_current:true,expired:false,
      calendar_summary:{state:'stale',reason:'Calendar expired',captured_at:'2026-10-19T08:00:00Z'},
      gap_summary:{confirmed_closed:2,covered_elsewhere:1,expected_quote_missing:3,unknown:4}},
  }]}))['data-import'].load();
  assert.equal(result.rows[0].calendarState,'stale');
  assert.equal(result.rows[0].calendarDetails,'Calendar expired');
  assert.ok(result.rows[0].gapDetails.includes('غير مؤكدة: 4'));
});

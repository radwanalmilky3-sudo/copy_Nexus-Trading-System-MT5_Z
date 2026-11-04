import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { withRequestTimeout } from '../src/lib/request-timeout.ts';

function loader(fetch) {
  const code = ts.transpileModule(readFileSync(new URL('../src/components/audit/evidence.ts', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const context = { exports: {}, process: { env: {} }, fetch,
    require: (name) => {
      if (name.includes('request-timeout')) return { withRequestTimeout };
      if (name.includes('api-client')) return { getAuthHeaders: () => ({ Authorization: 'Bearer example' }) };
      throw new Error(name);
    },
  };
  vm.runInNewContext(code, context);
  return context.exports.loadAuditEvidence;
}
const evidence = { status: 'available', source: 'project_audit', state: {
  file: 'DASHBOARD_STATE.json', sha256: 'a'.repeat(64), progress: { total: 5, done: 2, completion_percent: 40, by_status: { done: 2, pending: 3 } },
}, evidence: { count: 1, files: [{ path: 'report.md', sha256: 'b'.repeat(64), size_bytes: 12, modified_at: '2026-10-19T12:00:00Z' }] } };

test('audit loads real evidence through the authenticated gateway', async () => {
  const result = await loader(async (url, options) => {
    // The client now requests the same-origin proxy path (NEXT_PUBLIC_API_URL
    // is prepended when set; the test VM context has no env, so relative).
    assert.equal(url, '/api/audit/progress');
    assert.equal(options.headers.Authorization, 'Bearer example');
    return Response.json(evidence);
  })();
  assert.equal(result.state.progress.completion_percent, 40);
  assert.equal(result.evidence.files[0].sha256, 'b'.repeat(64));
});
test('an evidence outage is not replaced by an empty success', async () => {
  await assert.rejects(loader(async () => new Response('', { status: 503 }))(), /503/);
});
test('malformed evidence is rejected', async () => {
  await assert.rejects(loader(async () => Response.json({ status: 'available', evidence: {} }))());
});
